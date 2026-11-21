"""Attribute deletion (design §7.2; replaces attribute_removal).

Replaces tests/test_op_attribute_removal.py (Task 2). Old expectations and where they went:
- test_m1_removals ({n1 age_at_dx, n3 value}) -> test_fake_m1_moves (now also the window and its two bounds).
- test_child_lacks_only_that_field, test_attr_move_drops_only_that_attr -> test_patient_attr_deleted_dependent_blocked,
  test_value_deleted.
- test_absent_nodes_skipped -> test_absent_node_untouched.
- test_m2_single_move_and_pure ([n5 value]) -> test_fake_m2_moves_and_pure (now also the n3->n5 window and bounds).
- test_dose_removal_blocked_and_logged, test_unflagged_attr_not_removed -> test_patient_attr_deleted_dependent_blocked,
  test_unlisted_attr_blocked (op name attribute_deletion instead of attribute_removal).
"""
import pytest as _pytest

from semgen.canonical import canonical_json
from semgen.model import Interval, Observation
from semgen.operators.attribute_deletion import attribute_deletion
from semgen.order import check_order
from tests.support.relevance import relaxed


# Rev 4: deletion moves need a relaxable relevance decision; these tests are about what deletions do, so they
# run with every candidate relaxable (tests/support/relevance.py). The gate itself: tests/test_relevance.py.
@_pytest.fixture
def ctx(ctx):
    return relaxed(ctx)



def moves(m, ctx):
    return {(mv.change.target, mv.change.field): mv for mv in attribute_deletion(m, ctx).moves}


def test_fake_m1_moves(ctx, fake_m1):
    got = moves(fake_m1, ctx)
    assert set(got) == {("n1", "attrs.age_at_dx"), ("n3", "value"), ("n2->n3", "window"),
                        ("n2->n3", "window.lo"), ("n2->n3", "window.hi")}
    for mv in got.values():
        assert mv.change.op == "attribute_deletion" and mv.change.meaning == "generalized"
        assert check_order(fake_m1, mv.child, ctx).ok


def test_fake_m2_moves_and_pure(ctx, fake_m2):
    before = canonical_json(fake_m2)
    res = attribute_deletion(fake_m2, ctx)
    assert [(m.change.target, m.change.field) for m in res.moves] == [
        ("n5", "value"), ("n3->n5", "window"), ("n3->n5", "window.lo"), ("n3->n5", "window.hi")]
    assert res.blocked == [] and canonical_json(fake_m2) == before


def test_patient_attr_deleted_dependent_blocked(ctx, fake_m1):
    res = attribute_deletion(fake_m1, ctx)
    mv = next(m for m in res.moves if m.change.field == "attrs.age_at_dx")
    assert dict(mv.child.node("n1").attrs) == {} and mv.child.node("n2") == fake_m1.node("n2")
    assert mv.change.rule_id == "attr.delete.attr" and mv.change.after is None
    assert mv.change.before == Interval.point(67, "a").to_json()
    assert all(m.change.field != "attrs.cumulative_dose" for m in res.moves)
    # Every candidate is declared relaxable here, so the protected attribute is a conflict: unknown, blocked.
    assert [(b.op, b.target, b.reason, b.detail["field"], b.detail["decision"]) for b in res.blocked] == [
        ("attribute_deletion", "n2", "relevance_unknown", "attrs.cumulative_dose", "unknown")]
    assert "concept-dependent" in res.blocked[0].detail["reason"]


def test_unlisted_attr_blocked(ctx, fake_m1):
    m = fake_m1.replace_node(fake_m1.node("n1").model_copy(update={"attrs": {"mystery": Interval.point(1, "x")}}))
    res = attribute_deletion(m, ctx)
    assert all(x.change.field != "attrs.mystery" for x in res.moves)
    (b,) = [b for b in res.blocked if b.target == "n1" and b.detail.get("field") == "attrs.mystery"]
    assert b.reason == "relevance_unknown" and b.detail["decision"] == "unknown"
    # missing metadata, reported as such (not as a conflict with a stated requirement)
    assert b.detail["reason"] == ("declared relaxable, but the attribute is unlisted in the attribute definitions; "
                                  "the existing contract treats an unlisted attribute as concept-dependent (protected)")
    assert not b.detail["reason"].startswith("conflict")


def test_value_deleted(ctx, fake_m1):
    mv = moves(fake_m1, ctx)[("n3", "value")]
    assert mv.child.node("n3").value is None and mv.child.node("n1").attrs == fake_m1.node("n1").attrs
    assert (mv.change.rule_id, mv.change.before["lo"], mv.change.after) == ("attr.delete.value", 38, None)


def test_each_date_deleted(ctx, fake_m1):
    m = fake_m1.replace_node(fake_m1.node("n2").model_copy(update={"dates": {"start": "2026-01-02",
                                                                              "stop": "2026-03-04"}}))
    m = m.replace_edge(m.edge("P", "n2").model_copy(update={"dates": {"recorded": "2026-01-01"}}))
    got = moves(m, ctx)
    start, stop, rec = got[("n2", "dates.start")], got[("n2", "dates.stop")], got[("P->n2", "dates.recorded")]
    assert dict(start.child.node("n2").dates) == {"stop": "2026-03-04"}
    assert dict(stop.child.node("n2").dates) == {"start": "2026-01-02"}
    assert dict(rec.child.edge("P", "n2").dates) == {}
    assert (start.change.rule_id, start.change.before, start.change.after) == ("attr.delete.date", "2026-01-02", None)
    assert rec.change.rule_id == "attr.delete.date"
    assert all(check_order(m, mv.child, ctx).ok for mv in got.values())


