"""Attribute aggregation (design §7.3): A1 repeated observations and A3 SNOMED CT semantic grouping.

Both are ``kept`` moves: the match set is provably unchanged (``order.check_a1_merge`` / ``check_group_merge``).

A1 (D8): merge repeated observations of one measurement into one node.

A group is two or more present nodes of one motif with equal type, role, code and value unit, each with a point
value, no attrs, and no edge but an identical ``P -> node`` edge. Measurement identity must be established:
every node has ``test`` with all four fields (system, code, method, specimen) set and equal across the group (null
means unknown, never "the same"). The unit must be a valid UCUM expression of the pinned essence (``ctx.ucum``);
without an essence the unit cannot be validated and the merge blocks. The merged node keeps the lowest id,
``value=None``, no node dates, and ``observations`` = every original in id order with its value (and unit), dates,
reference range, label and source node id; the other nodes and their ``P`` edges go. Each observation's reference
range is authoritative; the node keeps a reference range only when every original shares it (else none). No mean, latest value or other
summary is computed: a patient must hold one distinct fact per observation, so the match set is unchanged.

A1 blocked reasons: ``observation_has_attrs``, ``observation_not_attached``, ``observation_has_other_edges``,
``observation_edges_differ``, ``measurement_identity_unknown``, ``measurement_identity_differs``,
``anchor_would_be_removed``, ``unit_validation_unavailable``, ``unit_invalid``.

A3 groups two or more nodes into one grouped node that keeps every original node verbatim in ``members``
(``code=None``); ``grouping`` names the members' lowest common SNOMED CT ancestor as an organisational summary only,
never used for matching (a patient matches iff every member matches its own fact). Candidates: present, non-``P``,
non-anchor, non-context nodes without observations or members, attached only by a ``P -> node`` edge, of one type
and role. The ancestor is read from the loaded release's IS-A hierarchy (nothing is listed by hand); it must be the
unique minimal common ancestor and be reachable from every member's concept by single steps that concept lift
(``ctx.floors.check_lift``) accepts. The lattice guard re-verifies the summary with ``semgen.lift_verify``.

A3 blocked reasons: ``multiple_minimal_ancestors``, ``group_types_differ``, ``group_edges_differ``, and for a step
to the ancestor that concept lift refuses (detail ``member``, ``step``, ``rule``), classified by the lift's own
rejecting rule: ``lcs_outside_floor`` (the ``hierarchy`` rule or a ``TOP_REASONS`` stop: root / top-level boundary),
``ontology_evidence_unknown`` (an ``UNKNOWN_REASONS`` outcome, an inactive concept, or no route; also a candidate
concept not active in the release, detail ``code``), ``lcs_semantic_rejection`` (any other rejecting rule, e.g.
semantic tag, MRCM domain, defining relationships).
"""
from __future__ import annotations

from collections import deque

from semgen.interfaces import TOP_REASONS, Blocked, ChangeRecord, GenContext, Move, OperatorResult
from semgen.lift import REJECT_REASONS, UNKNOWN_REASONS
from semgen.model import PATIENT_ID, Grouping, Motif, Node, Observation

OP = "attribute_aggregation"
RULE_ID = "attr.aggregate.repeated_observation"
ONTOLOGY_RULE = "attr.aggregate.ontology"
IDENTITY_FIELDS = ("system", "code", "method", "specimen")


def _is_point(n: Node) -> bool:
    return n.value is not None and n.value.lo is not None and n.value.lo == n.value.hi


def _edge_shape(e) -> tuple:
    return (e.rel, e.prov, e.window, tuple(sorted(e.dates.items())), e.bpn_score)


