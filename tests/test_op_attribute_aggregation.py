"""Attribute aggregation A1 (design §7.3, D8): repeated observations of one test merge into one node, `kept`.

All motifs, test identities, patients and the UCUM essence here are SYNTHETIC.
"""
import dataclasses

import pytest

from semgen.lattice import Budget, enumerate_lattice
from semgen.model import Edge, Interval, Motif, Node, Observation, ReferenceRange, TestIdentity

# These are A1 tests; attribute_aggregation also runs A3 (tests/test_op_attribute_groups.py), so A1 is tested on its
# own part.
from semgen.operators.attribute_aggregation import repeated_observations as attribute_aggregation
from semgen.operators.base import Blocked
from semgen.order import check_order
from tests.conftest import DISEASE, DM, GFR, LVEF
from tests.support.matcher import matches
from tests.support.ucum import test_ucum

U = "mL/min/{1.73_m2}"   # valid UCUM (the bare "1.73m2" spelling is not)


@pytest.fixture
def ctx(ctx):
    return dataclasses.replace(ctx, ucum=test_ucum("mL", "min", "%"))
GT = TestIdentity(system="urn:synthetic:lab", code="GFR-S", method="calc", specimen="Serum")


def labs(*vals, dates=True, test=GT, mid="LAB") -> Motif:
    nodes = [Node(id="P", type="Patient", role="patient"), Node(id="a", type="Disorder", role="anchor", code=DISEASE)]
    edges = [Edge(s="P", t="a", rel="has_condition", prov="asserted")]
    for i, v in enumerate(vals, start=1):
        nodes.append(Node(id=f"g{i}", type="Observable", role="outcome", code=GFR, value=Interval.point(v, U),
                          dates={"taken": f"2026-0{i}-01"} if dates else {}, test=test))
        edges.append(Edge(s="P", t=f"g{i}", rel="has_measurement", prov="asserted"))
    return Motif(motif_id=mid, anchor="a", nodes=tuple(nodes), edges=tuple(edges))


def upd(m: Motif, nid: str, **kw) -> Motif:
    return m.replace_node(m.node(nid).model_copy(update=kw))


def only_move(m, ctx):
    res = attribute_aggregation(m, ctx)
    assert res.blocked == [], res.blocked
    (mv,) = res.moves
    return mv


def only_block(m, ctx) -> Blocked:
    res = attribute_aggregation(m, ctx)
    assert res.moves == []
    (b,) = res.blocked
    assert b.op == "attribute_aggregation"
    return b


def test_merges_repeated_observations_preserving_all(ctx):
    parent = labs(42, 45, 40)
    mv = only_move(parent, ctx)
    g = mv.child.node("g1")
    assert mv.child.node_ids == {"P", "a", "g1"} and {e.key for e in mv.child.edges} == {("P", "a"), ("P", "g1")}
    assert g.value is None and dict(g.dates) == {} and g.test == GT and g.code == GFR
    assert [(o.source_node, o.value, dict(o.dates)) for o in g.observations] == [
        ("g1", Interval.point(42, U), {"taken": "2026-01-01"}),
        ("g2", Interval.point(45, U), {"taken": "2026-02-01"}),
        ("g3", Interval.point(40, U), {"taken": "2026-03-01"})]
    ch = mv.change
    assert (ch.op, ch.target, ch.field, ch.meaning, ch.rule_id) == (
        "attribute_aggregation", "g1", "observations", "kept", "attr.aggregate.repeated_observation")
    assert ch.evidence == {"merged": ["g1", "g2", "g3"],
                           "test": {"system": GT.system, "code": GT.code, "method": GT.method,
                                    "specimen": GT.specimen},
                           "unit_validation": {"unit": U, "status": "valid", "version": "test", "sha256": "0" * 64},
                           "canonical_identity": {"system": GT.system, "status": "terminology_unavailable"}}
    assert ch.before is None and ch.after == [o.source_node for o in g.observations]   # no mean/latest/min/max
    assert check_order(parent, mv.child, ctx).ok


