"""Budgeted breadth-first enumeration of the generalization lattice, per-node climbs and the final proofs (design §9).

States are bundles, deduplicated by hash (a bundle of one hashes as its motif). The search is bounded only by an
explicit ``Budget`` (unbounded by default). After the search every candidate's first-path edge is re-proven by
``check_bundle_order`` and, for a bundle of one, every candidate is checked against the root with ``check_order``.
"""
from __future__ import annotations

import contextlib
import dataclasses
import json
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path

from semgen.bundle import MotifBundle, bundle_canonical_json
from semgen.canonical import canonical_json
from semgen.interfaces import BOUNDARY_REASONS, TOP_REASONS, Blocked, ChangeRecord, GenContext
from semgen.lattice.moves import (
    _lifts_of_observation_nodes,
    _same_state,
    _slots,
    accept_lift_step,
    bundle_neighbors,
    operators_of,
    state_hash,
)
from semgen.lattice.policy import GeneralizationOrderError
from semgen.model import Motif
from semgen.operators.attribute_deletion import attribute_deletion
from semgen.operators.concept_lift import concept_lift, is_liftable
from semgen.operators.motif_deletion import motif_deletion
from semgen.operators.normative_bucketing import normative_bucketing
from semgen.order import check_bundle_order, check_order


@dataclass(frozen=True)
class Candidate:
    hash: str
    depth: int
    bundle: MotifBundle
    origin: str = "lattice"  # lattice (BFS) | axis (found only by a per-node climb)

    @property
    def motif(self) -> Motif:
        """The candidate's motif (a bundle of one plain part only; raises otherwise)."""
        return self.bundle.single_motif


def candidate_row(c: Candidate) -> dict:
    """The exported row: key ``motif`` (canonical motif JSON) for a bundle of one, ``bundle`` otherwise."""
    if c.bundle.is_single:
        key, body = "motif", canonical_json(c.bundle.single_motif)
    else:
        key, body = "bundle", bundle_canonical_json(c.bundle)
    return {"hash": c.hash, "depth": c.depth, "origin": c.origin, key: json.loads(body)}


