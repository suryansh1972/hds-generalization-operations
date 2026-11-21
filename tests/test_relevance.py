"""Relevance gate of attribute deletion (design §7.2): the declared cohort definition alone decides.

required -> rejected (``relevance_retain``); relaxable -> candidate; undeclared -> ``relevance_unknown``. A path
from the constrained node to the anchor never blocks a deletion on its own; a relaxable declaration that conflicts
with the attribute definitions is unknown. Every candidate is still proven by the guard and ``check_order``.
"""
import dataclasses

import pytest

from semgen.bundle import CohortDefinition
from semgen.lattice import GeneralizationOrderError, PolicyViolation
from semgen.lattice.moves import _accept
from semgen.model import Edge, Interval, Node
from semgen.operators.attribute_deletion import attribute_deletion, deletion_candidates
from semgen.operators.base import ChangeRecord, Move
from semgen.order import check_order
from semgen.relevance import assess


def cohort(*items) -> CohortDefinition:
    return CohortDefinition(id="C1", version="1", source="test", constraints=[
        {"target": t, "field": f, "necessity": n} for t, f, n in items])


def with_(ctx, **kw):
    return dataclasses.replace(ctx, **kw)


def linked(m):
    """``m`` with an asserted edge n3 -> n1 (the outcome is directly related to the anchor)."""
    return m.model_copy(update={"edges": m.edges + (Edge(s="n3", t="n1", rel="complication_of", prov="asserted"),)})


def with_absent(m):
    nodes = m.nodes + (Node(id="n9", type="Disorder", role="modifier", code=m.node("n1").code, polarity="absent"),)
    return m.model_copy(update={"nodes": nodes,
                                "edges": m.edges + (Edge(s="P", t="n9", rel="has_condition", prov="asserted"),)})


# --- the three declarations ------------------------------------------------------------------------------------

def test_no_cohort_everything_unknown_and_blocked(ctx, fake_m1):
    res = attribute_deletion(fake_m1, ctx)
    assert res.moves == []
    unknown = {(b.target, b.detail["field"]) for b in res.blocked if b.reason == "relevance_unknown"}
    assert unknown == {(mv.change.target, mv.change.field) for mv in deletion_candidates(fake_m1, ctx).moves}
    b = next(b for b in res.blocked if b.reason == "relevance_unknown")
    assert b.detail["necessity"]["status"] == "unknown" and b.detail["decision"] == "unknown"
    assert b.detail["reason"] == "no cohort definition declared"


def test_required_is_rejected(ctx, fake_m1):
    res = attribute_deletion(fake_m1, with_(ctx, cohort=cohort(("n3", "value", "required"))))
    b = next(b for b in res.blocked if b.target == "n3")
    assert b.reason == "relevance_retain" and b.detail["decision"] == "retain"
    assert all(mv.change.target != "n3" for mv in res.moves)


def test_undeclared_in_a_declared_cohort_is_unknown(ctx, fake_m1):
    res = attribute_deletion(fake_m1, with_(ctx, cohort=cohort(("n3", "value", "relaxable"))))
    assert [(m.change.target, m.change.field) for m in res.moves] == [("n3", "value")]
    b = next(b for b in res.blocked if (b.target, b.detail.get("field")) == ("n1", "attrs.age_at_dx"))
    assert b.reason == "relevance_unknown" and b.detail["reason"] == "the cohort definition does not declare this constraint"


def test_relaxable_generates_a_verified_candidate(ctx, fake_m1):
    """Disorder + age_at_dx = 67, declared relaxable -> the disorder alone; check_order proves it broader."""
    c = with_(ctx, cohort=cohort(("n1", "attrs.age_at_dx", "relaxable")))
    res = attribute_deletion(fake_m1, c)
    (mv,) = res.moves
    assert (mv.change.target, mv.change.field, mv.change.after) == ("n1", "attrs.age_at_dx", None)
    assert mv.change.evidence["relevance"]["decision"] == "relaxable"
    assert mv.change.evidence["relevance"]["necessity"]["source"] == {"id": "C1", "version": "1", "source": "test"}
    assert dict(mv.child.node("n1").attrs) == {}
    assert check_order(fake_m1, mv.child, c).ok
    _accept(fake_m1, mv, c)   # guard + independent order checker


# --- graph distance never decides ---------------------------------------------------------------------------

def test_connected_node_with_relaxable_constraint_is_deletable(ctx, fake_m1):
    m = linked(fake_m1)
    c = with_(ctx, cohort=cohort(("n3", "value", "relaxable")))
    (mv,) = attribute_deletion(m, c).moves
    assert (mv.change.target, mv.change.field) == ("n3", "value")
    assert "relationship" not in mv.change.evidence["relevance"]
    _accept(m, mv, c)