@pytest.mark.parametrize("field", ["method", "specimen"])   # system and code are required by TestIdentity
def test_null_identity_field_blocks(ctx, field):
    m = upd(labs(42, 45), "g2", test=GT.model_copy(update={field: None}))
    b = only_block(m, ctx)
    assert (b.target, b.reason, b.detail) == ("g2", "measurement_identity_unknown", {"node": "g2", "field": field})


def test_differing_identity_blocks(ctx):
    m = upd(labs(42, 45, 40), "g3", test=GT.model_copy(update={"specimen": "Plasma"}))
    b = only_block(m, ctx)
    assert (b.target, b.reason) == ("g1", "measurement_identity_differs")
    assert b.detail == {"nodes": ["g1", "g2", "g3"], "field": "specimen", "values": ["Plasma", "Serum"]}


def test_same_code_and_unit_without_test_blocks(ctx):
    b = only_block(labs(42, 45, test=None), ctx)
    assert (b.target, b.reason, b.detail) == ("g1", "measurement_identity_unknown", {"node": "g1", "field": "test"})


def test_other_edge_blocks(ctx):
    m = labs(42, 45)
    m = m.model_copy(update={"nodes": m.nodes + (Node(id="d", type="Substance", role="exposure", code="X"),),
                             "edges": m.edges + (Edge(s="P", t="d", rel="administered_drug", prov="asserted"),
                                                 Edge(s="d", t="g2", rel="followed_by", prov="asserted"))})
    b = only_block(m, ctx)
    assert (b.target, b.reason, b.detail) == ("g2", "observation_has_other_edges", {"node": "g2", "edges": ["d->g2"]})


def test_group_conditions(ctx):
    assert attribute_aggregation(labs(42), ctx).moves == []                         # one node: nothing to group
    b = only_block(upd(labs(42, 45), "g2", attrs={"age_at_dx": Interval.point(3, "a")}), ctx)
    assert (b.target, b.reason) == ("g2", "observation_has_attrs")
    m = labs(42, 45)
    m = m.replace_edge(m.edge("P", "g2").model_copy(update={"rel": "has_lab"}))
    assert only_block(m, ctx).reason == "observation_edges_differ"
    # Different code or unit: separate groups of one, nothing to merge.
    assert attribute_aggregation(upd(labs(42, 45), "g2", code=LVEF), ctx).moves == []
    assert attribute_aggregation(upd(labs(42, 45), "g2", value=Interval.point(45, "%")), ctx).moves == []
    # A banded (non-point) value is not an observation to merge.
    assert attribute_aggregation(upd(labs(42, 45), "g2", value=Interval.closed(40, 50, U)), ctx).moves == []


def test_anchor_never_removed(ctx):
    m = labs(42, 45).model_copy(update={"anchor": "g2"})     # merging keeps g1, so the anchor g2 would go
    b = only_block(m, ctx)
    assert (b.target, b.reason, b.detail) == ("g1", "anchor_would_be_removed", {"anchor": "g2", "kept": "g1"})
    assert len(attribute_aggregation(labs(42, 45).model_copy(update={"anchor": "g1"}), ctx).moves) == 1


def test_roles_group_separately(ctx):
    assert attribute_aggregation(upd(labs(42, 45), "g2", role="modifier"), ctx).moves == []


def _patient(*facts, anchor=DM) -> Motif:
    """facts: (value, date or None) per GFR fact."""
    nodes = [Node(id="P", type="Patient", role="patient"), Node(id="x", type="Disorder", role="anchor", code=anchor)]
    edges = [Edge(s="P", t="x", rel="has_condition", prov="asserted")]
    for i, (v, d) in enumerate(facts):
        nodes.append(Node(id=f"f{i}", type="Observable", role="outcome", code=GFR, value=Interval.point(v, U),
                          dates={"taken": d} if d else {}))
        edges.append(Edge(s="P", t=f"f{i}", rel="has_measurement", prov="asserted"))
    return Motif(motif_id="PAT", anchor="x", nodes=tuple(nodes), edges=tuple(edges))


