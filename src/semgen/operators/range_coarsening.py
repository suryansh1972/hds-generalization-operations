"""Range coarsening: widen a numeric constraint to the next ladder rung."""
from __future__ import annotations

from semgen.model import PATIENT_ID, Motif
from semgen.operators.base import Blocked, ChangeRecord, GenContext, Move, OperatorResult

OP = "range_coarsening"


def range_coarsening(motif: Motif, ctx: GenContext) -> OperatorResult:
    cfg = ctx.config
    moves: list[Move] = []
    blocked: list[Blocked] = []
    for node in sorted(motif.nodes, key=lambda n: n.id):
        if node.polarity != "present" or node.id == PATIENT_ID or node.role == "patient":
            continue
        items = [(f"attrs.{name}", node.attrs[name], cfg.attr_ladder_for(name), {"attr": name})
                 for name in sorted(node.attrs)]
        if node.value is not None:
            ladder = cfg.value_ladder_for(node.code) if node.code is not None else None
            items.append(("value", node.value, ladder, {"code": node.code}))
        for field, old, ladder, who in items:
            if ladder is None:
                blocked.append(Blocked(OP, node.id, "no_ladder", {"field": field, **who}))
                continue
            if old.unit != ladder.unit:
                blocked.append(Blocked(OP, node.id, "unit_mismatch", {
                    "field": field, "unit": old.unit, "ladder_unit": ladder.unit}))
                continue
            new = ladder.next_rung(old)
            if new is None:
                continue
            if field == "value":
                child_node = node.model_copy(update={"value": new})
            else:
                child_node = node.model_copy(update={"attrs": {**node.attrs, field[6:]: new}})
            moves.append(Move(motif.replace_node(child_node), ChangeRecord(
                OP, node.id, field, old.to_json(), new.to_json(), {"ladder": ladder.name})))
    return OperatorResult(moves, blocked)
