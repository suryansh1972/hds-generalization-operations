import json

import pytest

from semgen.operators.concept_lift import concept_lift
from semgen.model import Interval
from tests.conftest import *


def reasons(r): return {(b.target, b.reason) for b in r.blocked}


def test_breast_cancer_lifts_only_inside_floor(ctx, fake_m1):
    r = concept_lift(fake_m1, ctx)
    lifted = {(mv.change.target, mv.change.after) for mv in r.moves}
    assert ("n1", MAL_THORAX) in lifted and ("n1", NEO_BREAST) not in lifted
    assert ("n1", "outside_floor") in reasons(r)
    mv = next(m for m in r.moves if m.change.target == "n1")
    assert mv.change.before == BRCA and mv.change.evidence["floors"] == [MALIG]


def test_drug_with_dependent_dose_is_blocked(ctx, fake_m1):
    r = concept_lift(fake_m1, ctx)
    assert ("n2", "concept_dependent_attr") in reasons(r) and not any(m.change.target == "n2" for m in r.moves)


def test_drug_without_attrs_has_no_floor(ctx, fake_m2):
    assert ("n3", "no_floor") in reasons(concept_lift(fake_m2, ctx))        # metformin


def test_node_with_value_is_never_lifted(ctx, fake_m1):
    assert ("n3", "carries_value") in reasons(concept_lift(fake_m1, ctx))


def test_absent_context_patient_never_touched(ctx, fake_m1, fake_m2):
    assert "n2" not in {m.change.target for m in concept_lift(fake_m2, ctx).moves}   # absent T1DM
    assert not {m.change.target for m in concept_lift(fake_m1, ctx).moves} & {"P", "n4", "n5"}


def test_t2dm_lifts_to_dm_then_stops_at_floor(ctx, fake_m2):
    mv = next(m for m in concept_lift(fake_m2, ctx).moves if m.change.target == "n1"); assert mv.change.after == DM
    assert ("n1", "at_floor") in reasons(concept_lift(mv.child, ctx))


def test_lift_requires_every_applicable_floor(ctx):
    from semgen.snomed import Hierarchy
    from semgen.operators.base import GenContext
    h = Hierarchy.from_maps({"X": {"Y", DM}, "Y": {MALIG}, MALIG: {DISEASE}, DM: {DISEASE}, DISEASE: {ROOT}},
                            {}, {"X", "Y", MALIG, DM, DISEASE, ROOT})
    m = one_node_motif("X")                       # helper in conftest: P -has_condition-> n1(anchor, code)
    r = concept_lift(m, GenContext(hierarchy=h, config=ctx.config))
    assert r.moves == [] and ("n1", "outside_floor") in reasons(r)


def test_inactive_parent_skipped(ctx, fake_h):
    from semgen.operators.base import GenContext
    c = GenContext(hierarchy=fake_h, config=ctx.config.model_copy(update={"floors": (DISEASE,)}))
    r = concept_lift(one_node_motif(RA), c)
    assert [m.change.after for m in r.moves] == [DISEASE] and ("n1", "inactive_parent") in reasons(r)


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
    assert b.detail["parent"] == NEO_BREAST and b.detail["escaped_floors"] == [MALIG]
    d = next(b for b in r.blocked if b.reason == "concept_dependent_attr")
    assert d.detail["attrs"] == ["cumulative_dose"]


@pytest.mark.snomed
def test_real_m1_lift(real_ctx, real_motifs):
    m1 = next(m for m in real_motifs if m.motif_id == "M1")
    r = concept_lift(m1, real_ctx)
    assert [mv.change.after for mv in r.moves if mv.change.target == "n1"] == ["188361007"]
