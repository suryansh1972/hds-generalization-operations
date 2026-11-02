import json

import pytest

from semgen.operators.concept_lift import concept_lift
from semgen.model import Interval
from tests.conftest import *


def reasons(r): return {(b.target, b.reason) for b in r.blocked}


def blk(r, target, reason): return [b for b in r.blocked if b.target == target and b.reason == reason]


def test_breast_cancer_lifts_only_inside_floor(ctx, fake_m1):
    r = concept_lift(fake_m1, ctx)
    lifted = {(mv.change.target, mv.change.after) for mv in r.moves}
    assert ("n1", MAL_THORAX) in lifted and ("n1", NEO_BREAST) not in lifted
    (b,) = blk(r, "n1", "outside_floor")
    assert b.detail["parent"] == NEO_BREAST and b.detail["blocking_descendant"] == NEO_BREAST
    assert _lifts(r, "n1") == {MAL_THORAX}
    mv = next(m for m in r.moves if m.change.target == "n1")
    assert mv.change.before == BRCA
    assert mv.change.evidence["anchors"] == ["CA_105", "CA_130"]
    assert mv.change.evidence["phecode_level"] == "first_decimal"
    assert mv.change.evidence["isa"] == [BRCA, MAL_THORAX]


def test_drug_with_dependent_dose_is_blocked(ctx, fake_m1):
    r = concept_lift(fake_m1, ctx)
    assert ("n2", "concept_dependent_attr") in reasons(r) and not any(m.change.target == "n2" for m in r.moves)


def test_drug_not_in_icd_map_is_unmapped(ctx, fake_m2):
    r = concept_lift(fake_m2, ctx)
    (b,) = blk(r, "n3", "unmapped")                                          # metformin: Substance, no ICD-10 target
    assert b.detail == {"code": MET} and not any(m.change.target == "n3" for m in r.moves)
    assert not any(b.reason == "no_floor" for b in r.blocked)


def _retyped(code, typ):
    m = one_node_motif(code)
    return m.replace_node(m.node("n1").model_copy(update={"type": typ}))


def test_finding_typed_node_lifts_like_disorder(ctx):
    r = concept_lift(_retyped(BRCA, "Finding"), ctx)
    assert _lifts(r, "n1") == {MAL_THORAX}
    (b,) = blk(r, "n1", "outside_floor")
    assert b.detail["parent"] == NEO_BREAST
    assert not any(b.reason == "no_floor" for b in r.blocked)


def test_substance_typed_node_lifts_when_floor_allows(fake_h, ctx):
    from semgen.floors import PhecodeFloorPolicy
    from semgen.icd10map import Icd10Map
    from semgen.operators.base import GenContext
    from semgen.phecodex import PhecodeX
    pol = PhecodeFloorPolicy(fake_h, Icd10Map.from_maps({MET: {"X1"}, BIGUANIDE: {"X1"}}),
                             PhecodeX.from_maps({"X1": {"DR_1"}}, {}), "first_decimal")
    r = concept_lift(_retyped(MET, "Substance"), GenContext(fake_h, ctx.config, pol))
    assert _lifts(r, "n1") == {BIGUANIDE}


def test_node_with_value_is_never_lifted(ctx, fake_m1):
    assert ("n3", "carries_value") in reasons(concept_lift(fake_m1, ctx))


def test_absent_context_patient_never_touched(ctx, fake_m1, fake_m2):
    assert "n2" not in {m.change.target for m in concept_lift(fake_m2, ctx).moves}   # absent T1DM
    assert not {m.change.target for m in concept_lift(fake_m1, ctx).moves} & {"P", "n4", "n5"}


def test_t2dm_strictly_blocked_at_dm(ctx, fake_m2):
    r = concept_lift(fake_m2, ctx)
    assert not any(m.change.target == "n1" for m in r.moves)
    (b,) = blk(r, "n1", "outside_floor")
    assert b.detail["parent"] == DM and b.detail["blocking_descendant"] == T1DM
    assert b.detail["anchor"] == "EM_202.2"


def test_unmapped_and_inactive_parent(ctx):
    r = concept_lift(one_node_motif(RA), ctx)
    assert r.moves == [] and reasons(r) == {("n1", "inactive_parent"), ("n1", "unmapped")}
    assert blk(r, "n1", "inactive_parent")[0].detail == {"code": RA, "parent": RA_OLD_PARENT}