def test_meaning_kept_and_match_set_equal(ctx):
    parent = labs(42, 45, 40)
    child = only_move(parent, ctx).child
    pats = {"exact": _patient((42, "2026-01-01"), (45, "2026-02-01"), (40, "2026-03-01")),
            "extra": _patient((42, "2026-01-01"), (45, "2026-02-01"), (40, "2026-03-01"), (90, None)),
            "one_missing": _patient((42, "2026-01-01"), (45, "2026-02-01")),
            "wrong_date": _patient((42, "2026-01-01"), (45, "2026-02-02"), (40, "2026-03-01")),
            "wrong_value": _patient((42, "2026-01-01"), (46, "2026-02-01"), (40, "2026-03-01")),
            "anchor_not_disease": _patient((42, "2026-01-01"), (45, "2026-02-01"), (40, "2026-03-01"),
                                        anchor=GFR)}
    h = ctx.hierarchy
    got = {k: (matches(parent, p, h), matches(child, p, h)) for k, p in pats.items()}
    assert {k for k, (a, _) in got.items() if a} == {"exact", "extra"}
    assert all(a == b for a, b in got.values()), got


def test_merged_node_needs_distinct_fact_per_observation(ctx):
    parent = labs(42, 42, 42, dates=False)
    child = only_move(parent, ctx).child
    assert len(child.node("g1").observations) == 3
    h = ctx.hierarchy
    two, one, three = _patient((42, None), (42, None)), _patient((42, None)), _patient(*[(42, None)] * 3)
    for m in (parent, child):
        assert not matches(m, two, h)      # facts for only two of the three observations
        assert not matches(m, one, h)      # one fact satisfying all three values
        assert matches(m, three, h)


def test_lift_on_observation_node_blocked(ctx):
    """The merged node carries no value but its observations do: the lattice converts its lifts to Blocked."""
    lat = enumerate_lattice(labs(42, 45), ctx, Budget(max_depth=2))
    merged = [h for h, c in lat.candidates.items() if any(n.observations for n in c.motif.nodes)]
    assert merged
    for h in merged:
        rows = [b for frm, b in lat.blocked if frm == h and b.op == "concept_lift" and b.target == "g1"]
        if lat.candidates[h].depth < 2:
            # GFR's only parent is the top-level OBS: concept lift itself rejects it, so no move is left to convert
            assert [b.reason for b in rows] == ["top_level_concept"]
    assert all(c.motif.node("g1").code == GFR for c in lat.candidates.values()
               if "g1" in c.motif.node_ids and c.motif.node("g1").observations)


def test_check_order_containment_on_merges(ctx):
    """check_order (containment only, also the root proof) reads the two motifs. A merge is accepted; an
    observation whose value or date no longer contains the original, or whose source is not in the parent, is
    rejected; widening or deleting an observation is a generalisation and is accepted (chains rely on it).
    Exactness of the merge itself is test_check_a1_merge_requires_exact_merge."""
    parent = labs(42, 45, 40)
    child = only_move(parent, ctx).child
    assert check_order(parent, child, ctx).ok
    obs = child.node("g1").observations

    def with_obs(*o):
        return upd(child, "g1", observations=tuple(o))

    changed = with_obs(obs[0], obs[1].model_copy(update={"value": Interval.point(46, U)}), obs[2])
    r = check_order(parent, changed, ctx)
    assert (r.ok, r.reason, r.where) == (False, "observation_not_contained", "g1")
    moved = with_obs(obs[0], obs[1].model_copy(update={"dates": {"taken": "2026-02-02"}}), obs[2])
    assert check_order(parent, moved, ctx).reason == "observation_not_contained"
    ghost = with_obs(obs[0], obs[1], Observation(value=Interval.point(40, U), source_node="g9"))
    assert check_order(parent, ghost, ctx).reason == "observation_source_missing"
    reused = upd(child, "g1", observations=(obs[0], obs[1], obs[1]))
    assert check_order(parent, reused, ctx).reason == "observation_source_reused"
    widened = with_obs(obs[0], obs[1].model_copy(update={"value": Interval.closed(44, 46, U)}), obs[2])
    assert check_order(parent, widened, ctx).ok
    assert check_order(parent, with_obs(obs[0], obs[2]), ctx).ok         # an observation deleted: more general
    assert check_order(child, with_obs(obs[0], obs[2]), ctx).ok
    assert check_order(child, child, ctx).ok and not check_order(child, parent, ctx).ok