def json_line(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n"


@dataclass(frozen=True)
class LatticeEdge:
    parent: str
    child: str
    changes: tuple[ChangeRecord, ...]


@dataclass(frozen=True)
class NodeAxis:
    node: str
    status: str  # reached_floor | reached_hierarchy_top | policy_restricted
    reached: tuple[str, ...]
    stopped_by: tuple[str, ...]


@dataclass(frozen=True)
class Lattice:
    root: str
    candidates: dict[str, Candidate]
    edges: list[LatticeEdge]
    blocked: list[tuple[str, Blocked]]  # (hash of the candidate it came from, blocked move)
    status: str = "unknown"  # exhausted | budget_limited; hand-built lattices claim nothing
    unexpanded: int = 0
    axes: dict[str, NodeAxis] = field(default_factory=dict)  # per liftable root node; status above ignores them
    refused: int = 0         # new states not stored because max_states was reached
    budget_hit: tuple[str, ...] = ()   # the budget that stopped the search: max_states | max_depth | seconds
    state_space_estimate: int | None = None   # orientation only, never an upper bound (design §9)


def _int_arg(name: str, v, lo: int) -> None:
    if isinstance(v, bool) or not isinstance(v, int) or v < lo:
        raise ValueError(f"{name} must be an int >= {lo}, got {v!r}")


@dataclass(frozen=True)
class Budget:
    """Explicit search bounds; all None (the default) is unbounded. Never a correctness limit.

    ``max_states`` counts every stored state including the root (a new state beyond it is refused);
    ``max_depth``: states at that depth are stored but not expanded; ``seconds`` is checked before each
    expansion (a run stopped by it is not covered by the byte-identity guarantee).
    """

    max_states: int | None = None
    max_depth: int | None = None
    seconds: float | None = None

    def __post_init__(self) -> None:
        if self.max_states is not None:
            _int_arg("max_states", self.max_states, 1)
        if self.max_depth is not None:
            _int_arg("max_depth", self.max_depth, 0)
        if self.seconds is not None and (isinstance(self.seconds, bool) or not isinstance(self.seconds, (int, float))
                                         or not self.seconds >= 0):
            raise ValueError(f"seconds must be a number >= 0, got {self.seconds!r}")

    def to_json(self) -> dict:
        return asdict(self)


def _floor_ancestors(code: str, ctx: GenContext, role: str | None = None, node_id: str | None = None) -> set[str]:
    """Ancestors reachable by single lifts the floor accepts (active parents only); ``code`` excluded."""
    h, seen, todo = ctx.hierarchy, set(), [code]
    while todo:
        c = todo.pop()
        for p in sorted(h.parents(c)):
            if p not in seen and h.is_active(p) and ctx.floors.check_lift(c, p, role=role, node_id=node_id,
                                                                          cohort=ctx.cohort).ok:
                seen.add(p)
                todo.append(p)
    return seen


def state_space_estimate(bundle: MotifBundle, ctx: GenContext) -> int:
    """Orientation only and **not an upper bound** (design §9): over every part, the product of
    (1 + floor-accepted ancestors) per liftable node, 3 per bucketable value and 2 per deletable constraint (the
    root's bucketing and attribute-deletion moves), times 2 per candidate motif deletion of the root."""
    est = 1
    for _, m in _slots(bundle):
        for n in sorted(m.nodes, key=lambda n: n.id):
            if (is_liftable(n, ctx) and n.value is None and not n.observations and ctx.hierarchy.is_active(n.code)
                    and not any(ctx.config.attr_is_concept_dependent(a) for a in n.attrs)):
                est *= 1 + len(_floor_ancestors(n.code, ctx, n.role, n.id))
        est *= 3 ** len(normative_bucketing(m, ctx).moves) * 2 ** len(attribute_deletion(m, ctx).moves)
    if not bundle.is_single:
        est *= 2 ** len(motif_deletion(bundle, ctx).moves)
    return est


def _axis_status(reasons: set[str]) -> str:
    if reasons - BOUNDARY_REASONS - TOP_REASONS:
        return "policy_restricted"
    return "reached_hierarchy_top" if reasons & TOP_REASONS else "reached_floor"


class _Search:
    """The mutable state of one enumeration: candidates in acceptance order, edges, blocks, first-path parents."""

    def __init__(self, root: MotifBundle, ctx: GenContext, stream) -> None:
        self.ctx, self.stream = ctx, stream
        self.root_hash = state_hash(root)
        self.candidates: dict[str, Candidate] = {}
        self.first: dict[str, tuple[str, Mapping | None]] = {}   # child -> (first parent, its certificate)
        self.edges: list[LatticeEdge] = []
        self.blocked: list[tuple[str, Blocked]] = []
        self.seen_pairs: set[tuple[str, str]] = set()
        self.expanded: set[str] = set()
        self.store(Candidate(self.root_hash, 0, root), None, None)

    def store(self, c: Candidate, parent: str | None, certificate: Mapping | None) -> None:
        self.candidates[c.hash] = c
        if parent is not None:
            self.first[c.hash] = (parent, certificate)
        if self.stream is not None:
            self.stream.write(json_line(candidate_row(c)))
            self.stream.flush()

    def edge(self, parent: str, child: str, changes: tuple[ChangeRecord, ...]) -> None:
        if (parent, child) not in self.seen_pairs:
            self.seen_pairs.add((parent, child))
            self.edges.append(LatticeEdge(parent, child, changes))

    def climb(self, part_id: str | None, node: str) -> NodeAxis:
        """Breadth-first over accepted one-step lifts of ``node`` alone (in part ``part_id``; None = the bundle of
        one); finite because the ancestor set is."""
        ctx, candidates = self.ctx, self.candidates
        reached: set[str] = set()
        reasons: set[str] = set()
        visited = {self.root_hash}
        level = [self.root_hash]
        while level:
            nxt: list[str] = []
            for h in level:
                state = candidates[h].bundle
                motif = state.single_motif if part_id is None else state.part(part_id).motif
                res = concept_lift(motif, ctx)
                moves, lift_blocks = _lifts_of_observation_nodes(motif, res.moves)
                bl = [b for b in res.blocked + lift_blocks if b.target == node]
                reasons.update(b.reason for b in bl)
                if h not in self.expanded:  # the BFS logged every block on the states it expanded
                    self.blocked.extend((h, b) for b in bl)
                for mv in moves:
                    if mv.change.target != node:
                        continue
                    step = accept_lift_step(state, part_id, motif, mv, ctx)
                    if step is None:
                        continue
                    child, ch = step
                    if ch in candidates:
                        _same_state(candidates[ch].bundle, child, ch)
                    else:
                        self.store(Candidate(ch, candidates[h].depth + 1, child, "axis"), h, None)
                    self.edge(h, ch, (mv.change,))
                    reached.add(mv.change.after)
                    if ch not in visited:
                        visited.add(ch)
                        nxt.append(ch)
            level = nxt
        return NodeAxis(node, _axis_status(reasons), tuple(sorted(reached)), tuple(sorted(reasons)))


def enumerate_lattice(root: Motif | MotifBundle, ctx: GenContext, budget: Budget = Budget(), *, climb: bool = True,
                      progress: Path | None = None) -> Lattice:
    """Level-by-level BFS from ``root`` with global dedup, then per-node climbs; every candidate is proven <= root.

    A ``MotifBundle`` root sets ``ctx.subject`` and ``ctx.cohort`` from the bundle (a bare ``Motif`` root keeps ``ctx`` as given).
    ``exhausted`` iff no state was refused and no stored state with a neighbour is left unexpanded; otherwise
    ``budget_limited`` with ``budget_hit``. The climb ignores the budget. ``progress``, when given, receives every
    accepted candidate as one JSON line in acceptance (BFS) order as it is accepted: streamed to
    ``<progress>.partial`` and renamed to ``progress`` only after the root proof passes (a stale ``progress`` file
    is removed first, so a failed run never leaves a complete-looking one).

    Root proof: every candidate's first-path edge (from the parent it was first reached from) is re-proven by
    ``check_bundle_order``, so the per-edge proofs compose along a path to the root; for a bundle of one, every
    candidate is also checked against the root with ``check_order``.
    """
    if not isinstance(budget, Budget):
        raise TypeError(f"budget must be a Budget, got {budget!r}")
    if isinstance(root, MotifBundle):
        bundle_root = root
        ctx = dataclasses.replace(ctx, subject=root.subject, cohort=root.cohort)
    else:
        bundle_root = MotifBundle.of(root)
    estimate = state_space_estimate(bundle_root, ctx)
    partial = None
    if progress is not None:
        progress = Path(progress)
        partial = progress.with_name(progress.name + ".partial")
        progress.unlink(missing_ok=True)   # a stale file from an earlier run never survives into this one
    opened = partial.open("w", encoding="utf-8", newline="\n") if partial is not None else contextlib.nullcontext()
    with opened as stream:
        s = _Search(bundle_root, ctx, stream)
        status, unexpanded, refused, hit = _bfs(s, budget)
        axes: dict[str, NodeAxis] = {}
        if climb and concept_lift in operators_of(ctx).motif:
            for part_id, motif in _slots(bundle_root):
                for node in sorted((n for n in motif.nodes if is_liftable(n, ctx)), key=lambda n: n.id):
                    key = node.id if bundle_root.is_single else f"{part_id}/{node.id}"
                    axes[key] = s.climb(None if bundle_root.is_single else part_id, node.id)
    candidates = s.candidates
    for h, c in candidates.items():
        if h == s.root_hash:
            continue
        parent, certificate = s.first[h]
        r = check_bundle_order(candidates[parent].bundle, c.bundle, ctx, certificate)
        if not r.ok or candidates[parent].depth >= c.depth:
            raise GeneralizationOrderError(f"first-path proof failed: {r.reason} at {r.where} for {h} from {parent}")
    if bundle_root.is_single:
        for h, c in candidates.items():
            r = check_order(bundle_root.single_motif, c.motif, ctx)
            if not r.ok:
                raise GeneralizationOrderError(f"root proof failed: {r.reason} at {r.where} for {h}")
    if partial is not None:
        partial.replace(progress)   # complete only once every proof passed
    return Lattice(s.root_hash, candidates, s.edges, s.blocked, status, unexpanded, axes, refused, hit, estimate)


def _bfs(s: _Search, budget: Budget) -> tuple[str, int, int, tuple[str, ...]]:
    """The budgeted breadth-first search; returns (status, unexpanded, refused, budget_hit)."""
    max_depth, max_states = budget.max_depth, budget.max_states
    start = time.monotonic()
    frontier = [s.root_hash]
    depth = 0
    over_budget = timed_out = False
    unexpanded = refused = 0
    while frontier and (max_depth is None or depth < max_depth) and not over_budget:
        nxt: list[str] = []
        for i, h in enumerate(frontier):
            if budget.seconds is not None and time.monotonic() - start >= budget.seconds:
                timed_out = True
                unexpanded = len(set(frontier[i:]) | set(nxt))
                break
            ns, bl = bundle_neighbors(s.candidates[h].bundle, s.ctx)
            s.blocked.extend((h, b) for b in bl)
            s.expanded.add(h)
            for n in ns:
                if n.child_hash in s.candidates:
                    _same_state(s.candidates[n.child_hash].bundle, n.child, n.child_hash)
                elif max_states is not None and len(s.candidates) >= max_states:
                    over_budget = True
                    refused += 1
                    continue
                else:
                    s.store(Candidate(n.child_hash, depth + 1, n.child), h, n.certificate)
                    nxt.append(n.child_hash)
                s.edge(h, n.child_hash, n.changes)
            if over_budget:
                unexpanded = len(set(frontier[i + 1:]) | set(nxt))
                break
        if timed_out:
            break
        frontier = nxt
        depth += 1
    hit: tuple[str, ...] = ()
    if over_budget:
        hit = ("max_states",)
    elif timed_out:
        hit = ("seconds",)
    elif frontier and any(bundle_neighbors(s.candidates[h].bundle, s.ctx)[0] for h in frontier):
        hit, unexpanded = ("max_depth",), len(frontier)   # a depth cap on a dead end is still exhausted
    return ("budget_limited" if hit else "exhausted"), unexpanded, refused, hit
