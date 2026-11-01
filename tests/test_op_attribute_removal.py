from semgen.canonical import canonical_json
from semgen.model import Interval
from semgen.operators.attribute_removal import attribute_removal


def test_m1_removals(ctx, fake_m1):
    got = {(m.change.target, m.change.field) for m in attribute_removal(fake_m1, ctx).moves}
    assert got == {("n1", "attrs.age_at_dx"), ("n2", "attrs.cumulative_dose"), ("n3", "value")}


def test_child_lacks_only_that_field(ctx, fake_m1):
    mv = next(m for m in attribute_removal(fake_m1, ctx).moves if m.change.field == "value")
    assert mv.child.node("n3").value is None and mv.child.node("n1").attrs == fake_m1.node("n1").attrs
    assert mv.change.before["lo"] == 38


def test_absent_nodes_skipped(ctx, fake_m2):
    n = fake_m2.node("n2")
    m = fake_m2.replace_node(n.model_copy(update={"value": Interval.point(1, "x")}))
    assert all(mv.change.target != "n2" for mv in attribute_removal(m, ctx).moves)


def test_m2_single_move_and_pure(ctx, fake_m2):
    before = canonical_json(fake_m2)
    res = attribute_removal(fake_m2, ctx)
    assert [(m.change.target, m.change.field) for m in res.moves] == [("n5", "value")]
    assert res.blocked == [] and canonical_json(fake_m2) == before


def test_attr_move_drops_only_that_attr(ctx, fake_m1):
    mv = next(m for m in attribute_removal(fake_m1, ctx).moves if m.change.field == "attrs.age_at_dx")
    assert dict(mv.child.node("n1").attrs) == {} and mv.change.after is None
    assert mv.child.node("n2") == fake_m1.node("n2")
