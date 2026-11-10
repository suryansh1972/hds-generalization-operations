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
    with pytest.raises(PolicyViolation, match="absent_node_changed"): guard(fake_m2, child, None, ctx)


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


def _recode(m, nid, code):
    return m.replace_node(m.node(nid).model_copy(update={"code": code}))


def test_guard_ignores_mislabelled_change_record(ctx, fake_m1):
    from semgen.operators.base import ChangeRecord
    from tests.conftest import MAL_THORAX
    child = _recode(fake_m1, "n3", MAL_THORAX)   # an Observable code change labelled as something harmless
    # n3 is a clinical type carrying a value: rejected by the explicit valued-node rule (before direct-parent).
    with pytest.raises(PolicyViolation, match="lift_on_valued_node"):
        guard(fake_m1, child, ChangeRecord("attribute_removal", "n3", "attrs", None, None, {}), ctx)


def test_guard_rejects_code_change_on_non_clinical_type(ctx, fake_m1):
    n = fake_m1.node("n1").model_copy(update={"type": "Phenotype"})
    parent = fake_m1.replace_node(n)
    with pytest.raises(PolicyViolation, match="lift_type_not_allowed"):
        guard(parent, _recode(parent, "n1", "188361007"), None, ctx)


def test_guard_judges_non_disorder_clinical_lift_by_floor(ctx, fake_m1):
    from tests.conftest import NEO_BREAST, MAL_THORAX
    parent = fake_m1.replace_node(fake_m1.node("n1").model_copy(update={"type": "Finding"}))
    guard(parent, _recode(parent, "n1", MAL_THORAX), None, ctx)           # floor allows
    with pytest.raises(PolicyViolation, match="floor_violation"):
        guard(parent, _recode(parent, "n1", NEO_BREAST), None, ctx)       # floor rejects


def test_guard_rejects_two_level_jump(ctx, fake_m1):
    from tests.conftest import MALIG
    with pytest.raises(PolicyViolation, match="not_direct_parent"):
        guard(fake_m1, _recode(fake_m1, "n1", MALIG), None, ctx)


def test_guard_rejects_context_code_change(ctx, fake_m1):
    with pytest.raises(PolicyViolation, match="context_code_changed"):
        guard(fake_m1, _recode(fake_m1, "n4", "ENSG00000000001"), None, ctx)


def test_guard_rejects_added_absent_edge(ctx, fake_m2):
    from semgen.model import Edge
    child = fake_m2.model_copy(update={"edges": fake_m2.edges + (
        Edge(s="n1", t="n2", rel="associated_with", prov="asserted"),)})
    with pytest.raises(PolicyViolation, match="absent_edge_changed"): guard(fake_m2, child, None, ctx)


def test_guard_rejects_absent_edge_window_or_score_change(ctx, fake_m2):
    from semgen.model import Interval
    e = fake_m2.edge("P", "n2")
    for upd in ({"window": Interval(lo=0, hi=5, unit="d")}, {"bpn_score": 0.3}):
        child = fake_m2.replace_edge(e.model_copy(update=upd))
        with pytest.raises(PolicyViolation, match="absent_edge_changed"): guard(fake_m2, child, None, ctx)


def test_new_context_edge_passes_guard_but_order_rejects(ctx, fake_m1, monkeypatch):
    # The guard deliberately allows a NEW context edge: check_order rejects it as extra_edge.
    from semgen.model import Edge
    from semgen.operators.base import ChangeRecord, Move, OperatorResult
    child = fake_m1.model_copy(update={"edges": fake_m1.edges + (
        Edge(s="n1", t="n5", rel="associated_with", prov="context", bpn_score=0.5),)})
    guard(fake_m1, child, None, ctx)
    op = lambda m, c: OperatorResult([Move(child, ChangeRecord("bad", "n1", "edge", None, None, {}))], [])
    monkeypatch.setattr(L, "ALL_OPERATORS", [op])
    with pytest.raises(GeneralizationOrderError, match="extra_edge"): neighbors(fake_m1, ctx)


def test_every_real_operator_move_passes_guard(ctx, fake_m1, fake_m2):
    for m in (fake_m1, fake_m2):
        for op in L.ALL_OPERATORS:
            for mv in op(m, ctx).moves:
                guard(m, mv.child, mv.change, ctx)


def test_hash_collision_in_neighbors_detected(ctx, fake_m1, monkeypatch):
    monkeypatch.setattr(L, "motif_hash", lambda m: "c" * 16 if m is not fake_m1 else "p" * 16)
    with pytest.raises(GeneralizationOrderError, match="hash collision"): neighbors(fake_m1, ctx)


def test_hash_collision_in_enumerate_detected(ctx, fake_m1, monkeypatch):
    monkeypatch.setattr(L, "motif_hash", lambda m: "c" * 16)
    # every motif hashes alike, so the parent is skipped; use two roots' worth of children via a stub
    from semgen.lattice import Neighbor
    other = fake_m1.replace_node(fake_m1.node("n3").model_copy(update={"value": None}))
    monkeypatch.setattr(L, "neighbors", lambda m, c: ([Neighbor(other, "c" * 16, ())], []))
    with pytest.raises(GeneralizationOrderError, match="hash collision"): L.enumerate_lattice(fake_m1, ctx, 1)


def test_guard_rejects_code_change_on_valued_node(ctx, fake_m1):
    from tests.conftest import OBS
    with pytest.raises(PolicyViolation, match="lift_on_valued_node"):
        guard(fake_m1, _recode(fake_m1, "n3", OBS), None, ctx)           # LVEF (has value) -> its parent


def test_guard_rejects_code_change_on_dependent_attr_node(ctx, fake_m1):
    from tests.conftest import ANTHRA
    with pytest.raises(PolicyViolation, match="lift_on_dependent_attr"):
        guard(fake_m1, _recode(fake_m1, "n2", ANTHRA), None, ctx)        # DOX (cumulative_dose) -> its parent


def test_every_operator_move_passes_guard(ctx, fake_m1, fake_m2):
    from semgen.operators import ALL_OPERATORS
    n = 0
    for m in (fake_m1, fake_m2):
        for op in ALL_OPERATORS:
            for mv in op(m, ctx).moves:
                guard(m, mv.child, mv.change, ctx); n += 1
    assert n > 0


def test_guard_rejects_inactive_target_on_finding(fake_h, ctx):
    from semgen.floors import PhecodeFloorPolicy
    from semgen.icd10map import Icd10Map
    from semgen.operators.base import GenContext
    from semgen.phecodex import PhecodeX
    from tests.conftest import RA, RA_OLD_PARENT, one_node_motif
    floors = PhecodeFloorPolicy(fake_h, Icd10Map.from_maps({RA: {"E14"}}),
                                PhecodeX.from_maps({"E14": {"EM_202"}}, {}), "first_decimal")
    m = one_node_motif(RA)
    m = m.replace_node(m.node("n1").model_copy(update={"type": "Finding"}))
    with pytest.raises(PolicyViolation, match="inactive_target"):
        guard(m, _recode(m, "n1", RA_OLD_PARENT), None, GenContext(fake_h, ctx.config, floors))


def test_guard_rejects_dependent_attr_removal(ctx, fake_m1):
    n = fake_m1.node("n2")
    child = fake_m1.replace_node(n.model_copy(update={"attrs": {}}))
    with pytest.raises(PolicyViolation, match="dependent_attr_removed"):
        guard(fake_m1, child, None, ctx)
