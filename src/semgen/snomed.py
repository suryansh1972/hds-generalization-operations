"""SNOMED CT RF2 Snapshot loader: inferred IS-A hierarchy, FSN lookup and direction helpers."""
from __future__ import annotations

import hashlib
import os
import pickle
import re
import tempfile
from collections import deque
from pathlib import Path

import polars as pl

from semgen.settings import default_cache_dir, env_path

ROOT_ID = "138875005"
IS_A = "116680003"
INFERRED = "900000000000011006"
CACHE_VERSION = "2"
_TAG_RE = re.compile(r"\(([^()]+)\)$")
FSN_TYPE = "900000000000003001"


class FsnError(Exception):
    """Raised when an FSN label does not resolve to exactly one active concept."""


class HierarchyCycleError(ValueError):
    """Raised when the IS-A input contains a cycle (malformed hierarchy)."""


class Hierarchy:
    """Inferred IS-A graph readable in both directions: parents/ancestors go up, children/descendants go down.

    Lift reads upward only (parents, ancestors); downward reads (children, descendants) are for explicit queries.
    """

    characteristic_type = "inferred"

    def __init__(
        self,
        parents: dict[str, frozenset[str]],
        fsn: dict[str, str],
        active: frozenset[str],
        release: str,
        edition: str,
    ) -> None:
        self._parents = parents
        self._fsn = fsn
        self._active = active
        self.release = release
        self.edition = edition
        self._by_fsn: dict[str, list[str]] = {}
        for c, term in fsn.items():
            if c in active:
                self._by_fsn.setdefault(term, []).append(c)
        self._memo: dict[str, frozenset[str]] = {}
        self._children: dict[str, set[str]] | None = None
        self._desc_memo: dict[str, frozenset[str]] = {}
        self._count_memo: dict[str, int] = {}

    @classmethod
    def from_maps(
        cls,
        parents: dict[str, set[str]],
        fsn: dict[str, str],
        active: set[str],
        release: str = "TEST",
        edition: str = "TEST",
    ) -> Hierarchy:
        return cls(
            {c: frozenset(p) for c, p in parents.items()},
            dict(fsn),
            frozenset(active),
            release,
            edition,
        )

    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        state["_memo"] = {}
        state["_children"] = None
        state["_desc_memo"] = {}
        state["_count_memo"] = {}
        return state

    def parents(self, c: str) -> frozenset[str]:
        return self._parents.get(c, frozenset())

    def is_active(self, c: str) -> bool:
        return c in self._active

    def fsn(self, c: str) -> str | None:
        return self._fsn.get(c) if c in self._active else None

    def resolve_fsn(self, label: str) -> str:
        hits = self._by_fsn.get(label, [])
        if len(hits) != 1:
            raise FsnError(f"FSN {label!r} matched {len(hits)} active concepts (need exactly 1)")
        return hits[0]

    @property
    def n_active(self) -> int:
        """Number of active concepts (the N of intrinsic information content)."""
        return len(self._active)

    def ancestors(self, c: str) -> frozenset[str]:
        """Strict transitive closure over parents (iterative, memoised). A cycle (malformed input; IS-A in a
        released hierarchy is acyclic) raises ``HierarchyCycleError`` instead of looping."""
        memo = self._memo
        if c in memo:
            return memo[c]
        stack = [c]
        expanding: set[str] = set()   # nodes whose parents are being resolved: a chain of IS-A steps from c
        while stack:
            node = stack[-1]
            if node in memo:
                stack.pop()
                continue
            pending = [p for p in self.parents(node) if p not in memo]
            if pending:
                if node in expanding or any(p in expanding for p in pending):
                    raise HierarchyCycleError(f"IS-A cycle through {node!r}")
                expanding.add(node)
                stack.extend(pending)
                continue
            expanding.discard(node)
            acc: set[str] = set()
            for p in self.parents(node):
                acc.add(p)
                acc |= memo[p]
            memo[node] = frozenset(acc)
            stack.pop()
        return memo[c]

    def ancestors_or_self(self, c: str) -> frozenset[str]:
        return self.ancestors(c) | {c}

    def _child_index(self) -> dict[str, set[str]]:
        if self._children is None:
            children: dict[str, set[str]] = {}
            for child, ps in self._parents.items():
                for p in ps:
                    children.setdefault(p, set()).add(child)
            self._children = children
        return self._children

    def children(self, c: str) -> frozenset[str]:
        return frozenset(self._child_index().get(c, ()))

    def descendants(self, c: str) -> frozenset[str]:
        """Strict ECL `< c` (activity not filtered)."""
        return self.descendants_or_self(c) - {c}

    def descendant_count(self, c: str) -> int:
        """Distinct active strict descendants; plain traversal, memoises integers only."""
        if c in self._count_memo:
            return self._count_memo[c]
        children = self._child_index()
        seen = {c}
        stack = [c]
        while stack:
            for k in children.get(stack.pop(), ()):
                if k not in seen:
                    seen.add(k)
                    stack.append(k)
        seen.discard(c)
        n = self._count_memo[c] = sum(1 for k in seen if k in self._active)
        return n

    def semantic_tag(self, c: str) -> str | None:
        """Trailing parenthesised tag of an active concept's FSN, e.g. 'disorder'."""
        m = _TAG_RE.search(self.fsn(c) or "")
        return m.group(1) if m else None

    def descendants_or_self(self, c: str) -> frozenset[str]:
        """ECL `<< c`: c plus every concept below it (iterative, memoised, activity not filtered)."""
        children = self._child_index()
        memo = self._desc_memo
        stack = [c]
        while stack:
            node = stack[-1]
            if node in memo:
                stack.pop()
                continue
            kids = children.get(node, ())
            pending = [k for k in kids if k not in memo]
            if pending:
                stack.extend(pending)  # IS-A is acyclic, so this terminates
                continue
            acc: set[str] = {node}
            for k in kids:
                acc |= memo[k]
            memo[node] = frozenset(acc)
            stack.pop()
        return memo[c]

    def is_descendant_or_self(self, concept: str, of_: str) -> bool:
        """ECL `concept << of_`."""
        return of_ in self.ancestors_or_self(concept)

    def depth(self, c: str) -> int:
        """Shortest IS-A distance to the SNOMED root; ValueError if unreachable."""
        seen = {c}
        frontier = deque([(c, 0)])
        while frontier:
            node, d = frontier.popleft()
            if node == ROOT_ID:
                return d
            for p in self.parents(node):
                if p not in seen:
                    seen.add(p)
                    frontier.append((p, d + 1))
        raise ValueError(f"concept {c!r} has no IS-A path to {ROOT_ID}")


