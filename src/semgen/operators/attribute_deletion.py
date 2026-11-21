"""Attribute deletion (design §7.2; replaces attribute_removal): drop one constraint, keep the element.

One move per candidate, on present non-``P`` nodes and on edges touching no absent node: a concept-independent
attribute (``about: patient``), the value, one date, one A1 observation (while at least two remain); an edge's
window, or one of its two bounds when both are set (a one-sided window's single bound is the window itself).
The edge, its ``rel`` and direction always remain. Context edges are never changed (``lattice.guard``).
The proof is ``check_order``: the child keeps a subset of the parent's constraints.

``deletion_candidates`` enumerates; ``attribute_deletion`` passes each candidate through the relevance gate
(``semgen.relevance.assess``), which reads the declared cohort definition only: graph distance to the anchor never
decides. Only ``relaxable`` candidates become moves (the assessment goes into the evidence); ``retain`` / ``unknown``
become ``relevance_retain`` / ``relevance_unknown``. A concept-dependent attribute (attribute definitions) is
``concept_dependent_attr``; declared relaxable it is a conflict, ``relevance_unknown``. Deleting a constraint changes
the pattern only: the node, every edge, absent nodes, context and provenance stay.
"""
from __future__ import annotations

from semgen.interfaces import Blocked, ChangeRecord, GenContext, Move, OperatorResult, is_absent_touching
from semgen.model import PATIENT_ID, Edge, Interval, Motif, Node, Observation
from semgen.relevance import assess

OP = "attribute_deletion"


def _record(target: str, field: str, before, after, kind: str) -> ChangeRecord:
    return ChangeRecord(OP, target, field, before, after, {}, meaning="generalized", rule_id=f"attr.delete.{kind}")


def _observation_json(o: Observation) -> dict:
    return {"value": o.value.to_json(), "dates": dict(o.dates), "source_node": o.source_node,
            "source_record": o.source_record, "label": o.label,
            "reference_range": None if o.reference_range is None else o.reference_range.model_dump(mode="json")}


def _node_moves(motif: Motif, node: Node, ctx: GenContext, moves: list[Move], blocked: list[Blocked]) -> None:
    def add(update: dict, field: str, before, kind: str) -> None:
        moves.append(Move(motif.replace_node(node.model_copy(update=update)), _record(node.id, field, before, None, kind)))

    for name in sorted(node.attrs):
        if ctx.config.attr_is_concept_dependent(name):
            field = f"attrs.{name}"
            if ctx.cohort is not None and ctx.cohort.necessity(node.id, field) == "relaxable":
                if name in ctx.config.attribute_definitions:   # an explicit about: node_concept: a real conflict
                    a = assess(node.id, field, ctx, ("the attribute definitions mark it concept-dependent (protected)",))
                else:                                          # missing metadata, not a stated requirement
                    a = {**assess(node.id, field, ctx, ("unlisted",)),
                         "reason": "declared relaxable, but the attribute is unlisted in the attribute definitions; "
                                   "the existing contract treats an unlisted attribute as concept-dependent (protected)"}
                blocked.append(Blocked(OP, node.id, "relevance_unknown", a))
            else:
                blocked.append(Blocked(OP, node.id, "concept_dependent_attr", {"attr": name}))
            continue
        add({"attrs": {k: v for k, v in node.attrs.items() if k != name}}, f"attrs.{name}",
            node.attrs[name].to_json(), "attr")
    if node.value is not None:
        add({"value": None}, "value", node.value.to_json(), "value")
    for name in sorted(node.dates):
        add({"dates": {k: v for k, v in node.dates.items() if k != name}}, f"dates.{name}", node.dates[name], "date")
    if len(node.observations) > 2:
        for i, o in enumerate(node.observations):
            rest = node.observations[:i] + node.observations[i + 1:]
            add({"observations": rest}, f"observations.{o.source_node}", _observation_json(o), "observation")


def _edge_moves(motif: Motif, edge: Edge, moves: list[Move]) -> None:
    target = f"{edge.s}->{edge.t}"

    def add(update: dict, field: str, before, after, kind: str) -> None:
        moves.append(Move(motif.replace_edge(edge.model_copy(update=update)),
                          _record(target, field, before, after, kind)))

    w = edge.window
    if w is not None:
        add({"window": None}, "window", w.to_json(), None, "window")
        if w.lo is not None and w.hi is not None:
            lo_free = Interval(lo=None, hi=w.hi, hi_closed=w.hi_closed, unit=w.unit)
            hi_free = Interval(lo=w.lo, lo_closed=w.lo_closed, hi=None, unit=w.unit)
            add({"window": lo_free}, "window.lo", w.to_json(), lo_free.to_json(), "window_lo")
            add({"window": hi_free}, "window.hi", w.to_json(), hi_free.to_json(), "window_hi")
    for name in sorted(edge.dates):
        add({"dates": {k: v for k, v in edge.dates.items() if k != name}}, f"dates.{name}", edge.dates[name], None,
            "date")


def deletion_candidates(motif: Motif, ctx: GenContext) -> OperatorResult:
    """Every structurally legal deletion, before the relevance gate."""
    moves: list[Move] = []
    blocked: list[Blocked] = []
    for node in sorted(motif.nodes, key=lambda n: n.id):
        if node.polarity != "present" or node.id == PATIENT_ID or node.role == "patient":
            continue
        _node_moves(motif, node, ctx, moves, blocked)
    for edge in sorted(motif.edges, key=lambda e: e.key):
        if edge.prov == "context" or is_absent_touching(motif, edge):
            continue
        _edge_moves(motif, edge, moves)
    return OperatorResult(moves, blocked)


def attribute_deletion(motif: Motif, ctx: GenContext) -> OperatorResult:
    cand = deletion_candidates(motif, ctx)
    moves: list[Move] = []
    blocked = list(cand.blocked)
    for mv in cand.moves:
        ch = mv.change
        a = assess(ch.target, ch.field, ctx)
        if a["decision"] == "relaxable":
            moves.append(Move(mv.child, ChangeRecord(ch.op, ch.target, ch.field, ch.before, ch.after,
                                                     {**ch.evidence, "relevance": a}, meaning=ch.meaning,
                                                     rule_id=ch.rule_id, source=ch.source)))
        else:
            blocked.append(Blocked(OP, ch.target, f"relevance_{a['decision']}", a))
    return OperatorResult(moves, blocked)