def test_window_deleted_edge_kept(ctx, fake_m1):
    mv = moves(fake_m1, ctx)[("n2->n3", "window")]
    old, new = fake_m1.edge("n2", "n3"), mv.child.edge("n2", "n3")
    assert new is not None and new.window is None
    assert (new.rel, new.s, new.t, new.prov) == (old.rel, old.s, old.t, old.prov)
    assert len(mv.child.edges) == len(fake_m1.edges)
    assert (mv.change.rule_id, mv.change.before, mv.change.after) == (
        "attr.delete.window", Interval.point(23, "d").to_json(), None)


def test_window_bound_deleted(ctx, fake_m1):
    got = moves(fake_m1, ctx)
    lo, hi = got[("n2->n3", "window.lo")], got[("n2->n3", "window.hi")]
    assert lo.child.edge("n2", "n3").window == Interval(lo=None, hi=23, unit="d")
    assert hi.child.edge("n2", "n3").window == Interval(lo=23, hi=None, unit="d")
    assert (lo.change.rule_id, hi.change.rule_id) == ("attr.delete.window_lo", "attr.delete.window_hi")
    assert lo.change.after == Interval(lo=None, hi=23, unit="d").to_json()
    # A one-sided window offers only the whole-window deletion (its single bound is the window).
    m = lo.child
    assert {f for (t, f) in moves(m, ctx) if t == "n2->n3"} == {"window"}


def test_absent_node_untouched(ctx, fake_m2):
    n = fake_m2.node("n2")
    m = fake_m2.model_copy(update={"nodes": tuple(
        x.model_copy(update={"attrs": {"age_at_dx": Interval.point(1, "a")}}) if x.id == "n2" else x
        for x in fake_m2.nodes)})
    m = m.replace_edge(m.edge("P", "n2").model_copy(update={"dates": {"recorded": "2026-01-01"}}))
    res = attribute_deletion(m, ctx)
    assert all(mv.change.target not in ("n2", "P->n2") for mv in res.moves)
    assert all(b.target not in ("n2", "P->n2") for b in res.blocked)
    assert n.polarity == "absent"


def test_context_edges_untouched(ctx, fake_m1):
    m = fake_m1.replace_edge(fake_m1.edge("n2", "n4").model_copy(update={"dates": {"seen": "2026-01-01"}}))
    assert all(mv.change.target != "n2->n4" for mv in attribute_deletion(m, ctx).moves)


def _merged(fake_m2, n_obs):
    obs = tuple(Observation(value=Interval.point(40 + i, "mL/min/1.73m2"), source_node="n5" if i == 0 else f"x{i}",
                            dates={"taken": f"2026-01-0{i + 1}"}) for i in range(n_obs))
    return fake_m2.replace_node(fake_m2.node("n5").model_copy(update={"value": None, "observations": obs}))


def test_observation_deleted_only_when_two_remain(ctx, fake_m2):
    three = _merged(fake_m2, 3)
    got = {k: v for k, v in moves(three, ctx).items() if k[0] == "n5"}
    assert set(got) == {("n5", "observations.n5"), ("n5", "observations.x1"), ("n5", "observations.x2")}
    mv = got[("n5", "observations.x1")]
    assert [o.source_node for o in mv.child.node("n5").observations] == ["n5", "x2"]
    assert mv.change.rule_id == "attr.delete.observation" and mv.change.after is None
    assert mv.change.before == {"value": Interval.point(41, "mL/min/1.73m2").to_json(),
                                "dates": {"taken": "2026-01-02"}, "source_node": "x1", "source_record": None,
                                "label": None, "reference_range": None}
    assert check_order(three, mv.child, ctx).ok
    two = _merged(fake_m2, 2)
    assert not [k for k in moves(two, ctx) if k[0] == "n5"]



def test_deleted_observation_record_keeps_label_and_reference_range(ctx, fake_m2):
    """The ChangeRecord of a deleted A1 observation keeps its full provenance (label, reported reference range)."""
    from semgen.model import ReferenceRange, TestIdentity
    rr = ReferenceRange(interval=Interval.closed(60, 120, "mL/min/1.73m2"), kind="reference",
                        test=TestIdentity(system="s", code="c", method="m", specimen="sp"), source="lab",
                        source_ref="r-x1")
    three = _merged(fake_m2, 3)
    n5 = three.node("n5")
    obs = (n5.observations[0], n5.observations[1].model_copy(update={"label": "eGFR 2 Jan", "reference_range": rr}),
           n5.observations[2])
    three = three.replace_node(n5.model_copy(update={"observations": obs}))
    before = moves(three, ctx)[("n5", "observations.x1")].change.before
    assert before["label"] == "eGFR 2 Jan" and before["reference_range"] == rr.model_dump(mode="json")
    assert ReferenceRange.model_validate(before["reference_range"]) == rr   # deserialises to the same range