def _group_blocked(motif: Motif, group: list[Node], ctx: GenContext) -> Blocked | None:
    """Why ``group`` (sorted by id, two or more nodes) cannot be merged, or None."""
    for n in group:
        if n.attrs:
            return Blocked(OP, n.id, "observation_has_attrs", {"node": n.id, "attrs": sorted(n.attrs)})
    p_edges = []
    for n in group:
        touching = sorted((e for e in motif.edges if n.id in (e.s, e.t)), key=lambda e: e.key)
        other = [f"{e.s}->{e.t}" for e in touching if (e.s, e.t) != (PATIENT_ID, n.id)]
        if other:
            return Blocked(OP, n.id, "observation_has_other_edges", {"node": n.id, "edges": other})
        if not touching:
            return Blocked(OP, n.id, "observation_not_attached", {"node": n.id})
        p_edges.append(touching[0])
    # Equal in every field, so the one kept P edge constrains each observation's fact exactly as before.
    if len({_edge_shape(e) for e in p_edges}) > 1:
        return Blocked(OP, group[0].id, "observation_edges_differ", {"nodes": [n.id for n in group]})
    for n in group:
        if n.test is None:
            return Blocked(OP, n.id, "measurement_identity_unknown", {"node": n.id, "field": "test"})
        for f in IDENTITY_FIELDS:
            if getattr(n.test, f) is None:
                return Blocked(OP, n.id, "measurement_identity_unknown", {"node": n.id, "field": f})
    for f in IDENTITY_FIELDS:
        values = sorted({getattr(n.test, f) for n in group})
        if len(values) > 1:
            return Blocked(OP, group[0].id, "measurement_identity_differs",
                           {"nodes": [n.id for n in group], "field": f, "values": values})
    ids = {n.id for n in group}
    if motif.anchor in ids and motif.anchor != group[0].id:
        return Blocked(OP, group[0].id, "anchor_would_be_removed", {"anchor": motif.anchor, "kept": group[0].id})
    unit = group[0].value.unit
    if ctx.ucum is None:
        return Blocked(OP, group[0].id, "unit_validation_unavailable",
                       {"nodes": sorted(ids), "unit": unit, "missing": "no UCUM essence loaded"})
    if not ctx.ucum.is_valid(unit):
        return Blocked(OP, group[0].id, "unit_invalid", {"nodes": sorted(ids), **ctx.ucum.check(unit)})
    return None


def _a1_evidence(n: Node, ctx: GenContext) -> dict:
    table = ctx.code_tables.get(n.test.system)
    ci = ({"system": n.test.system, "status": "terminology_unavailable"} if table is None
          else {"system": n.test.system, **table.lookup(n.test.code)})
    return {"unit_validation": ctx.ucum.check(n.value.unit), "canonical_identity": ci}


def _a1(motif: Motif, ctx: GenContext) -> OperatorResult:
    groups: dict[tuple, list[Node]] = {}
    for node in sorted(motif.nodes, key=lambda n: n.id):
        if node.polarity != "present" or node.id == PATIENT_ID or node.role == "patient" or not _is_point(node):
            continue
        key = (node.type, node.role, node.code is None, node.code or "", node.value.unit)
        groups.setdefault(key, []).append(node)
    moves: list[Move] = []
    blocked: list[Blocked] = []
    for key in sorted(groups):
        group = groups[key]
        if len(group) < 2:
            continue
        if (b := _group_blocked(motif, group, ctx)) is not None:
            blocked.append(b)
            continue
        keep = group[0]
        obs = tuple(Observation(value=n.value, dates=n.dates, source_node=n.id, label=n.label,
                                reference_range=n.reference_range) for n in group)
        ranges = {n.reference_range for n in group}
        merged = keep.model_copy(update={"value": None, "dates": {}, "observations": obs,
                                         "reference_range": keep.reference_range if len(ranges) == 1 else None})
        child = motif.without({n.id for n in group[1:]}, set()).replace_node(merged)
        t = keep.test
        evidence = {"merged": [n.id for n in group], "test": {f: getattr(t, f) for f in IDENTITY_FIELDS},
                    **_a1_evidence(keep, ctx)}
        moves.append(Move(child, ChangeRecord(OP, keep.id, "observations", None, [o.source_node for o in obs],
                                              evidence, meaning="kept", rule_id=RULE_ID)))
    return OperatorResult(moves, blocked)


