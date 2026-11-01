"""Neighbor generation: operator moves filtered by the policy guard and the order proof (D10).

Every candidate child must pass ``guard`` (floors, protected nodes, absent nodes, context
edges) and ``check_order``. A failure raises; nothing is silently dropped.
"""
from __future__ import annotations

from dataclasses import dataclass

from semgen.canonical import motif_hash
from semgen.model import PATIENT_ID, Motif
from semgen.operators import ALL_OPERATORS
from semgen.operators.base import Blocked, ChangeRecord, GenContext
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
    if change is not None and change.op == "concept_lift":
        if not ctx.hierarchy.is_active(change.after):
            raise _violation("inactive_target", str(change.after), f"node {change.target}")
        d = ctx.floors.check_lift(change.before, change.after)
        if not d.ok:
            raise _violation("floor_violation", f"{change.before}->{change.after}", f"reason={d.reason}")


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
            guard(motif, mv.child, mv.change, ctx)
            r = check_order(motif, mv.child, ctx)
            if not r.ok:
                raise GeneralizationOrderError(f"{r.reason} at {r.where}: {mv.change}")
            if h in found:
                n = found[h]
                found[h] = Neighbor(n.child, h, n.changes + (mv.change,))
            else:
                found[h] = Neighbor(mv.child, h, (mv.change,))
    return list(found.values()), blocked
