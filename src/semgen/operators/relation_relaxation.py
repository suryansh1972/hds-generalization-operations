"""Relation relaxation: move an asserted edge's relation one step up the relation hierarchy."""
from __future__ import annotations

from semgen.model import Motif
from semgen.operators.base import ChangeRecord, GenContext, Move, OperatorResult, is_absent_touching

OP = "relation_relaxation"


def relation_relaxation(motif: Motif, ctx: GenContext) -> OperatorResult:
    moves: list[Move] = []
    for edge in sorted(motif.edges, key=lambda e: e.key):
        if edge.prov != "asserted" or is_absent_touching(motif, edge):
            continue
        parent = ctx.config.relations.parent(edge.rel)
        if parent is None:
            continue
        child = motif.replace_edge(edge.model_copy(update={"rel": parent}))
        moves.append(Move(child, ChangeRecord(
            OP, f"{edge.s}->{edge.t}", "rel", edge.rel, parent, {"relation_parent": [edge.rel, parent]})))
    return OperatorResult(moves, [])
