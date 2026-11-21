"""Concept lift: replace a node's code by a direct active inferred IS-A parent that ``semgen.lift`` accepts.

Every active parent of a polyhierarchical concept is evaluated and becomes its own candidate; rejected and unknown
parents are reported as blocked with the transition record. A present value or concept-dependent attribute blocks
the lift (motif rule, not ontology). Repeated lifts (the climb) are driven by the lattice, one step at a time; the
lattice guard re-checks each applied step with the independent verifier (``semgen.lift_verify``).
"""
from __future__ import annotations

from semgen.interfaces import Blocked, ChangeRecord, GenContext, Move, OperatorResult
from semgen.model import Motif, Node

OP = "concept_lift"
STRUCTURAL_ROLES = frozenset({"context", "patient"})   # motif schema: KG enrichment nodes and P are never lifted


def is_liftable(node: Node, ctx: GenContext | None = None) -> bool:
    """A present, coded, non-structural node; whether its code can lift is decided from the release."""
    return node.polarity == "present" and node.role not in STRUCTURAL_ROLES and node.code is not None


def concept_lift(motif: Motif, ctx: GenContext) -> OperatorResult:
    h, cfg = ctx.hierarchy, ctx.config
    moves: list[Move] = []
    blocked: list[Blocked] = []
    for node in sorted(motif.nodes, key=lambda n: n.id):
        if not is_liftable(node, ctx):
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
        for p in sorted(h.parents(code)):
            d = ctx.floors.check_lift(code, p, role=node.role, node_id=node.id, cohort=ctx.cohort)
            if not d.ok:
                block(d.reason or "unknown", **d.detail)
                continue
            child = motif.replace_node(node.model_copy(update={"code": p, "label": h.fsn(p)}))
            evidence = {"isa": [code, p], "parent_fsn": h.fsn(p), "transition": d.detail.get("transition"),
                        "fingerprint": d.detail.get("fingerprint"),
                        "depth_before": h.depth(code), "depth_after": h.depth(p)}
            moves.append(Move(child, ChangeRecord(OP, node.id, "code", code, p, evidence)))
    return OperatorResult(moves, blocked)