def test_check_a1_merge_requires_exact_merge(ctx):
    """§7.3 proof, per merge transition: sources == {g.id} + the removed nodes, equal values and dates, nothing
    else changed. Each rejected child below passes containment (check_order) but is not an exact merge."""
    from semgen.order import check_a1_merge, is_a1_merge
    parent = labs(42, 45, 40)
    child = only_move(parent, ctx).child
    assert is_a1_merge(parent, child) and check_a1_merge(parent, child, ctx).ok
    obs = child.node("g1").observations

    def with_obs(m, *o):
        return upd(m, "g1", observations=tuple(o))

    def rejected(c, reason):
        assert check_order(parent, c, ctx).ok, "the case must be one containment alone accepts"
        r = check_a1_merge(parent, c, ctx)
        assert (r.ok, r.reason) == (False, reason), r

    # g3 removed but its observation dropped: a silent loss of one observation.
    rejected(with_obs(child, obs[0], obs[1]), "a1_sources_not_exact")
    # g.id missing from the sources (its own value lost).
    rejected(with_obs(child, obs[1], obs[2]), "a1_sources_not_exact")
    # Another node removed in the same transition, claimed by no observation.
    extra = parent.model_copy(update={
        "nodes": parent.nodes + (Node(id="z", type="Substance", role="exposure", code="X"),),
        "edges": parent.edges + (Edge(s="P", t="z", rel="administered_drug", prov="asserted"),)})
    assert check_a1_merge(extra, only_move(extra, ctx).child.without({"z"}, set()), ctx).reason == \
        "a1_sources_not_exact"
    # A changed (widened) value and a dropped date: contained, but not equal.
    rejected(with_obs(child, obs[0], obs[1].model_copy(update={"value": Interval.closed(44, 46, U)}), obs[2]),
             "a1_observation_changed")
    rejected(with_obs(child, obs[0], obs[1].model_copy(update={"dates": {}}), obs[2]), "a1_observation_changed")
    # Something else changed in the same transition.
    rejected(upd(child, "a", code=None), "a1_other_change")
    rejected(upd(child, "g1", test=None), "a1_other_change")             # merged node's own fields changed
    rejected(child.without(set(), {("P", "a")}), "a1_other_change")      # an unrelated edge dropped
    # Not a merge transition at all.
    assert check_a1_merge(parent, parent, ctx).reason == "not_a1_merge" and not is_a1_merge(parent, parent)


def test_lattice_rejects_inexact_merge(ctx, monkeypatch):
    """The lattice runs check_a1_merge on merge transitions: an operator that drops a source raises."""
    import semgen.lattice as L
    from semgen.operators.base import Move, OperatorResult

    def lossy(m, c):
        res = attribute_aggregation(m, c)
        out = []
        for mv in res.moves:
            g = mv.child.node(mv.change.target)
            out.append(Move(upd(mv.child, g.id, observations=g.observations[:-1]), mv.change))
        return OperatorResult(out, res.blocked)

    from tests.support.ops import with_ops
    with pytest.raises(L.GeneralizationOrderError, match="a1_sources_not_exact"):
        enumerate_lattice(labs(42, 45, 40), with_ops(ctx, lossy), Budget(max_depth=1))
    assert enumerate_lattice(labs(42, 45, 40), with_ops(ctx, attribute_aggregation), Budget(max_depth=1)).status == "exhausted"


def test_check_order_rejects_merging_a_node_still_in_general(ctx):
    parent = labs(42, 45)
    child = only_move(parent, ctx).child
    # Keep g2 as its own node too: one patient fact cannot serve both g2 and the g2 observation.
    both = child.model_copy(update={"nodes": child.nodes + (parent.node("g2"),),
                                    "edges": child.edges + (parent.edge("P", "g2"),)})
    assert check_order(parent, both, ctx).reason == "observation_source_reused"