@pytest.mark.parametrize("connected", [False, True])
def test_graph_distance_does_not_change_the_decision(ctx, fake_m1, connected):
    m = linked(fake_m1) if connected else fake_m1
    for need in ("required", "relaxable"):
        c = with_(ctx, cohort=cohort(("n3", "value", need), ("n2->n3", "window", need)))
        got = {(mv.change.target, mv.change.field) for mv in attribute_deletion(m, c).moves}
        assert got == ({("n3", "value"), ("n2->n3", "window")} if need == "relaxable" else set())


def test_assess_reads_only_the_declaration(ctx):
    c = with_(ctx, cohort=cohort(("x", "value", "relaxable"), ("y", "value", "required")))
    assert assess("x", "value", c)["decision"] == "relaxable"
    assert assess("y", "value", c)["decision"] == "retain"
    assert assess("z", "value", c)["decision"] == "unknown"
    assert assess("x", "value", c, ("a stated conflict",))["decision"] == "unknown"


# --- conflicts and protected structure ----------------------------------------------------------------------

def test_relaxable_conflicting_with_attribute_definitions_is_unknown(ctx, fake_m1):
    """cumulative_dose is ``about: node_concept``: a relaxable declaration does not override it."""
    c = with_(ctx, cohort=cohort(("n2", "attrs.cumulative_dose", "relaxable")))
    res = attribute_deletion(fake_m1, c)
    assert res.moves == []
    b = next(b for b in res.blocked if b.target == "n2")
    assert b.reason == "relevance_unknown" and b.detail["decision"] == "unknown"
    assert b.detail["reason"].startswith("conflict: declared relaxable") and "concept-dependent" in b.detail["reason"]


def test_concept_dependent_attr_without_relaxable_declaration(ctx, fake_m1):
    res = attribute_deletion(fake_m1, with_(ctx, cohort=cohort(("n2", "attrs.cumulative_dose", "required"))))
    b = next(b for b in res.blocked if b.target == "n2")
    assert (b.reason, b.detail) == ("concept_dependent_attr", {"attr": "cumulative_dose"})


def test_only_the_requested_constraint_goes(ctx, fake_m1):
    m = with_absent(fake_m1)
    c = with_(ctx, cohort=cohort(("n1", "attrs.age_at_dx", "relaxable")))
    (mv,) = attribute_deletion(m, c).moves
    child = mv.child
    assert child.node_ids == m.node_ids and child.edges == m.edges   # every node and edge (context too) stays
    assert child.node("n9") == m.node("n9")                          # the negated fact is unchanged
    for nid in m.node_ids - {"n1"}:
        assert child.node(nid) == m.node(nid)
    assert child.node("n1").model_copy(update={"attrs": m.node("n1").attrs}) == m.node("n1")


def test_edge_window_deletion_keeps_the_edge(ctx, fake_m1):
    c = with_(ctx, cohort=cohort(("n2->n3", "window", "relaxable")))
    (mv,) = attribute_deletion(fake_m1, c).moves
    e0, e1 = fake_m1.edge("n2", "n3"), mv.child.edge("n2", "n3")
    assert e1 is not None and e1.window is None and e1.model_copy(update={"window": e0.window}) == e0
    assert mv.child.nodes == fake_m1.nodes


def test_cohort_rejects_duplicates():
    with pytest.raises(ValueError):
        cohort(("n1", "value", "required"), ("n1", "value", "relaxable"))


# --- independent verification -------------------------------------------------------------------------------

def _forged(m, child, field="value"):
    return Move(child, ChangeRecord("attribute_deletion", "n3", field, None, None, {}, rule_id="attr.delete.value"))


def test_independent_checker_rejects_a_narrowing_move(ctx, fake_m1):
    """A move labelled as a deletion that in fact narrows the value is refused by check_order."""
    narrower = fake_m1.replace_node(fake_m1.node("n3").model_copy(update={"value": Interval.point(39, "%")}))
    with pytest.raises(GeneralizationOrderError):
        _accept(fake_m1, _forged(fake_m1, narrower), ctx)


def test_guard_rejects_a_move_touching_a_negated_fact(ctx, fake_m1):
    m = with_absent(fake_m1)
    changed = m.replace_node(m.node("n9").model_copy(update={"code": m.node("n3").code}))
    with pytest.raises(PolicyViolation, match="absent_node_changed"):
        _accept(m, _forged(m, changed), ctx)


def test_guard_rejects_a_move_changing_context(ctx, fake_m1):
    changed = fake_m1.replace_edge(fake_m1.edge("n2", "n4").model_copy(update={"bpn_score": 0.1}))
    with pytest.raises(PolicyViolation, match="context_edge_changed"):
        _accept(fake_m1, _forged(fake_m1, changed), ctx)