# --- A3 ------------------------------------------------------------------------------------------------


def _p_edge(motif: Motif, n: Node):
    """The node's only edge if it is ``P -> node``, else None (the node is not a grouping candidate)."""
    touching = [e for e in motif.edges if n.id in (e.s, e.t)]
    return touching[0] if len(touching) == 1 and (touching[0].s, touching[0].t) == (PATIENT_ID, n.id) else None


def _candidates(motif: Motif) -> list[Node]:
    return [n for n in sorted(motif.nodes, key=lambda n: n.id)
            if n.polarity == "present" and n.id not in (PATIENT_ID, motif.anchor)
            and n.role not in ("patient", "anchor", "context") and not n.observations and not n.members
            and n.code is not None and _p_edge(motif, n) is not None]


def lift_path(code: str, target: str, ctx: GenContext, role: str | None = None,
              node_id: str | None = None) -> list[str] | tuple[str, str, str, str | None]:
    """Shortest path ``code -> ... -> target`` of single steps concept lift accepts, or the first refused step
    towards ``target`` as ``(child, parent, reason, rule)``; ``rule`` names the lift rule that decided it (None when
    the lift record names none)."""
    h = ctx.hierarchy
    prev: dict[str, str | None] = {code: None}
    queue = deque([code])
    refused: list[tuple[str, str, str, str | None]] = []
    while queue:
        c = queue.popleft()
        if c == target:
            path = [c]
            while (p := prev[path[-1]]) is not None:
                path.append(p)
            return path[::-1]
        for p in sorted(h.parents(c)):
            if p in prev or target not in h.ancestors_or_self(p):
                continue
            rule: str | None = None
            if not h.is_active(p):
                reason: str | None = "inactive_parent"
            else:
                d = ctx.floors.check_lift(c, p, role=role, node_id=node_id, cohort=ctx.cohort)
                reason = None if d.ok else (d.reason or "outside_floor")
                if reason is not None:
                    rules = (d.detail.get("transition") or {}).get("rules") or []
                    rule = next((r.get("rule") for r in rules if r.get("reason") == reason), None)
            if reason is None:
                prev[p] = c
                queue.append(p)
            else:
                refused.append((c, p, reason, rule))
    return refused[0] if refused else (code, target, "not_an_ancestor", None)


def _classify(reason: str, rule: str | None) -> str:
    """Why an ancestor is out of reach, from the lift's own outcome: missing evidence, the hierarchy boundary, or a
    semantic (ontology-structural) rejection. Anything unrecognised is not evidence of either: unknown."""
    if reason in UNKNOWN_REASONS or reason in ("inactive_concept", "inactive_parent", "not_an_ancestor"):
        return "ontology_evidence_unknown"
    if reason in TOP_REASONS or rule == "hierarchy":
        return "lcs_outside_floor"
    if reason in REJECT_REASONS:
        return "lcs_semantic_rejection"
    return "ontology_evidence_unknown"


def _refused(target: str, step: tuple[str, str, str, str | None], member: str) -> Blocked:
    c, p, reason, rule = step
    return Blocked(OP, target, _classify(reason, rule), {"member": member, "step": [c, p, reason], "rule": rule})


def _group_move(motif: Motif, group: list[Node], grouping: Grouping, rule_id: str, evidence: dict,
                source: dict) -> Move | Blocked:
    ids = [n.id for n in group]
    target = "+".join(ids)
    if len({(n.type, n.role) for n in group}) > 1:
        return Blocked(OP, target, "group_types_differ", {"nodes": ids})
    if len({_edge_shape(_p_edge(motif, n)) for n in group}) > 1:
        return Blocked(OP, target, "group_edges_differ", {"nodes": ids})
    keep = group[0]
    merged = Node(id=keep.id, type=keep.type, role=keep.role, label=grouping.label, members=tuple(group),
                  grouping=grouping)
    child = motif.without(set(ids[1:]), set()).replace_node(merged)
    return Move(child, ChangeRecord(OP, keep.id, "members", None, ids, {"members": ids, **evidence},
                                    meaning="kept", rule_id=rule_id, source=source))


