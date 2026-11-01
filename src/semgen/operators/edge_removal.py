"""Edge removal: drop one edge, cascade patient-edge targets, and clean up orphaned nodes."""
from __future__ import annotations

from collections import deque

from semgen.model import PATIENT_ID, Motif
from semgen.operators.base import Blocked, ChangeRecord, GenContext, Move, OperatorResult, is_absent_touching

OP = "edge_removal"


def _label(key: tuple[str, str]) -> str:
    return f"{key[0]}->{key[1]}"


def edge_removal(motif: Motif, ctx: GenContext) -> OperatorResult:
    moves: list[Move] = []
    blocked: list[Blocked] = []
    absent = {n.id for n in motif.nodes if n.polarity == "absent"}
    for edge in sorted(motif.edges, key=lambda e: e.key):
        target = _label(edge.key)
        detail = {"rel": edge.rel, "prov": edge.prov}
        if edge.s == PATIENT_ID and edge.t == motif.anchor:
            blocked.append(Blocked(OP, target, "protected_anchor_edge", detail))
            continue
        if is_absent_touching(motif, edge):
            blocked.append(Blocked(OP, target, "touches_absent", detail))
            continue

        removed_edges = {edge.key}
        removed_nodes: set[str] = set()
        if edge.s == PATIENT_ID:
            removed_nodes.add(edge.t)
            removed_edges |= {e.key for e in motif.edges if edge.t in (e.s, e.t)}

        remaining = [e for e in motif.edges if e.key not in removed_edges]
        adj: dict[str, set[str]] = {}
        for e in remaining:
            adj.setdefault(e.s, set()).add(e.t)
            adj.setdefault(e.t, set()).add(e.s)
        seen = {PATIENT_ID}
        queue = deque([PATIENT_ID])
        while queue:
            for nxt in adj.get(queue.popleft(), ()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        orphans = {n.id for n in motif.nodes if n.id not in seen and n.id not in removed_nodes}
        removed_nodes |= orphans
        removed_edges |= {e.key for e in motif.edges if e.s in orphans or e.t in orphans}

        dropped = sorted(({motif.anchor} | absent) & removed_nodes)
        if dropped:
            blocked.append(Blocked(OP, target, "would_drop_protected", {**detail, "dropped": dropped}))
            continue
        if not any(e.prov == "asserted" for e in motif.edges if e.key not in removed_edges):
            blocked.append(Blocked(OP, target, "no_asserted_left", detail))
            continue

        child = motif.without(removed_nodes, removed_edges)
        before = {"s": edge.s, "t": edge.t, "rel": edge.rel, "prov": edge.prov,
                  "window": edge.window.to_json() if edge.window else None, "bpn_score": edge.bpn_score}
        evidence = {"removed_nodes": sorted(removed_nodes),
                    "removed_edges": sorted(_label(k) for k in removed_edges)}
        moves.append(Move(child, ChangeRecord(OP, target, "edge", before, None, evidence)))
    return OperatorResult(moves, blocked)
