from semgen.operators import ALL_OPERATORS
from semgen.operators.base import ChangeRecord
from semgen.operators.relation_relaxation import relation_relaxation
from semgen.model import Edge


def test_m1_administered_drug(ctx, fake_m1):
    (mv,) = relation_relaxation(fake_m1, ctx).moves
    assert (mv.change.target, mv.change.before, mv.change.after) == ("P->n2", "administered_drug", "exposed_to_drug")


def test_only_rel_changes(ctx, fake_m1):
    (mv,) = relation_relaxation(fake_m1, ctx).moves
    a, b = fake_m1.edge("P", "n2"), mv.child.edge("P", "n2")
    assert a.model_dump(exclude={"rel"}) == b.model_dump(exclude={"rel"})


def test_has_finding_fixture(ctx, fake_m1):
    m = fake_m1.replace_edge(Edge(s="P", t="n1", rel="has_finding", prov="asserted"))
    assert any(mv.change.after == "has_observation" for mv in relation_relaxation(m, ctx).moves)


def test_context_edges_never_relaxed(ctx, fake_m1):
    m = fake_m1.replace_edge(fake_m1.edge("n2", "n4").model_copy(update={"rel": "administered_drug"}))
    assert all(mv.change.target != "n2->n4" for mv in relation_relaxation(m, ctx).moves)


def test_edge_into_absent_node_never_relaxed(ctx, fake_m2):
    m = fake_m2.replace_edge(fake_m2.edge("P", "n2").model_copy(update={"rel": "has_finding"}))
    assert all(mv.change.target != "P->n2" for mv in relation_relaxation(m, ctx).moves)


def test_full_change_record(ctx, fake_m1):
    (mv,) = relation_relaxation(fake_m1, ctx).moves
    assert mv.change == ChangeRecord(
        "relation_relaxation", "P->n2", "rel", "administered_drug", "exposed_to_drug",
        {"relation_parent": ["administered_drug", "exposed_to_drug"]})


def test_has_finding_exactly_has_observation(ctx, fake_m1):
    m = fake_m1.replace_edge(Edge(s="P", t="n1", rel="has_finding", prov="asserted"))
    mv = next(mv for mv in relation_relaxation(m, ctx).moves if mv.change.target == "P->n1")
    assert mv.change.after == "has_observation"
    assert mv.child.edge("P", "n1").rel == "has_observation"


def test_one_step_only(ctx, fake_m1):
    (mv,) = relation_relaxation(fake_m1, ctx).moves
    assert mv.child.edge("P", "n2").rel == "exposed_to_drug"
    again = relation_relaxation(mv.child, ctx)
    assert all(m.change.target != "P->n2" for m in again.moves)
    assert not again.blocked


def test_window_preserved(ctx, fake_m1):
    e = fake_m1.edge("n2", "n3")
    m = fake_m1.replace_edge(e.model_copy(update={"rel": "administered_drug"}))
    mv = next(mv for mv in relation_relaxation(m, ctx).moves if mv.change.target == "n2->n3")
    assert mv.child.edge("n2", "n3").window == e.window
    assert mv.child.edge("n2", "n3").window is not None


def test_derived_edge_never_relaxed(ctx, fake_m1):
    e = fake_m1.edge("P", "n2").model_copy(update={"prov": "derived"})
    m = fake_m1.replace_edge(e)
    assert relation_relaxation(m, ctx).moves == []


def test_input_not_mutated(ctx, fake_m1):
    before = fake_m1.model_dump()
    relation_relaxation(fake_m1, ctx)
    assert fake_m1.model_dump() == before


def test_registry_index():
    assert ALL_OPERATORS.index(relation_relaxation) == 4