def test_guard_rejects_code_change_on_observation_node(ctx):
    """Second line behind the lattice conversion: the guard treats observations like a value."""
    import semgen.lattice as L
    from tests.conftest import OBS
    parent = only_move(labs(42, 45), ctx).child
    assert parent.node("g1").value is None and parent.node("g1").observations
    lifted = upd(parent, "g1", code=OBS)                     # GFR -> its direct parent, accepted by the floor
    with pytest.raises(L.PolicyViolation, match="lift_on_valued_node: g1"):
        L.guard(parent, lifted, None, ctx)


# --- identity, units and preservation ------------------------------------------------------------------------

def test_mismatched_method_blocks(ctx):
    b = only_block(upd(labs(42, 45), "g2", test=GT.model_copy(update={"method": "measured"})), ctx)
    assert (b.reason, b.detail["field"], b.detail["values"]) == ("measurement_identity_differs", "method",
                                                                 ["calc", "measured"])


def test_mismatched_units_never_merge(ctx):
    m = upd(labs(42, 45), "g2", value=Interval.point(45, "mL/min"))
    assert attribute_aggregation(m, ctx).moves == []


def test_invalid_ucum_unit_blocks(ctx):
    bad = "mL/min/1.73m2"
    m = labs(42, 45)
    for nid in ("g1", "g2"):
        m = upd(m, nid, value=m.node(nid).value.model_copy(update={"unit": bad}))
    b = only_block(m, ctx)
    assert (b.target, b.reason, b.detail["unit"], b.detail["status"]) == ("g1", "unit_invalid", bad, "invalid")


def test_no_ucum_essence_blocks(ctx):
    b = only_block(labs(42, 45), dataclasses.replace(ctx, ucum=None))
    assert (b.target, b.reason, b.detail["unit"]) == ("g1", "unit_validation_unavailable", U)


def test_conflicting_patient_relationships_block(ctx):
    m = labs(42, 45)
    m = m.replace_edge(m.edge("P", "g2").model_copy(update={"window": Interval.closed(0, 3, "d")}))
    assert only_block(m, ctx).reason == "observation_edges_differ"


def test_each_observation_keeps_its_reference_range_and_label(ctx):
    rr = [ReferenceRange(interval=Interval.closed(60, 120, U), kind="reference", test=GT, source="lab",
                         source_ref=f"r{i}") for i in (1, 2)]
    m = upd(upd(labs(42, 45), "g1", reference_range=rr[0], label="GFR Jan"), "g2", reference_range=rr[1],
            label="GFR Feb")
    mv = only_move(m, ctx)
    g = mv.child.node("g1")
    assert [(o.source_node, o.reference_range, o.label) for o in g.observations] == [
        ("g1", rr[0], "GFR Jan"), ("g2", rr[1], "GFR Feb")]
    assert g.test == GT                    # the shared identity stays on the node
    assert g.reference_range is None       # the ranges differ: only the observations carry them
    from semgen.order import check_a1_merge
    assert check_a1_merge(m, mv.child, ctx).ok
    dropped = upd(mv.child, "g1", observations=(g.observations[0], g.observations[1].model_copy(
        update={"reference_range": None})))
    assert check_a1_merge(m, dropped, ctx).reason == "a1_observation_changed"


def test_checker_refuses_merging_a_different_measurement(ctx):
    """Independent of the generator: an observation whose source node had another code or test is not exact."""
    from semgen.order import check_a1_merge
    parent = labs(42, 45)
    child = only_move(parent, ctx).child
    for change in ({"code": LVEF}, {"test": GT.model_copy(update={"specimen": "Plasma"})},
                   {"test": GT.model_copy(update={"method": None})}):
        p2 = upd(parent, "g2", **change)
        assert check_a1_merge(p2, child, ctx).reason == "a1_identity_differs", change


def test_no_statistical_summary_replaces_values(ctx):
    g = only_move(labs(42, 45, 40), ctx).child.node("g1")
    assert g.value is None and sorted(o.value.lo for o in g.observations) == [40, 42, 45]



