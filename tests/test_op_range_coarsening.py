from semgen.model import Interval
from semgen.operators import ALL_OPERATORS
from semgen.operators.range_coarsening import range_coarsening


def step(ctx, m, target, field):
    return next(mv for mv in range_coarsening(m, ctx).moves
                if (mv.change.target, mv.change.field) == (target, field))


def walk(ctx, m, target, field):
    out = []
    while True:
        mvs = [mv for mv in range_coarsening(m, ctx).moves
               if (mv.change.target, mv.change.field) == (target, field)]
        if not mvs:
            return m, out
        m = mvs[0].child
        node = m.node(target)
        new = node.value if field == "value" else node.attrs[field.split(".", 1)[1]]
        prev = mvs[0].change.before
        assert new.strictly_contains(Interval(**prev)) and new.unit == prev["unit"]
        out.append(new)


def test_m1_first_steps(ctx, fake_m1):
    got = {(mv.change.target, mv.change.field): mv for mv in range_coarsening(fake_m1, ctx).moves}
    assert set(got) == {("n3", "value"), ("n1", "attrs.age_at_dx"), ("n2", "attrs.cumulative_dose")}
    assert got[("n3", "value")].child.node("n3").value == Interval(
        lo=0, hi=40, hi_closed=False, unit="%")
    assert got[("n1", "attrs.age_at_dx")].child.node("n1").attrs["age_at_dx"] == Interval(
        lo=65, hi=80, hi_closed=False, unit="a")
    assert got[("n2", "attrs.cumulative_dose")].child.node("n2").attrs[
        "cumulative_dose"] == Interval(lo=250, hi=None, unit="mg/m2")


def test_lvef_walk_to_end(ctx, fake_m1):
    m, w = fake_m1, []
    while True:
        mvs = [mv for mv in range_coarsening(m, ctx).moves
               if (mv.change.target, mv.change.field) == ("n3", "value")]
        if not mvs:
            break
        m = mvs[0].child
        w.append(m.node("n3").value)
    assert w == [Interval(lo=0, hi=40, hi_closed=False, unit="%"),
                 Interval(lo=0, hi=50, hi_closed=False, unit="%"),
                 Interval(lo=0, hi=55, hi_closed=False, unit="%")]


def test_value_outside_every_rung(ctx, fake_m1):
    n = fake_m1.node("n3")
    m = fake_m1.replace_node(n.model_copy(update={"value": Interval.point(120, "%")}))
    assert not [mv for mv in range_coarsening(m, ctx).moves if mv.change.target == "n3"]
    assert not range_coarsening(m, ctx).blocked


def test_unit_mismatch_blocked(ctx, fake_m1):
    n = fake_m1.node("n3")
    m = fake_m1.replace_node(n.model_copy(update={"value": Interval.point(38, "fraction")}))
    res = range_coarsening(m, ctx)
    assert any(b.reason == "unit_mismatch" for b in res.blocked)
    b = next(b for b in res.blocked if b.reason == "unit_mismatch")
    assert b.detail == {"field": "value", "unit": "fraction", "ladder_unit": "%"}


def test_absent_nodes_skipped(ctx, fake_m2):
    res = range_coarsening(fake_m2, ctx)
    assert all(mv.change.target != "n2" for mv in res.moves)
    assert all(b.target != "n2" for b in res.blocked)


def test_lvef_60_makes_one_move_then_stops(ctx, fake_m1):
    n = fake_m1.node("n3")
    m = fake_m1.replace_node(n.model_copy(update={"value": Interval.point(60, "%")}))
    _, w = walk(ctx, m, "n3", "value")
    assert w == [Interval(lo=55, hi=101, hi_closed=False, unit="%")]


def test_egfr_walk(ctx, fake_m2):
    _, w = walk(ctx, fake_m2, "n5", "value")
    assert w == [Interval(lo=30, hi=45, hi_closed=False, unit="mL/min/1.73m2"),
                 Interval(lo=30, hi=60, hi_closed=False, unit="mL/min/1.73m2"),
                 Interval(lo=0, hi=60, hi_closed=False, unit="mL/min/1.73m2")]


def test_age_and_dose_walks(ctx, fake_m1):
    n = fake_m1.node("n1")
    m = fake_m1.replace_node(n.model_copy(update={"attrs": {"age_at_dx": Interval(
        lo=65, hi=80, unit="a", hi_closed=False)}}))
    _, w = walk(ctx, m, "n1", "attrs.age_at_dx")
    assert w == [Interval(lo=65, hi=None, unit="a")]
    n = fake_m1.node("n2")
    m = fake_m1.replace_node(n.model_copy(update={"attrs": {"cumulative_dose": Interval(
        lo=250, hi=None, unit="mg/m2", hi_closed=False)}}))
    _, w = walk(ctx, m, "n2", "attrs.cumulative_dose")
    assert w == [Interval(lo=100, hi=None, unit="mg/m2")]


def test_no_ladder_blocked_and_pure(ctx, fake_m1):
    n = fake_m1.node("n1")
    m = fake_m1.replace_node(n.model_copy(update={"attrs": {"zzz": Interval.point(1, "a")}}))
    before = m.model_dump_json()
    res = range_coarsening(m, ctx)
    assert m.model_dump_json() == before
    assert any(b.reason == "no_ladder" and b.detail == {"field": "attrs.zzz", "attr": "zzz"}
               for b in res.blocked)


def test_registered_last(ctx):
    assert ALL_OPERATORS[-1] is range_coarsening


def test_full_change_record(ctx, fake_m1):
    ch = step(ctx, fake_m1, "n3", "value").change
    lvef = ctx.config.value_ladder_for(fake_m1.node("n3").code)
    assert (ch.op, ch.target, ch.field) == ("range_coarsening", "n3", "value")
    assert ch.before == Interval.point(38, "%").to_json()
    assert ch.after == Interval(lo=0, hi=40, hi_closed=False, unit="%").to_json()
    assert ch.evidence == {"ladder": lvef.name}


def test_closed_endpoint_not_contained_in_half_open_rung(ctx, fake_m1):
    n = fake_m1.node("n3")
    closed = Interval(lo=0, hi=40, unit="%")
    m = fake_m1.replace_node(n.model_copy(update={"value": closed}))
    mv = step(ctx, m, "n3", "value")
    assert mv.child.node("n3").value == Interval(lo=0, hi=50, hi_closed=False, unit="%")
    assert mv.child.node("n3").value != Interval(lo=0, hi=40, hi_closed=False, unit="%")
