"""SNOMED CT RF2 Snapshot loader: inferred IS-A hierarchy, FSN lookup and direction helpers."""
from __future__ import annotations

import hashlib
import os
import pickle
import re
import tempfile
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from semgen.config import GenConfig

ROOT_ID = "138875005"
IS_A = "116680003"
INFERRED = "900000000000011006"
FSN_TYPE = "900000000000003001"
DEFAULT_RF2_DIR = Path(
    "/Users/suryanshshivaprasad/Documents/HDX/SnomedCT_InternationalRF2_PRODUCTION_20260201T120000Z"
    "/Snapshot/Terminology"
)
DEFAULT_CACHE_DIR = Path("data/cache")


class FsnError(Exception):
    """Raised when an FSN label does not resolve to exactly one active concept."""


class Hierarchy:
    """Inferred IS-A graph. Only upward (child -> parent) edges are ever read."""

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

    def ancestors(self, c: str) -> frozenset[str]:
        """Strict transitive closure over parents (iterative, memoised)."""
        memo = self._memo
        if c in memo:
            return memo[c]
        stack = [c]
        while stack:
            node = stack[-1]
            if node in memo:
                stack.pop()
                continue
            pending = [p for p in self.parents(node) if p not in memo]
            if pending:
                stack.extend(pending)  # IS-A is acyclic, so this terminates
                continue
            acc: set[str] = set()
            for p in self.parents(node):
                acc.add(p)
                acc |= memo[p]
            memo[node] = frozenset(acc)
            stack.pop()
        return memo[c]

    def ancestors_or_self(self, c: str) -> frozenset[str]:
        return self.ancestors(c) | {c}

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


def default_rf2_dir() -> Path:
    env = os.environ.get("SEMGEN_RF2_DIR")
    return Path(env) if env else DEFAULT_RF2_DIR


def _find(d: Path, pattern: str) -> Path:
    hits = sorted(d.glob(pattern))
    if len(hits) != 1:
        raise FileNotFoundError(f"expected exactly one {pattern} in {d}, found {len(hits)}")
    return hits[0]


def _read(path: Path, cols: list[str]) -> pl.DataFrame:
    return pl.read_csv(
        path, separator="\t", infer_schema=False, quote_char=None, columns=cols
    )


def load_rf2(terminology_dir: str | Path, cache_dir: str | Path | None = None) -> Hierarchy:
    d = Path(terminology_dir).resolve()
    # sct2_Relationship_ cannot match StatedRelationship or RelationshipConcreteValues_.
    cf = _find(d, "sct2_Concept_Snapshot_*.txt")
    df = _find(d, "sct2_Description_Snapshot*.txt")
    rf = _find(d, "sct2_Relationship_Snapshot_*.txt")
    m = re.search(r"_INT_(\d{8})", rf.name)
    release = m.group(1) if m else "UNKNOWN"
    edition = "International" if "_INT_" in rf.name else "UNKNOWN"

    sig = [str(d)]
    for f in (cf, df, rf):
        st = f.stat()
        sig.append(f"{f.name}|{st.st_size}|{st.st_mtime_ns}")
    key = hashlib.sha256("\n".join(sig).encode()).hexdigest()[:12]
    cdir = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
    cache = cdir / f"snomed_{release}_{key}.pkl"
    if cache.exists():
        try:
            with cache.open("rb") as fh:
                h = pickle.load(fh)
            if isinstance(h, Hierarchy):
                h._memo = {}
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


def check_floors(config: GenConfig, h: Hierarchy) -> None:
    from semgen.config import ConfigError

    bad = [f for f in config.floors if not h.is_active(f)]
    if bad:
        raise ConfigError(f"floor concept(s) unknown or inactive in SNOMED {h.release}: {', '.join(bad)}")
