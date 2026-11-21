"""Normative range bucketing (design §7.1): replace a point value by the bucket holding it:
``below_reference_interval`` / ``within_reference_interval`` / ``above_reference_interval`` (rev 4 names).

The reference interval comes from ``semgen.refrange.select_range`` (the result's own range, else Mayo); missing,
ambiguous or conflicting evidence is a Blocked row. The bucket contains the value, so the proof is the existing
value-containment rule of ``check_order`` (units are equal by construction, D7).
"""
from __future__ import annotations

from semgen.interfaces import Blocked, ChangeRecord, GenContext, Move, OperatorResult
from semgen.model import PATIENT_ID, Motif, Node
from semgen.refrange import OP, buckets, select_range

RULE_ID = "bucket.reference_interval"


def _has_point_value(n: Node) -> bool:
    v = n.value
    return v is not None and v.lo is not None and v.lo == v.hi


def normative_bucketing(motif: Motif, ctx: GenContext) -> OperatorResult:
    moves: list[Move] = []
    blocked: list[Blocked] = []
    for node in sorted(motif.nodes, key=lambda n: n.id):
        if node.polarity != "present" or node.id == PATIENT_ID or node.role == "patient" or not _has_point_value(node):
            continue
        sel = select_range(node, ctx.subject, ctx.refranges)
        if isinstance(sel, Blocked):
            blocked.append(sel)
            continue
        name, bucket = next((n, b) for n, b in buckets(sel.interval) if b.contains(node.value))
        child = motif.replace_node(node.model_copy(update={"value": bucket}))
        evidence = {"bucket": name, "interval_kind": "reference_interval", "reference_interval": sel.interval.to_json(), "selection": list(sel.selection),
                    "unit_conversion": None}
        moves.append(Move(child, ChangeRecord(OP, node.id, "value", node.value.to_json(), bucket.to_json(), evidence,
                                              meaning="generalized", rule_id=RULE_ID, source=sel.source)))
    return OperatorResult(moves, blocked)
