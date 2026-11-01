"""Attribute removal: drop one optional attribute or the value of a present node."""
from __future__ import annotations

from semgen.model import PATIENT_ID, Motif
from semgen.operators.base import ChangeRecord, GenContext, Move, OperatorResult

OP = "attribute_removal"


def attribute_removal(motif: Motif, ctx: GenContext) -> OperatorResult:
    moves: list[Move] = []
    for node in sorted(motif.nodes, key=lambda n: n.id):
        if node.polarity != "present" or node.id == PATIENT_ID or node.role == "patient":
            continue
        for name in sorted(node.attrs):
            rest = {k: v for k, v in node.attrs.items() if k != name}
            child = motif.replace_node(node.model_copy(update={"attrs": rest}))
            moves.append(Move(child, ChangeRecord(
                OP, node.id, f"attrs.{name}", node.attrs[name].to_json(), None, {})))
        if node.value is not None:
            child = motif.replace_node(node.model_copy(update={"value": None}))
            moves.append(Move(child, ChangeRecord(
                OP, node.id, "value", node.value.to_json(), None, {})))
    return OperatorResult(moves, [])
