import json

import pytest

from semgen.model import Interval
from semgen.operators.concept_lift import concept_lift
from tests.conftest import *


def reasons(r): return {(b.target, b.reason) for b in r.blocked}


def blk(r, target, reason): return [b for b in r.blocked if b.target == target and b.reason == reason]


def test_breast_cancer_lifts_to_both_parents(ctx, fake_m1):
    """Rewritten (Task 1): was MAL_THORAX only, NEO_BREAST outside_floor, PhecodeX anchors in the evidence; now
    both disorder-tagged parents are allowed under snomed_boundary, with the boundary evidence."""
    r = concept_lift(fake_m1, ctx)
    assert _lifts(r, "n1") == {MAL_THORAX, NEO_BREAST} and not blk(r, "n1", "outside_floor")
    mv = next(m for m in r.moves if m.change.target == "n1" and m.change.after == MAL_THORAX)
    assert mv.change.before == BRCA
    assert mv.change.evidence["isa"] == [BRCA, MAL_THORAX]
    assert mv.change.evidence["transition"]["decision"] == "accepted"
    assert mv.change.evidence["fingerprint"] == ctx.floors.fingerprint


def test_drug_with_dependent_dose_is_blocked(ctx, fake_m1):
    r = concept_lift(fake_m1, ctx)
    assert ("n2", "concept_dependent_attr") in reasons(r) and not any(m.change.target == "n2" for m in r.moves)


def test_drug_lifts_within_its_tag(ctx, fake_m2):
    """Rewritten (Task 1): was metformin unmapped (no ICD-10 target); now it lifts to BIGUANIDE (same tag)."""
    r = concept_lift(fake_m2, ctx)
    assert _lifts(r, "n3") == {BIGUANIDE} and not blk(r, "n3", "unmapped")
    assert not any(b.reason == "no_floor" for b in r.blocked)


def _retyped(code, typ):
    m = one_node_motif(code)
    return m.replace_node(m.node("n1").model_copy(update={"type": typ}))


def test_finding_typed_node_lifts_like_disorder(ctx):
    """Rewritten (Task 1): was MAL_THORAX only with NEO_BREAST outside_floor; now both parents, like the Disorder."""
    r = concept_lift(_retyped(BRCA, "Finding"), ctx)
    assert _lifts(r, "n1") == {MAL_THORAX, NEO_BREAST} == _lifts(concept_lift(one_node_motif(BRCA), ctx), "n1")
    assert not any(b.reason == "no_floor" for b in r.blocked)


def test_substance_typed_node_lifts_when_floor_allows(ctx):
    """Rewritten (Task 1): was a hand-built PhecodeX policy mapping MET and BIGUANIDE; now the shared
    SNOMED-only ctx, which allows MET -> BIGUANIDE (same substance tag)."""
    r = concept_lift(_retyped(MET, "Substance"), ctx)
    assert _lifts(r, "n1") == {BIGUANIDE}


def test_node_with_value_is_never_lifted(ctx, fake_m1):
    assert ("n3", "carries_value") in reasons(concept_lift(fake_m1, ctx))


def test_absent_context_patient_never_touched(ctx, fake_m1, fake_m2):
    assert "n2" not in {m.change.target for m in concept_lift(fake_m2, ctx).moves}   # absent T1DM
    assert not {m.change.target for m in concept_lift(fake_m1, ctx).moves} & {"P", "n4", "n5"}


def test_t2dm_lifts_to_dm(ctx, fake_m2):
    """Rewritten (Task 1): was T2DM -> DM outside_floor (blocked by T1DM's PhecodeX anchor); now allowed."""
    r = concept_lift(fake_m2, ctx)
    assert _lifts(r, "n1") == {DM} and not blk(r, "n1", "outside_floor")


def test_inactive_parent_blocked_active_parent_allowed(ctx):
    """Rewritten (Task 1): was no moves with inactive_parent + unmapped; now inactive_parent is still blocked and
    the active parent DISEASE is allowed."""
    r = concept_lift(one_node_motif(RA), ctx)
    assert _lifts(r, "n1") == {DISEASE} and reasons(r) == {("n1", "inactive_parent")}
    d = blk(r, "n1", "inactive_parent")[0].detail
    assert d["code"] == RA and d["parent"] == RA_OLD_PARENT and d["decision"] == "rejected"


