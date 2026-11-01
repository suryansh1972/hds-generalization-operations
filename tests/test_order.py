from hypothesis import HealthCheck, given, settings, strategies as st

from semgen.model import Interval
from semgen.order import check_order
from tests.conftest import *


def test_identity_both_ways(ctx, fake_m1):
    assert check_order(fake_m1, fake_m1, ctx).ok
def bad(ctx, s, g, reason): r = check_order(s, g, ctx); assert not r.ok and r.reason == reason
def test_sibling_drug(ctx, fake_m1):
    bad(ctx, fake_m1, fake_m1.replace_node(fake_m1.node("n2").model_copy(update={"code": DAUNO})), "concept_not_broader")
def test_narrowed_or_moved_lvef(ctx, fake_m1):
    wide = fake_m1.replace_node(fake_m1.node("n3").model_copy(update={"value": Interval(lo=0, hi=40, hi_closed=False, unit="%")}))
    bad(ctx, wide, wide.replace_node(wide.node("n3").model_copy(update={"value": Interval(lo=38, hi=39, unit="%")})), "value_not_contained")
    bad(ctx, fake_m1, fake_m1.replace_node(fake_m1.node("n3").model_copy(update={"value": Interval(lo=40, hi=50, hi_closed=False, unit="%")})), "value_not_contained")
def test_reversed_edge(ctx, fake_m1):
    base = fake_m1.without(set(), {("n2", "n3")})
    flipped = fake_m1.edge("n2", "n3").model_copy(update={"s": "n3", "t": "n2"})
    bad(ctx, fake_m1, base.model_copy(update={"edges": base.edges + (flipped,)}), "extra_edge")
def test_context_promoted_to_asserted(ctx, fake_m1):
    bad(ctx, fake_m1, fake_m1.replace_edge(fake_m1.edge("n2", "n4").model_copy(update={"prov": "asserted"})), "provenance_changed")
def test_absent_lifted(ctx, fake_m2):
    bad(ctx, fake_m2, fake_m2.replace_node(fake_m2.node("n2").model_copy(update={"code": DM})), "absent_not_narrower")
def test_value_added_fails_and_removed_passes(ctx, fake_m1):
    no_val = fake_m1.replace_node(fake_m1.node("n3").model_copy(update={"value": None}))
    assert check_order(fake_m1, no_val, ctx).ok
    bad(ctx, no_val, fake_m1, "value_added")
def test_every_single_operator_move_verifies(ctx, fake_m1, fake_m2):
    from semgen.operators import ALL_OPERATORS
    for m in (fake_m1, fake_m2):
        for op in ALL_OPERATORS:
            for mv in op(m, ctx).moves:
                r = check_order(m, mv.child, ctx); assert r.ok, (mv.change, r)


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None, max_examples=100)
@given(st.lists(st.integers(min_value=0, max_value=10_000), max_size=5))
def test_random_chains_stay_ordered(ctx, fake_m1, picks):
    from semgen.operators import ALL_OPERATORS
    cur, chain = fake_m1, [fake_m1]
    for idx in picks:
        moves = [mv for op in ALL_OPERATORS for mv in op(cur, ctx).moves]
        if not moves:
            break
        cur = moves[idx % len(moves)].child
        chain.append(cur)
    assert check_order(fake_m1, cur, ctx).ok
    for prev, nxt in zip(chain, chain[1:]):
        assert check_order(prev, nxt, ctx).ok


# --- focused extras ------------------------------------------------------------
def _with_val(m, iv):
    return m.replace_node(m.node("n3").model_copy(update={"value": iv}))


def test_endpoint_inclusivity(ctx, fake_m1):
    closed = _with_val(fake_m1, Interval(lo=0, hi=40, unit="%"))
    opened = _with_val(fake_m1, Interval(lo=0, hi=40, hi_closed=False, unit="%"))
    assert check_order(opened, closed, ctx).ok
    bad(ctx, closed, opened, "value_not_contained")


def test_unit_mismatch(ctx, fake_m1):
    bad(ctx, fake_m1, _with_val(fake_m1, Interval(lo=0, hi=100, unit="mmHg")), "value_not_contained")


def _with_attr(m, iv):
    n = m.node("n1")
    attrs = dict(n.attrs)
    if iv is None:
        attrs.pop("age_at_dx")
    else:
        attrs["age_at_dx"] = iv
    return m.replace_node(n.model_copy(update={"attrs": attrs}))


def test_attrs(ctx, fake_m1):
    removed = _with_attr(fake_m1, None)
    assert check_order(fake_m1, removed, ctx).ok
    bad(ctx, removed, fake_m1, "attr_added")
    wide = _with_attr(fake_m1, Interval(lo=60, hi=70, unit="a"))
    assert check_order(fake_m1, wide, ctx).ok
    bad(ctx, wide, fake_m1, "attr_not_contained")