def test_mapped_child_never_moves_to_inactive_parent(fake_h, ctx):
    from semgen.floors import PhecodeFloorPolicy
    from semgen.icd10map import Icd10Map
    from semgen.operators.base import GenContext
    from semgen.phecodex import PhecodeX
    pol = PhecodeFloorPolicy(fake_h, Icd10Map.from_maps({RA: {"E14"}}),
                             PhecodeX.from_maps({"E14": {"EM_202"}}, {}), "first_decimal")
    d = pol.check_lift(RA, RA_OLD_PARENT)             # policy fails closed on inactive parents
    assert not d.ok and d.reason == "inactive_parent"
    r = concept_lift(one_node_motif(RA), GenContext(fake_h, ctx.config, pol))
    assert RA_OLD_PARENT not in _lifts(r, "n1")
    (b,) = blk(r, "n1", "inactive_parent")
    assert b.detail["parent"] == RA_OLD_PARENT


def test_no_at_floor_reason(ctx, fake_m1, fake_m2):
    assert not any(b.reason == "at_floor" for m in (fake_m1, fake_m2) for b in concept_lift(m, ctx).blocked)


def test_unflagged_attr_blocks(ctx, fake_m2):
    n = fake_m2.node("n1"); m = fake_m2.replace_node(n.model_copy(update={"attrs": {"mystery": Interval.point(1, "x")}}))
    assert ("n1", "concept_dependent_attr") in reasons(concept_lift(m, ctx))


def test_input_not_mutated(ctx, fake_m1):
    from semgen.canonical import canonical_json
    before = canonical_json(fake_m1); concept_lift(fake_m1, ctx); assert canonical_json(fake_m1) == before


def test_child_differs_only_in_code_and_label(ctx, fake_m1):
    from semgen.canonical import canonical_json
    mv = next(m for m in concept_lift(fake_m1, ctx).moves if m.change.target == "n1")
    restored = mv.child.replace_node(mv.child.node("n1").model_copy(update={"code": BRCA}))
    assert canonical_json(restored) == canonical_json(fake_m1)
    assert mv.child.node("n1").code == MAL_THORAX


def test_records_round_trip_json_and_order_is_deterministic(ctx, fake_m1):
    r = concept_lift(fake_m1, ctx)
    for mv in r.moves:
        json.dumps(mv.change.to_json())
    for b in r.blocked:
        json.dumps(b.to_json())
    again = concept_lift(fake_m1, ctx)
    assert [b.to_json() for b in r.blocked] == [b.to_json() for b in again.blocked]
    assert [m.change.to_json() for m in r.moves] == [m.change.to_json() for m in again.moves]
    b = next(b for b in r.blocked if b.reason == "outside_floor")
    assert b.detail["parent"] == NEO_BREAST and b.detail["code"] == BRCA
    d = next(b for b in r.blocked if b.reason == "concept_dependent_attr")
    assert d.detail["attrs"] == ["cumulative_dose"]


def _m(real_motifs, mid): return next(m for m in real_motifs if m.motif_id == mid)


def _lifts(r, node): return {mv.change.after for mv in r.moves if mv.change.target == node}


@pytest.mark.snomed
@pytest.mark.phecodex
def test_real_m1_no_lift(real_ctx, real_motifs):
    r = concept_lift(_m(real_motifs, "M1"), real_ctx)
    assert _lifts(r, "n1") == set()
    assert {b.detail["parent"] for b in blk(r, "n1", "outside_floor")} == {"126926005", "188361007"}


@pytest.mark.snomed
@pytest.mark.phecodex
def test_real_m3_lift(real_ctx, real_motifs):
    assert _lifts(concept_lift(_m(real_motifs, "M3"), real_ctx), "n1") == {"254637007"}


@pytest.mark.snomed
@pytest.mark.phecodex
def test_real_m4_ra_blocked(real_ctx, real_motifs):
    r = concept_lift(_m(real_motifs, "M4"), real_ctx)
    assert len(blk(r, "n1", "outside_floor")) == 2 and not any(b.reason == "no_floor" for b in r.blocked)


@pytest.mark.snomed
@pytest.mark.phecodex
def test_real_m2_dm_blocked(real_ctx, real_motifs):
    r = concept_lift(_m(real_motifs, "M2"), real_ctx)
    (b,) = blk(r, "n1", "outside_floor")
    assert b.detail["parent"] == DM and b.detail["blocking_descendant"] == "105401000119101"


def test_unknown_and_parentless_codes_are_blocked(ctx):
    unknown = concept_lift(one_node_motif("999999999"), ctx)
    (b,) = blk(unknown, "n1", "unknown_concept")
    assert b.detail == {"code": "999999999"} and not unknown.moves
    root = concept_lift(one_node_motif(ROOT), ctx)
    (b,) = blk(root, "n1", "no_parent")
    assert b.detail == {"code": ROOT} and not root.moves


@pytest.mark.snomed
@pytest.mark.phecodex
def test_real_no_no_floor_anywhere(real_ctx, real_motifs):
    assert not any(b.reason == "no_floor" for m in real_motifs for b in concept_lift(m, real_ctx).blocked)