def _a3(motif: Motif, ctx: GenContext) -> OperatorResult:
    h = ctx.hierarchy
    blocked: list[Blocked] = []
    all_cands = _candidates(motif)
    kinds = [(n.type, n.role) for n in all_cands]
    cands = []
    for n in all_cands:
        if h.is_active(n.code):
            cands.append(n)
        elif kinds.count((n.type, n.role)) > 1:   # it could have been grouped: its concept is not evidence
            blocked.append(Blocked(OP, n.id, "ontology_evidence_unknown",
                                   {"code": n.code, "missing": "concept not active in the loaded release"}))
    categories: dict[str, list[Node]] = {}
    for i, a in enumerate(cands):
        for b in cands[i + 1:]:
            if a.code == b.code or (a.type, a.role) != (b.type, b.role):
                continue
            common = set(h.ancestors_or_self(a.code)) & set(h.ancestors_or_self(b.code))
            minimal = sorted(c for c in common if not any(c in h.ancestors(x) for x in common if x != c))
            if len(minimal) > 1:
                blocked.append(Blocked(OP, f"{a.id}+{b.id}", "multiple_minimal_ancestors",
                                       {"codes": [a.code, b.code], "ancestors": minimal}))
                continue
            if not minimal:
                continue   # no common ancestor in the release: nothing to group under
            c = minimal[0]
            refused = [(n, r) for n in (a, b) if not isinstance(r := lift_path(n.code, c, ctx, n.role, n.id), list)]
            if refused:
                blocked.append(_refused(f"{a.id}+{b.id}", refused[0][1], refused[0][0].id))
                continue
            if c not in categories:
                categories[c] = [n for n in cands if (n.type, n.role) == (a.type, a.role)
                                 and isinstance(lift_path(n.code, c, ctx, n.role, n.id), list)]
    by_members: dict[tuple, list[str]] = {}
    for c, group in categories.items():
        if len({n.code for n in group}) >= 2:
            by_members.setdefault(tuple(n.id for n in group), []).append(c)
    moves: list[Move] = []
    for ids in sorted(by_members):
        cs = by_members[ids]
        most_specific = [c for c in cs if not any(o != c and o in h.descendants_or_self(c) for o in cs)]
        if len(most_specific) != 1:
            blocked.append(Blocked(OP, "+".join(ids), "multiple_minimal_ancestors", {"ancestors": sorted(cs)}))
            continue
        c = most_specific[0]
        group = [motif.node(i) for i in ids]
        g = Grouping(kind="ontology", system="SNOMED CT", code=c, label=h.fsn(c),
                     version=f"{h.edition}/{h.release}", source="active IS-A hierarchy")
        r = _group_move(motif, group, g, ONTOLOGY_RULE,
                        {"category": c, "paths": {n.id: lift_path(n.code, c, ctx, n.role, n.id) for n in group}},
                        {"kind": "ontology", "edition": h.edition, "release": h.release})
        (moves if isinstance(r, Move) else blocked).append(r)
    return OperatorResult(moves, blocked)


# Public names of the two parts (tests inspect them separately).
repeated_observations, ontology_groups = _a1, _a3


def attribute_aggregation(motif: Motif, ctx: GenContext) -> OperatorResult:
    moves: list[Move] = []
    blocked: list[Blocked] = []
    for part in (_a1, _a3):
        r = part(motif, ctx)
        moves += r.moves
        blocked += r.blocked
    return OperatorResult(moves, blocked)