def test_relation_narrowed(ctx, fake_m1):
    broad = fake_m1.replace_edge(fake_m1.edge("P", "n2").model_copy(update={"rel": "exposed_to_drug"}))
    assert check_order(fake_m1, broad, ctx).ok
    bad(ctx, broad, fake_m1, "relation_not_broader")


def test_window(ctx, fake_m1):
    e = fake_m1.edge("n2", "n3")
    wide = fake_m1.replace_edge(e.model_copy(update={"window": Interval(lo=0, hi=30, unit="d")}))
    none = fake_m1.replace_edge(e.model_copy(update={"window": None}))
    assert check_order(fake_m1, wide, ctx).ok and check_order(fake_m1, none, ctx).ok
    bad(ctx, none, fake_m1, "window_added")
    bad(ctx, wide, fake_m1, "window_not_contained")


def test_type_role_polarity(ctx, fake_m1, fake_m2):
    bad(ctx, fake_m1, fake_m1.replace_node(fake_m1.node("n2").model_copy(update={"type": "Disorder"})), "type_changed")
    bad(ctx, fake_m1, fake_m1.replace_node(fake_m1.node("n2").model_copy(update={"role": "modifier"})), "role_changed")
    bad(ctx, fake_m2, fake_m2.replace_node(fake_m2.node("n2").model_copy(update={"polarity": "present"})), "polarity_changed")


def test_context_code_changed(ctx, fake_m1):
    bad(ctx, fake_m1, fake_m1.replace_node(fake_m1.node("n4").model_copy(update={"code": "OTHER"})), "context_code_changed")


def test_extra_node(ctx, fake_m1):
    small = fake_m1.without({"n5"}, set())
    r = check_order(small, fake_m1, ctx)
    assert (r.ok, r.reason, r.where) == (False, "extra_node", "n5")


def test_removing_edge_or_node_ok(ctx, fake_m1):
    assert check_order(fake_m1, fake_m1.without(set(), {("n2", "n3")}), ctx).ok
    assert check_order(fake_m1, fake_m1.without({"n5"}, set()), ctx).ok


def test_reverse_direction_fails(ctx, fake_m1):
    from semgen.operators.concept_lift import concept_lift
    from semgen.operators.range_coarsening import range_coarsening
    (lift, *_) = concept_lift(fake_m1, ctx).moves
    r = check_order(lift.child, fake_m1, ctx)
    assert not r.ok and r.reason == "concept_not_broader"
    rng = next(mv for mv in range_coarsening(fake_m1, ctx).moves if mv.change.field == "value")
    r = check_order(rng.child, fake_m1, ctx)
    assert not r.ok and r.reason == "value_not_contained"


# --- fix round 1: pin the allowed side of each code direction -------------------
def _n2(m, code):
    return m.replace_node(m.node("n2").model_copy(update={"code": code}))


def test_absent_narrowing_allowed(ctx, fake_m2):
    assert check_order(_n2(fake_m2, DM), _n2(fake_m2, T2DM), ctx).ok


def test_absent_sibling_rejected(ctx, fake_m2):
    bad(ctx, _n2(fake_m2, T1DM), _n2(fake_m2, T2DM), "absent_not_narrower")


def test_absent_none_mismatch_rejected(ctx, fake_m2):
    bad(ctx, fake_m2, _n2(fake_m2, None), "absent_not_narrower")
    bad(ctx, _n2(fake_m2, None), fake_m2, "absent_not_narrower")


def test_present_none_handling(ctx, fake_m1):
    assert check_order(fake_m1, _n2(fake_m1, None), ctx).ok
    bad(ctx, _n2(fake_m1, None), fake_m1, "concept_not_broader")


def _n2v(m, value):
    return m.replace_node(m.node("n2").model_copy(update={"value": value}))


def test_absent_value_widened_rejected(ctx, fake_m2):
    narrow, wide = Interval(lo=1, hi=2, unit="%"), Interval(lo=0, hi=5, unit="%")
    bad(ctx, _n2v(fake_m2, narrow), _n2v(fake_m2, wide), "absent_constraint_changed")


def test_absent_value_removed_rejected(ctx, fake_m2):
    bad(ctx, _n2v(fake_m2, Interval(lo=1, hi=2, unit="%")), _n2v(fake_m2, None), "absent_constraint_changed")


def test_absent_equal_value_passes(ctx, fake_m2):
    v = Interval(lo=1, hi=2, unit="%")
    assert check_order(_n2v(fake_m2, v), _n2v(fake_m2, v), ctx).ok
