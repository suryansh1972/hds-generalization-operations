"""Temporal coarsening: widen an edge's time window to the next ladder rung."""
from __future__ import annotations

from semgen.model import Motif
from semgen.operators.base import Blocked, ChangeRecord, GenContext, Move, OperatorResult, is_absent_touching

OP = "temporal_coarsening"


def temporal_coarsening(motif: Motif, ctx: GenContext) -> OperatorResult:
    ladder = ctx.config.time_ladder
    moves: list[Move] = []
    blocked: list[Blocked] = []
    for edge in sorted(motif.edges, key=lambda e: e.key):
        if edge.window is None or edge.prov == "context" or is_absent_touching(motif, edge):
            continue
        old = edge.window
        target = f"{edge.s}->{edge.t}"
        if old.unit != ladder.unit:
            blocked.append(Blocked(OP, target, "unit_mismatch", {"unit": old.unit, "ladder_unit": ladder.unit}))
            continue
        new = ladder.next_rung(old)
        if new is None:
            continue
        child = motif.replace_edge(edge.model_copy(update={"window": new}))
        moves.append(Move(child, ChangeRecord(
            OP, target, "window", old.to_json(), new.to_json(), {"ladder": ladder.name})))
    return OperatorResult(moves, blocked)
