from semgen.model import Interval
from semgen.operators.temporal_coarsening import temporal_coarsening


def test_walk_23_days(ctx, fake_m1):
    m, walk = fake_m1, []
    while (mvs := temporal_coarsening(m, ctx).moves):
        m = mvs[0].child; w = m.edge("n2", "n3").window; walk.append((w.lo, w.hi))
    assert walk == [(0, 30), (0, 90), (0, 365), (0, None)]
def test_lower_bound_never_negative_and_direction_kept(ctx, fake_m1):
    for mv in temporal_coarsening(fake_m1, ctx).moves:
        e = mv.child.edge("n2", "n3"); assert e.window.lo >= 0 and mv.child.edge("n3", "n2") is None
def test_180_days_jumps_to_365(ctx, fake_m2):
    assert temporal_coarsening(fake_m2, ctx).moves[0].change.after["hi"] == 365
def test_edges_without_window_untouched(ctx, fake_m1):
    assert {mv.change.target for mv in temporal_coarsening(fake_m1, ctx).moves} == {"n2->n3"}


def _win(m, s="n2", t="n3"):
    return m.edge(s, t).window


def test_walk_full_interval_equality(ctx, fake_m1):
    m, walk = fake_m1, []
    while (mvs := temporal_coarsening(m, ctx).moves):
        m = mvs[0].child; walk.append(_win(m))
    assert walk == [Interval(lo=0, hi=30, unit="d"), Interval(lo=0, hi=90, unit="d"),
                    Interval(lo=0, hi=365, unit="d"),
                    Interval(lo=0, hi=None, hi_closed=False, unit="d")]


def test_fractional_window(ctx, fake_m1):
    m = fake_m1.replace_edge(fake_m1.edge("n2", "n3").model_copy(
        update={"window": Interval(lo=0.5, hi=0.5, unit="d")}))
    mvs = temporal_coarsening(m, ctx).moves
    assert mvs[0].child.edge("n2", "n3").window == Interval(lo=0, hi=30, unit="d")


def test_end_of_ladder_no_move(ctx, fake_m1):
    top = Interval(lo=0, hi=None, hi_closed=False, unit="d")
    m = fake_m1.replace_edge(fake_m1.edge("n2", "n3").model_copy(update={"window": top}))
    r = temporal_coarsening(m, ctx)
    assert r.moves == [] and r.blocked == []


def test_context_edge_with_window_untouched(ctx, fake_m1):
    e = fake_m1.edge("n2", "n4")
    m = fake_m1.replace_edge(e.model_copy(update={"window": Interval(lo=1, hi=1, unit="d")}))
    assert {mv.change.target for mv in temporal_coarsening(m, ctx).moves} == {"n2->n3"}


def test_absent_touching_edge_untouched(ctx, fake_m2):
    e = fake_m2.edge("P", "n2")
    m = fake_m2.replace_edge(e.model_copy(update={"window": Interval(lo=1, hi=1, unit="d")}))
    assert {mv.change.target for mv in temporal_coarsening(m, ctx).moves} == {"n3->n5"}


def test_input_not_mutated(ctx, fake_m1):
    before = fake_m1.model_dump_json()
    temporal_coarsening(fake_m1, ctx)
    assert fake_m1.model_dump_json() == before


def test_strictly_contains_and_nonnegative(ctx, fake_m1):
    m = fake_m1
    while (mvs := temporal_coarsening(m, ctx).moves):
        old, new = _win(m), _win(mvs[0].child)
        assert new != old and new.lo >= 0 and new.lo <= old.lo
        assert new.hi is None or (old.hi is not None and new.hi >= old.hi)
        m = mvs[0].child


def test_full_change_record(ctx, fake_m1):
    from semgen.operators.base import ChangeRecord
    mv = temporal_coarsening(fake_m1, ctx).moves[0]
    old = fake_m1.edge("n2", "n3").window
    assert mv.change == ChangeRecord(
        "temporal_coarsening", "n2->n3", "window", old.to_json(),
        Interval(lo=0, hi=30, unit="d").to_json(), {"ladder": ctx.config.time_ladder.name})