def test_node_reference_range_kept_only_when_shared(ctx):
    from semgen.order import check_a1_merge
    rr = ReferenceRange(interval=Interval.closed(60, 120, U), kind="reference", test=GT, source="lab", source_ref="r")
    shared = upd(upd(labs(42, 45), "g1", reference_range=rr), "g2", reference_range=rr)
    g = only_move(shared, ctx).child.node("g1")
    assert g.reference_range == rr and [o.reference_range for o in g.observations] == [rr, rr]
    one_only = upd(labs(42, 45), "g1", reference_range=rr)   # g2 reports none: not shared
    mv = only_move(one_only, ctx)
    assert mv.child.node("g1").reference_range is None
    assert [o.reference_range for o in mv.child.node("g1").observations] == [rr, None]
    assert check_a1_merge(one_only, mv.child, ctx).ok
    # the checker derives the node-level range itself: the first source's range kept anyway is refused
    kept_first = upd(mv.child, "g1", reference_range=rr)
    assert check_a1_merge(one_only, kept_first, ctx).reason == "a1_other_change"


def test_reference_range_on_merged_node_does_not_change_matching(ctx):
    rr = ReferenceRange(interval=Interval.closed(60, 120, U), kind="reference", test=GT, source="lab", source_ref="r")
    parent = upd(labs(42, 45), "g1", reference_range=rr)
    child = only_move(parent, ctx).child
    pats = [_patient((42, "2026-01-01"), (45, "2026-02-01")), _patient((42, "2026-01-01")),
            _patient((42, "2026-01-01"), (45, "2026-02-01"), (1, None)), _patient((45, "2026-01-01"), (42, "2026-02-01"))]
    assert [matches(parent, p, ctx.hierarchy) for p in pats] == [matches(child, p, ctx.hierarchy) for p in pats]


def test_observation_serialisation_round_trips_label_and_range():
    """Labels are excluded from canonical JSON by design (as for nodes); the model itself round-trips both."""
    from semgen.canonical import canonical_json
    rr = ReferenceRange(interval=Interval.closed(60, 120, U), kind="reference", test=GT, source="lab", source_ref="r")
    o = Observation(value=Interval.point(42, U), dates={"taken": "2026-01-01"}, source_node="g1", label="GFR Jan",
                    reference_range=rr)
    assert Observation.model_validate(o.model_dump(mode="json")) == o
    m = labs(42).replace_node(labs(42).node("g1").model_copy(update={"value": None, "observations": (o,)}))
    import json
    (row,) = [n for n in json.loads(canonical_json(m))["nodes"] if n["id"] == "g1"]
    assert row["observations"][0]["reference_range"]["source_ref"] == "r" and "label" not in row["observations"][0]


@pytest.mark.parametrize("ucum, rule", [(None, "a1_unit_unverified"), ("only-other-units", "a1_unit_invalid")])
def test_guard_refuses_a1_merge_without_valid_ucum(ctx, ucum, rule):
    """A merge that bypasses the generator (here: produced under a permissive essence) is refused by the guard."""
    from semgen.lattice import PolicyViolation, guard
    from semgen.lattice.moves import _accept
    parent = labs(42, 45)
    mv = only_move(parent, ctx)
    strict = dataclasses.replace(ctx, ucum=None if ucum is None else test_ucum("zzz"))
    with pytest.raises(PolicyViolation, match=rule):
        guard(parent, mv.child, mv.change, strict)
    with pytest.raises(PolicyViolation, match=rule):
        _accept(parent, mv, strict)
    _accept(parent, mv, ctx)   # the same merge with the pinned units valid is accepted


def test_guard_rechecks_units_when_observations_change(ctx):
    """A forged edit of an existing aggregate's observation unit is re-validated, not trusted."""
    from semgen.lattice import PolicyViolation, guard
    child = only_move(labs(42, 45), ctx).child
    g = child.node("g1")
    obs = (g.observations[0].model_copy(update={"value": Interval.point(42, "mEq/L")}), g.observations[1])
    with pytest.raises(PolicyViolation, match="a1_unit_invalid"):
        guard(child, upd(child, "g1", observations=obs), None, ctx)
    guard(child, child, None, ctx)   # unchanged observations: nothing to re-check