def default_rf2_dir() -> Path | None:
    """The release named by ``SEMGEN_RF2_DIR`` (resolved by ``terminology_dir``), or None when unset."""
    env = env_path("SEMGEN_RF2_DIR")
    return terminology_dir(env) if env is not None else None


def terminology_dir(path: str | Path) -> Path:
    """The ``Snapshot/Terminology`` directory of a release given as its root, its ``Snapshot`` or that directory."""
    p = Path(path).expanduser()
    for cand in (p / "Snapshot" / "Terminology", p / "Terminology"):
        if cand.is_dir():
            return cand
    return p


def _find(d: Path, pattern: str) -> Path:
    hits = sorted(d.glob(pattern))
    if len(hits) != 1:
        raise FileNotFoundError(f"expected exactly one {pattern} in {d}, found {len(hits)}")
    return hits[0]


def _read(path: Path, cols: list[str]) -> pl.DataFrame:
    return pl.read_csv(
        path, separator="\t", infer_schema=False, quote_char=None, columns=cols
    )


def load_rf2(rf2_dir: str | Path, cache_dir: str | Path | None = None) -> Hierarchy:
    """Load (or read from the cache) the inferred hierarchy of the release at ``rf2_dir`` (see ``terminology_dir``)."""
    d = terminology_dir(rf2_dir).resolve()
    # sct2_Relationship_ cannot match StatedRelationship or RelationshipConcreteValues_.
    cf = _find(d, "sct2_Concept_Snapshot_*.txt")
    df = _find(d, "sct2_Description_Snapshot*.txt")
    rf = _find(d, "sct2_Relationship_Snapshot_*.txt")
    m = re.search(r"_INT_(\d{8})", rf.name)
    release = m.group(1) if m else "UNKNOWN"
    edition = "International" if "_INT_" in rf.name else "UNKNOWN"

    sig = [str(d), f"v{CACHE_VERSION}"]
    for f in (cf, df, rf):
        st = f.stat()
        sig.append(f"{f.name}|{st.st_size}|{st.st_mtime_ns}")
    key = hashlib.sha256("\n".join(sig).encode()).hexdigest()[:12]
    cdir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    cache = cdir / f"snomed_{release}_{key}.pkl"
    if cache.exists():
        try:
            with cache.open("rb") as fh:
                h = pickle.load(fh)
            if isinstance(h, Hierarchy):
                h._memo = {}
                h._children = None
                h._desc_memo = {}
                h._count_memo = {}
                return h
        except Exception:
            pass  # corrupt cache: rebuild

    concepts = _read(cf, ["id", "active"]).filter(pl.col("active") == "1")
    active = frozenset(concepts["id"].to_list())

    rel = _read(rf, ["active", "sourceId", "destinationId", "typeId", "characteristicTypeId"]).filter(
        (pl.col("active") == "1")
        & (pl.col("typeId") == IS_A)
        & (pl.col("characteristicTypeId") == INFERRED)
    )
    pmap: dict[str, set[str]] = {}
    for s, t in zip(rel["sourceId"].to_list(), rel["destinationId"].to_list()):
        pmap.setdefault(s, set()).add(t)

    desc = _read(df, ["active", "conceptId", "typeId", "term"]).filter(
        (pl.col("active") == "1") & (pl.col("typeId") == FSN_TYPE)
    )
    fsn: dict[str, str] = {}
    for c, term in zip(desc["conceptId"].to_list(), desc["term"].to_list()):
        if c in active:
            fsn[c] = term

    h = Hierarchy.from_maps(pmap, fsn, set(active), release, edition)

    cdir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=cdir, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            pickle.dump(h, fh, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, cache)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return h
