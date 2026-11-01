"""Concept lift: replace a node's code by a direct IS-A parent, bounded by floors."""
from __future__ import annotations

from semgen.model import Motif
from semgen.operators.base import (CLINICAL_TYPES, Blocked, ChangeRecord, GenContext, Move,
                                   OperatorResult)

OP = "concept_lift"


def concept_lift(motif: Motif, ctx: GenContext) -> OperatorResult:
    h, cfg = ctx.hierarchy, ctx.config
    moves: list[Move] = []
    blocked: list[Blocked] = []
    for node in sorted(motif.nodes, key=lambda n: n.id):
        if (node.polarity != "present" or node.type not in CLINICAL_TYPES
                or node.role in {"context", "patient"} or node.code is None):
            continue
        code = node.code

        def block(reason: str, **extra) -> None:
            blocked.append(Blocked(OP, node.id, reason, {"code": code, **extra}))

        if node.value is not None:
            block("carries_value")
            continue
        dependent = sorted(a for a in node.attrs if cfg.attr_is_concept_dependent(a))
        if dependent:
            block("concept_dependent_attr", attrs=dependent)
            continue
        floors = [f for f in cfg.floors if h.is_descendant_or_self(code, f)]
        if not floors:
            block("no_floor")
            continue
        if code in floors:
            block("at_floor", floors=floors)
            continue
        for p in sorted(h.parents(code)):
            if not h.is_active(p):
                block("inactive_parent", parent=p)
                continue
            escaped = [f for f in floors if not h.is_descendant_or_self(p, f)]
            if escaped:
                block("outside_floor", parent=p, escaped_floors=escaped)
                continue
            child = motif.replace_node(node.model_copy(update={"code": p, "label": h.fsn(p)}))
            evidence = {"isa": [code, p], "floors": floors, "parent_fsn": h.fsn(p),
                        "depth_before": h.depth(code), "depth_after": h.depth(p)}
            moves.append(Move(child, ChangeRecord(OP, node.id, "code", code, p, evidence)))
    return OperatorResult(moves, blocked)
