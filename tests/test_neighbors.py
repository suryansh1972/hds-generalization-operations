import pytest

import semgen.lattice as L
from semgen.canonical import motif_hash
from semgen.lattice import GeneralizationOrderError, PolicyViolation, guard, neighbors


def test_unique_children_and_parent_excluded(ctx, fake_m1):
    ns, _ = neighbors(fake_m1, ctx)
    hs = [n.child_hash for n in ns]; assert len(hs) == len(set(hs)) and motif_hash(fake_m1) not in hs


def test_same_child_from_two_operators_keeps_both(ctx, fake_m1, monkeypatch):
    from semgen.operators.base import ChangeRecord, Move, OperatorResult
    child = fake_m1.replace_node(fake_m1.node("n3").model_copy(update={"value": None}))
    def op(name): return lambda m, c: OperatorResult([Move(child, ChangeRecord(name, "n3", "value", None, None, {}))], [])
    monkeypatch.setattr(L, "ALL_OPERATORS", [op("first"), op("second")])
    (n,), _ = neighbors(fake_m1, ctx)
    assert [c.op for c in n.changes] == ["first", "second"]


def test_order_failure_stops_loudly(ctx, fake_m1, monkeypatch):
    monkeypatch.setattr(L, "check_order", lambda s, g, c: L.OrderResult(False, "forced", "n1"))
    with pytest.raises(GeneralizationOrderError, match="forced"): neighbors(fake_m1, ctx)


def test_guard_rejects_touching_absent(ctx, fake_m2):
    child = fake_m2.without({"n2"}, {("P", "n2")})
    with pytest.raises(PolicyViolation): guard(fake_m2, child, None, ctx)


def test_blocked_collected(ctx, fake_m1):
    _, blocked = neighbors(fake_m1, ctx)
    assert {("concept_lift", "n3", "carries_value")} <= {(b.op, b.target, b.reason) for b in blocked}


def test_guard_rejects_floor_escape(ctx, fake_m1):
    from semgen.operators.base import ChangeRecord
    from tests.conftest import BRCA, NEO_BREAST
    child = fake_m1.replace_node(fake_m1.node("n1").model_copy(update={"code": NEO_BREAST}))
    with pytest.raises(PolicyViolation, match="floor_violation"):
        guard(fake_m1, child, ChangeRecord("concept_lift", "n1", "code", BRCA, NEO_BREAST, {}), ctx)


def test_guard_rejects_inactive_target(fake_h, ctx):
    from semgen.floors import PhecodeFloorPolicy
    from semgen.icd10map import Icd10Map
    from semgen.operators.base import ChangeRecord, GenContext
    from semgen.phecodex import PhecodeX
    from tests.conftest import RA, RA_OLD_PARENT, one_node_motif
    floors = PhecodeFloorPolicy(fake_h, Icd10Map.from_maps({RA: {"E14"}}),
                                PhecodeX.from_maps({"E14": {"EM_202"}}, {}), "first_decimal")
    lctx = GenContext(fake_h, ctx.config, floors)
    m = one_node_motif(RA)
    child = m.replace_node(m.node("n1").model_copy(update={"code": RA_OLD_PARENT}))
    with pytest.raises(PolicyViolation, match="inactive_target"):
        guard(m, child, ChangeRecord("concept_lift", "n1", "code", RA, RA_OLD_PARENT, {}), lctx)


def test_guard_rejects_missing_anchor(ctx, fake_m1):
    child = fake_m1.without({"n1"}, {("P", "n1")})
    with pytest.raises(PolicyViolation, match="protected_node_removed"): guard(fake_m1, child, None, ctx)


def test_guard_rejects_changed_context_edge(ctx, fake_m1):
    e = fake_m1.edge("n2", "n4")
    for upd in ({"bpn_score": 0.5}, {"rel": "associated_with"}):
        child = fake_m1.replace_edge(e.model_copy(update=upd))
        with pytest.raises(PolicyViolation, match="context_edge_changed"): guard(fake_m1, child, None, ctx)


def test_guard_allows_removed_context_edge(ctx, fake_m1):
    child = fake_m1.without({"n4", "n5"}, {("n2", "n4"), ("n4", "n5")})
    guard(fake_m1, child, None, ctx)


def test_guard_rejects_changed_absent_edge(ctx, fake_m2):
    e = fake_m2.edge("P", "n2")
    child = fake_m2.replace_edge(e.model_copy(update={"rel": "associated_with"}))
    with pytest.raises(PolicyViolation, match="absent_edge_changed"): guard(fake_m2, child, None, ctx)


def test_real_operator_moves_pass_on_fakes(ctx, fake_m1, fake_m2):
    for m in (fake_m1, fake_m2):
        ns, _ = neighbors(m, ctx)
        assert ns


def test_policy_violation_propagates(ctx, fake_m1, monkeypatch):
    from semgen.operators.base import ChangeRecord, Move, OperatorResult
    child = fake_m1.without({"n1"}, {("P", "n1")})
    op = lambda m, c: OperatorResult([Move(child, ChangeRecord("bad", "n1", "node", None, None, {}))], [])
    monkeypatch.setattr(L, "ALL_OPERATORS", [op])
    with pytest.raises(PolicyViolation): neighbors(fake_m1, ctx)


def test_neighbors_deterministic(ctx, fake_m1):
    a, _ = neighbors(fake_m1, ctx)
    b, _ = neighbors(fake_m1, ctx)
    assert [(n.child_hash, n.changes) for n in a] == [(n.child_hash, n.changes) for n in b]


def test_neighbors_contains_mal_thorax_lift(ctx, fake_m1):
    from tests.conftest import MAL_THORAX
    ns, _ = neighbors(fake_m1, ctx)
    assert any(c.op == "concept_lift" and c.after == MAL_THORAX for n in ns for c in n.changes)
