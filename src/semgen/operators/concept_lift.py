"""Concept lift: replace a node's code by a direct IS-A parent, bounded by the selected floor policy.

Reads upward only (parents), never downward. A present value or concept-dependent attribute blocks the lift;
the policy (snomed_boundary or phecodex) then accepts or blocks each active parent. Repeated lifts (the climb)
are driven by the lattice, one step at a time.
"""
from __future__ import annotations

from semgen.model import Motif, Node
from semgen.operators.base import (CLINICAL_TYPES, Blocked, ChangeRecord, GenContext, Move,
                                   OperatorResult)

OP = "concept_lift"


def is_liftable(node: Node) -> bool:
    return (node.polarity == "present" and node.type in CLINICAL_TYPES
            and node.role not in {"context", "patient"} and node.code is not None)


def concept_lift(motif: Motif, ctx: GenContext) -> OperatorResult:
    h, cfg = ctx.hierarchy, ctx.config
    moves: list[Move] = []
    blocked: list[Blocked] = []
    for node in sorted(motif.nodes, key=lambda n: n.id):
        if not is_liftable(node):
            continue
        code = node.code

        def block(reason: str, /, **extra) -> None:
            blocked.append(Blocked(OP, node.id, reason, {"code": code, **extra}))

        if not h.is_active(code):
            block("unknown_concept")
            continue
        if node.value is not None:
            block("carries_value")
            continue
        dependent = sorted(a for a in node.attrs if cfg.attr_is_concept_dependent(a))
        if dependent:
            block("concept_dependent_attr", attrs=dependent)
            continue
        if not h.parents(code):
            block("no_parent")
            continue
        parents = sorted(h.parents(code))
        for p in parents:
            if not h.is_active(p):   # before the floor check: the policy approves an empty parent vacuously
                block("inactive_parent", parent=p)
        for p in parents:
            if not h.is_active(p):
                continue
            d = ctx.floors.check_lift(code, p)
            if d.reason == "unmapped":
                block("unmapped")
                break
            if not d.ok:
                block(d.reason or "outside_floor", **d.detail)
                continue
            child = motif.replace_node(node.model_copy(update={"code": p, "label": h.fsn(p)}))
            evidence = {"isa": [code, p], **d.detail, "parent_fsn": h.fsn(p),
                        "depth_before": h.depth(code), "depth_after": h.depth(p)}
            moves.append(Move(child, ChangeRecord(OP, node.id, "code", code, p, evidence)))
    return OperatorResult(moves, blocked)