def test_mapped_child_never_moves_to_inactive_parent(ctx):
    """Rewritten (Task 1): was a hand-built PhecodeX policy; now the shared SNOMED-only policy, which also fails
    closed on the inactive parent."""
    d = ctx.floors.check_lift(RA, RA_OLD_PARENT)       # policy fails closed on inactive parents
    assert not d.ok and d.reason == "inactive_parent"
    r = concept_lift(one_node_motif(RA), ctx)
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
    """Rewritten (Task 1): was the first n1 move (MAL_THORAX, the only PhecodeX-allowed parent); now the
    MAL_THORAX move is selected explicitly, since NEO_BREAST is allowed too and sorts first."""
    from semgen.canonical import canonical_json
    mv = next(m for m in concept_lift(fake_m1, ctx).moves if m.change.target == "n1" and m.change.after == MAL_THORAX)
    restored = mv.child.replace_node(mv.child.node("n1").model_copy(update={"code": BRCA}))
    assert canonical_json(restored) == canonical_json(fake_m1)
    assert mv.child.node("n1").code == MAL_THORAX


def test_records_round_trip_json_and_order_is_deterministic(ctx, fake_m1):
    """Rewritten (Task 1): was the NEO_BREAST outside_floor block checked; now the two allowed moves, in order."""
    r = concept_lift(fake_m1, ctx)
    for mv in r.moves:
        json.dumps(mv.change.to_json())
    for b in r.blocked:
        json.dumps(b.to_json())
    again = concept_lift(fake_m1, ctx)
    assert [b.to_json() for b in r.blocked] == [b.to_json() for b in again.blocked]
    assert [m.change.to_json() for m in r.moves] == [m.change.to_json() for m in again.moves]
    assert [(m.change.target, m.change.before, m.change.after) for m in r.moves] == [
        ("n1", BRCA, NEO_BREAST), ("n1", BRCA, MAL_THORAX)]   # parents in sorted id order
    d = next(b for b in r.blocked if b.reason == "concept_dependent_attr")
    assert d.detail["attrs"] == ["cumulative_dose"]


def _m(real_motifs, mid): return next(m for m in real_motifs if m.motif_id == mid)


def _lifts(r, node): return {mv.change.after for mv in r.moves if mv.change.target == node}


@pytest.mark.snomed
def test_real_m1_lifts(real_ctx, real_motifs):
    """Rewritten (Task 1): was no lift (both parents outside_floor); now both parents, as in golden real_lift/M1."""
    r = concept_lift(_m(real_motifs, "M1"), real_ctx)
    assert _lifts(r, "n1") == {"126926005", "188361007"} and not blk(r, "n1", "outside_floor")


@pytest.mark.snomed
def test_real_m3_lift(real_ctx, real_motifs):
    assert _lifts(concept_lift(_m(real_motifs, "M3"), real_ctx), "n1") == {"254637007"}


@pytest.mark.snomed
def test_real_m4_ra_does_not_lift(real_ctx, real_motifs):
    """Rewritten (SNOMED-only lift): both RA parents drop a defining attribute, so neither is a lift."""
    r = concept_lift(_m(real_motifs, "M4"), real_ctx)
    assert _lifts(r, "n1") == set() and len(blk(r, "n1", "defining_attribute_dropped")) == 2
    assert not any(b.reason == "no_floor" for b in r.blocked)


@pytest.mark.snomed
def test_real_m2_dm_lifts(real_ctx, real_motifs):
    """Rewritten (Task 1): was T2DM -> DM outside_floor (blocking descendant 105401000119101); now allowed."""
    r = concept_lift(_m(real_motifs, "M2"), real_ctx)
    assert _lifts(r, "n1") == {DM} and not blk(r, "n1", "outside_floor")


def test_unknown_and_parentless_codes_are_blocked(ctx):
    unknown = concept_lift(one_node_motif("999999999"), ctx)
    (b,) = blk(unknown, "n1", "unknown_concept")
    assert b.detail == {"code": "999999999"} and not unknown.moves
    root = concept_lift(one_node_motif(ROOT), ctx)
    (b,) = blk(root, "n1", "no_parent")
    assert b.detail == {"code": ROOT} and not root.moves


@pytest.mark.snomed
def test_real_no_no_floor_anywhere(real_ctx, real_motifs):
    assert not any(b.reason == "no_floor" for m in real_motifs for b in concept_lift(m, real_ctx).blocked)
