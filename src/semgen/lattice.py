"""Neighbor generation: operator moves filtered by the policy guard and the order proof (D10).

Every candidate child must pass ``guard`` (floors, protected nodes, absent nodes, context
edges) and ``check_order``. A failure raises; nothing is silently dropped.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from semgen.canonical import canonical_json, motif_hash
from semgen.model import PATIENT_ID, Motif
from semgen.operators import ALL_OPERATORS, concept_lift
from semgen.operators.base import (BOUNDARY_REASONS, CLINICAL_TYPES, TOP_REASONS, Blocked, ChangeRecord,
                                   GenContext, Move)
from semgen.operators.concept_lift import is_liftable
from semgen.order import OrderResult, check_order  # noqa: F401  (OrderResult re-exported)


class PolicyViolation(Exception):
    """A candidate move breaks a hard policy rule."""


class GeneralizationOrderError(Exception):
    """A candidate move is not provably more general than its parent."""


@dataclass(frozen=True)
class Neighbor:
    child: Motif
    child_hash: str
    changes: tuple[ChangeRecord, ...]


def _violation(rule: str, element: str, detail: str = "") -> PolicyViolation:
    return PolicyViolation(f"{rule}: {element}" + (f" ({detail})" if detail else ""))


def _absent_ids(m: Motif) -> set[str]:
    return {i for i in m.node_ids if m.node(i).polarity == "absent"}


def _absent_edges(m: Motif) -> dict:
    ab = _absent_ids(m)
    return {e.key: e for e in m.edges if e.s in ab or e.t in ab}


def guard(parent: Motif, child: Motif, change: ChangeRecord | None, ctx: GenContext) -> None:
    for nid in (PATIENT_ID, parent.anchor):
        if nid not in child.node_ids:
            raise _violation("protected_node_removed", nid)
    p_abs, c_abs = _absent_ids(parent), _absent_ids(child)
    for nid in sorted(p_abs):
        if nid not in child.node_ids or child.node(nid) != parent.node(nid):
            raise _violation("absent_node_changed", nid)
    for nid in sorted(c_abs - p_abs):
        raise _violation("absent_node_changed", nid, "absent node not in parent")
    p_edges, c_edges = _absent_edges(parent), _absent_edges(child)
    for key, e in sorted(p_edges.items()):
        ce = child.edge(*key)
        if ce is None or ce != e:
            raise _violation("absent_edge_changed", f"{key[0]}->{key[1]}")
    for key in sorted(set(c_edges) - set(p_edges)):
        raise _violation("absent_edge_changed", f"{key[0]}->{key[1]}", "absent edge not in parent")
    for e in sorted(child.edges, key=lambda x: x.key):
        if e.prov != "context":
            continue
        pe = parent.edge(e.s, e.t)
        if pe is not None and pe != e:
            raise _violation("context_edge_changed", f"{e.s}->{e.t}")
    # A NEW context edge (no parent counterpart) is allowed here on purpose: check_order
    # rejects it as ``extra_edge``, so it can never reach the lattice.
    for nid in sorted(parent.node_ids & child.node_ids):
        lost = sorted(a for a in set(parent.node(nid).attrs) - set(child.node(nid).attrs)
                      if ctx.config.attr_is_concept_dependent(a))
        if lost:
            raise _violation("dependent_attr_removed", nid, f"attrs={lost}")
    # Code changes are derived from the parent/child diff, never from the operator's ChangeRecord.
    h = ctx.hierarchy
    for nid in sorted(parent.node_ids & child.node_ids):
        pn, cn = parent.node(nid), child.node(nid)
        if pn.code == cn.code:
            continue
        what = f"node {nid}" + (f" via {change.op}" if change is not None else "")
        if pn.role == "context":
            raise _violation("context_code_changed", nid, what)
        if pn.polarity != "present":
            continue  # absent nodes are covered by absent_node_changed
        if pn.type not in CLINICAL_TYPES:
            raise _violation("lift_type_not_allowed", nid, f"type={pn.type}; {what}")
        if pn.value is not None:
            raise _violation("lift_on_valued_node", nid, what)
        dependent = sorted(a for a in pn.attrs if ctx.config.attr_is_concept_dependent(a))
        if dependent:
            raise _violation("lift_on_dependent_attr", nid, f"attrs={dependent}; {what}")
        if pn.code is None or cn.code is None or cn.code not in h.parents(pn.code):
            raise _violation("not_direct_parent", f"{pn.code}->{cn.code}", what)
        if not h.is_active(cn.code):
            raise _violation("inactive_target", str(cn.code), what)
        d = ctx.floors.check_lift(pn.code, cn.code)
        if not d.ok:
            raise _violation("floor_violation", f"{pn.code}->{cn.code}", f"reason={d.reason}; {what}")


def _same_motif(stored: Motif, new: Motif, h: str) -> None:
    if canonical_json(stored) != canonical_json(new):
        raise GeneralizationOrderError(f"hash collision on {h}: distinct motifs share a hash")


def _accept(parent: Motif, move: Move, ctx: GenContext) -> None:
    guard(parent, move.child, move.change, ctx)
    r = check_order(parent, move.child, ctx)
    if not r.ok:
        raise GeneralizationOrderError(f"{r.reason} at {r.where}: {move.change}")


def neighbors(motif: Motif, ctx: GenContext) -> tuple[list[Neighbor], list[Blocked]]:
    parent_hash = motif_hash(motif)
    found: dict[str, Neighbor] = {}
    blocked: list[Blocked] = []
    for op in ALL_OPERATORS:
        res = op(motif, ctx)
        blocked.extend(res.blocked)
        for mv in res.moves:
            h = motif_hash(mv.child)
            if h == parent_hash:
                continue
            _accept(motif, mv, ctx)
            if h in found:
                n = found[h]
                _same_motif(n.child, mv.child, h)
                found[h] = Neighbor(n.child, h, n.changes + (mv.change,))
            else:
                found[h] = Neighbor(mv.child, h, (mv.change,))
    return list(found.values()), blocked


@dataclass(frozen=True)
class Candidate:
    hash: str
    depth: int
    motif: Motif
    origin: str = "lattice"  # lattice (BFS) | axis (found only by a per-node climb)


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
    status: str = "unknown"  # exhausted | depth_limited | candidate_limited; hand-built lattices claim nothing
    unexpanded: int = 0
    axes: dict[str, NodeAxis] = field(default_factory=dict)  # per liftable root node; status above ignores them


def _int_arg(name: str, v, lo: int) -> None:
    if isinstance(v, bool) or not isinstance(v, int) or v < lo:
        raise ValueError(f"{name} must be an int >= {lo}, got {v!r}")


def _axis_status(reasons: set[str]) -> str:
    if reasons - BOUNDARY_REASONS - TOP_REASONS:
        return "policy_restricted"
    return "reached_hierarchy_top" if reasons & TOP_REASONS else "reached_floor"


def _climb(root_hash: str, node: str, ctx: GenContext, candidates: dict[str, Candidate], edges: list[LatticeEdge],
           blocked: list[tuple[str, Blocked]], seen_pairs: set[tuple[str, str]], expanded: set[str]) -> NodeAxis:
    """Breadth-first over accepted one-step lifts of ``node`` alone; finite because the ancestor set is."""
    reached: set[str] = set()
    reasons: set[str] = set()
    visited = {root_hash}
    level = [root_hash]
    while level:
        nxt: list[str] = []
        for h in level:
            motif = candidates[h].motif
            res = concept_lift(motif, ctx)
            bl = [b for b in res.blocked if b.target == node]
            reasons.update(b.reason for b in bl)
            if h not in expanded:  # the BFS logged every block on the motifs it expanded
                blocked.extend((h, b) for b in bl)
            for mv in res.moves:
                if mv.change.target != node:
                    continue
                ch = motif_hash(mv.child)
                if ch == h:
                    continue
                _accept(motif, mv, ctx)
                if ch in candidates:
                    _same_motif(candidates[ch].motif, mv.child, ch)
                else:
                    candidates[ch] = Candidate(ch, candidates[h].depth + 1, mv.child, "axis")
                if (h, ch) not in seen_pairs:
                    seen_pairs.add((h, ch))
                    edges.append(LatticeEdge(h, ch, (mv.change,)))
                reached.add(mv.change.after)
                if ch not in visited:
                    visited.add(ch)
                    nxt.append(ch)
        level = nxt
    return NodeAxis(node, _axis_status(reasons), tuple(sorted(reached)), tuple(sorted(reasons)))


def enumerate_lattice(root: Motif, ctx: GenContext, max_depth: int | None = None,
                      max_candidates: int | None = None, *, climb: bool = True) -> Lattice:
    """Level-by-level BFS from ``root`` with global dedup, then per-node climbs; every candidate is proven <= root."""
    if max_depth is None:
        max_depth = ctx.config.max_depth
    if max_candidates is None:
        max_candidates = ctx.config.max_candidates
    _int_arg("max_depth", max_depth, 0)
    _int_arg("max_candidates", max_candidates, 1)
    root_hash = motif_hash(root)
    candidates: dict[str, Candidate] = {root_hash: Candidate(root_hash, 0, root)}
    edges: list[LatticeEdge] = []
    blocked: list[tuple[str, Blocked]] = []
    seen_pairs: set[tuple[str, str]] = set()
    expanded: set[str] = set()
    frontier = [root_hash]
    depth = 0
    over_budget = False
    unexpanded = 0
    while frontier and depth < max_depth and not over_budget:
        nxt: list[str] = []
        for i, h in enumerate(frontier):
            ns, bl = neighbors(candidates[h].motif, ctx)
            blocked.extend((h, b) for b in bl)
            expanded.add(h)
            for n in ns:
                if n.child_hash in candidates:
                    _same_motif(candidates[n.child_hash].motif, n.child, n.child_hash)
                elif len(candidates) >= max_candidates:
                    over_budget = True
                    continue
                else:
                    candidates[n.child_hash] = Candidate(n.child_hash, depth + 1, n.child)
                    nxt.append(n.child_hash)
                if (h, n.child_hash) not in seen_pairs:
                    seen_pairs.add((h, n.child_hash))
                    edges.append(LatticeEdge(h, n.child_hash, n.changes))
            if over_budget:
                unexpanded = len(set(frontier[i + 1:]) | set(nxt))
                break
        frontier = nxt
        depth += 1
    if over_budget:
        status = "candidate_limited"
    elif frontier and any(neighbors(candidates[h].motif, ctx)[0] for h in frontier):
        status, unexpanded = "depth_limited", len(frontier)
    else:
        status = "exhausted"
    axes: dict[str, NodeAxis] = {}
    if climb:
        for node in sorted((n for n in root.nodes if is_liftable(n)), key=lambda n: n.id):
            axes[node.id] = _climb(root_hash, node.id, ctx, candidates, edges, blocked, seen_pairs, expanded)
    for h, c in candidates.items():
        r = check_order(root, c.motif, ctx)
        if not r.ok:
            raise GeneralizationOrderError(f"root proof failed: {r.reason} at {r.where} for {h}")
    return Lattice(root_hash, candidates, edges, blocked, status, unexpanded, axes)
