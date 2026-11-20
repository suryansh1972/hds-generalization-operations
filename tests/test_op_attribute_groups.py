"""A3 SNOMED CT semantic grouping (design §7.3), A1 evidence, and the removal of A2 panel grouping."""
import dataclasses
import importlib

import pytest

import semgen.operators as ops
from semgen.lattice import PolicyViolation, guard
from semgen.lattice.moves import _accept
from semgen.model import PATIENT_ID, Edge, Grouping, Interval, Motif, Node, TestIdentity
from semgen.operators.attribute_aggregation import attribute_aggregation
from semgen.operators.base import GenContext
from semgen.order import check_group_merge, check_order, is_group_merge, verify_containment
from semgen.snomed import Hierarchy
from tests.support.fake_snomed import (
    BRCA,
    DISEASE,
    DM,
    FAKE_FSN,
    FAKE_ISA,
    FIND,
    MAL_THORAX,
    NEO_BREAST,
    RA_OLD_PARENT,
    T1DM,
    T2DM,
    fake_concept_model,
    fake_lift,
)
from tests.support.matcher import matches
from tests.support.ucum import test_ucum

SYS = "urn:test:catalogue"
# Test-only concepts on top of the fake hierarchy (the shared fake hierarchy is not changed: golden runs use it).
X2, X3, X4 = "TEST-X2", "TEST-X3", "TEST-X4"


@pytest.fixture
def ext(ctx) -> GenContext:
    """``X2`` IS-A NEO_BREAST and MAL_THORAX (like BRCA); ``X3`` IS-A Clinical finding (a top-level concept);
    ``X4`` IS-A DM with no definition in the concept model (lift steps from it are unknown)."""
    isa = {**FAKE_ISA, X2: {NEO_BREAST, MAL_THORAX}, X3: {FIND}, X4: {DM}}
    fsn = {**FAKE_FSN, X2: "Test breast and thorax disorder (disorder)", X3: "Test finding (disorder)",
           X4: "Test undefined diabetes (disorder)"}
    active = (set(isa) | {p for ps in isa.values() for p in ps}) - {RA_OLD_PARENT}
    h = Hierarchy.from_maps(isa, fsn, active)
    return GenContext(h, ctx.config, fake_lift(h, fake_concept_model((X2, X3))))


def tid(code):
    return TestIdentity(system=SYS, code=code, method="m", specimen="s")


def motif(facts, anchor_code=DM):
    """P, an anchor disorder, and one P-attached fact per (id, type, code, value, test)."""
    nodes = [Node(id=PATIENT_ID, type="Patient", role="patient"),
             Node(id="a", type="Disorder", role="anchor", code=anchor_code)]
    edges = [Edge(s=PATIENT_ID, t="a", rel="has_condition", prov="asserted")]
    for i, t, c, v, test in facts:
        nodes.append(Node(id=i, type=t, role="modifier", code=c, value=v, test=test))
        edges.append(Edge(s=PATIENT_ID, t=i, rel="has_fact", prov="asserted"))
    return Motif(motif_id="G", anchor="a", nodes=tuple(nodes), edges=tuple(edges))


def dx(*codes):
    return [(f"d{i}", "Disorder", c, None, None) for i, c in enumerate(codes, 1)]


def by_rule(res, rule):
    return [m for m in res.moves if m.change.rule_id == rule]


def reasons(res):
    return {(b.target, b.reason) for b in res.blocked}


ONTOLOGY = "attr.aggregate.ontology"


# --- A2 is gone -----------------------------------------------------------------------------------------------

def test_a2_is_not_registered_exposed_or_executable(ctx):
    # the module itself (``import ... as`` would bind the re-exported function of the same name)
    agg = importlib.import_module("semgen.operators.attribute_aggregation")
    assert hasattr(agg, "repeated_observations") and hasattr(agg, "ontology_groups")   # not vacuous
    assert not hasattr(agg, "panel_groups") and not hasattr(agg, "_a2") and not hasattr(agg, "PANEL_RULE")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("semgen.groups")
    assert not any(f.name == "panels" for f in dataclasses.fields(GenContext))
    assert "panel_sources" not in type(ctx.config).model_fields
    with pytest.raises(Exception):
        Grouping(kind="panel", system=SYS, code="PNL", version="v1", source="s")
    labs = [(f"x{i}", "Observable", f"c{i}", Interval.point(i, "u"), tid(f"t{i}")) for i in (1, 2)]
    res = attribute_aggregation(motif(labs), ctx)
    assert res.moves == [] and not any("panel" in b.reason for b in res.blocked)
    assert ops.ALL_OPERATORS[-1] is attribute_aggregation


# --- A3 -------------------------------------------------------------------------------------------------------

def test_a3_groups_under_the_unique_lowest_common_ancestor(ctx):
    m = motif(dx(T1DM, T2DM), anchor_code=T2DM)
    (mv,) = by_rule(attribute_aggregation(m, ctx), ONTOLOGY)
    g = mv.child.node("d1")
    assert g.grouping.kind == "ontology" and g.grouping.code == DM and g.code is None
    assert mv.change.meaning == "kept" and mv.change.evidence["paths"] == {"d1": [T1DM, DM], "d2": [T2DM, DM]}
    assert is_group_merge(m, mv.child) and check_group_merge(m, mv.child, ctx).ok and check_order(m, mv.child, ctx).ok
    _accept(m, mv, ctx)


def test_a3_preserves_every_original_concept(ctx):
    m = motif(dx(T1DM, T2DM), anchor_code=T2DM)
    (mv,) = by_rule(attribute_aggregation(m, ctx), ONTOLOGY)
    g = mv.child.node("d1")
    assert g.members == (m.node("d1"), m.node("d2"))   # verbatim, original codes kept
    assert [x.code for x in g.members] == [T1DM, T2DM] and "d2" not in mv.child.node_ids


def test_a3_summary_never_decides_matching(ctx):
    m = motif(dx(T1DM, T2DM), anchor_code=T2DM)
    (mv,) = by_rule(attribute_aggregation(m, ctx), ONTOLOGY)
    h = ctx.hierarchy
    patients = [motif(dx(*cs), anchor_code=T2DM) for cs in ((T1DM, T2DM), (DM,), (T1DM,), (DM, DM), (T2DM, T1DM))]
    for p in patients:
        assert matches(m, p, h) == matches(mv.child, p, h)
    assert not matches(mv.child, patients[1], h)   # a DM-coded fact alone matches neither member


def test_a3_multiple_incomparable_ancestors_block(ext):
    """X2 and BRCA share two incomparable minimal ancestors (NEO_BREAST, MAL_THORAX)."""
    res = attribute_aggregation(motif(dx(X2, BRCA)), ext)
    assert by_rule(res, ONTOLOGY) == []
    b = next(b for b in res.blocked if b.reason == "multiple_minimal_ancestors")
    assert b.target == "d1+d2" and b.detail["ancestors"] == sorted([NEO_BREAST, MAL_THORAX])


def test_a3_ancestor_beyond_the_lift_boundary_blocks(ext):
    """The lowest common ancestor of X3 and T1DM is Clinical finding, a top-level concept lift rejects."""
    res = attribute_aggregation(motif(dx(X3, T1DM)), ext)
    assert by_rule(res, ONTOLOGY) == []
    b = next(b for b in res.blocked if b.target == "d1+d2")
    assert b.reason == "lcs_outside_floor" and b.detail["step"][1] == FIND and b.detail["rule"] == "hierarchy"


def test_a3_unknown_ontology_evidence_blocks(ext):
    """X4 has no definition in the concept model: its step to DM is unknown, so nothing is grouped."""
    res = attribute_aggregation(motif(dx(X4, T1DM)), ext)
    assert by_rule(res, ONTOLOGY) == []
    b = next(b for b in res.blocked if b.target == "d1+d2")
    assert b.reason == "ontology_evidence_unknown" and b.detail["member"] == "d1" and b.detail["step"][:2] == [X4, DM]


def test_a3_inactive_concept_is_unknown_not_skipped(ctx):
    res = attribute_aggregation(motif(dx(RA_OLD_PARENT, T1DM)), ctx)
    assert by_rule(res, ONTOLOGY) == []
    assert ("d1", "ontology_evidence_unknown") in reasons(res)


def test_a3_needs_two_distinct_codes(ctx):
    assert by_rule(attribute_aggregation(motif(dx(T1DM, T1DM), anchor_code=T2DM), ctx), ONTOLOGY) == []


def test_a3_never_groups_the_anchor_or_context(ctx):
    assert by_rule(attribute_aggregation(motif(dx(T1DM), anchor_code=T2DM), ctx), ONTOLOGY) == []


# --- independent verification of groupings ---------------------------------------------------------------------

def _a3_move(ctx):
    m = motif(dx(T1DM, T2DM), anchor_code=T2DM)
    (mv,) = by_rule(attribute_aggregation(m, ctx), ONTOLOGY)
    return m, mv


@pytest.mark.parametrize("code, rule", [(DISEASE, "group_summary_not_unique_lca"),
                                        (T1DM, "group_summary_not_unique_lca")])
def test_guard_rejects_a_forged_summary_concept(ctx, code, rule):
    m, mv = _a3_move(ctx)
    g = mv.child.node("d1")
    forged = mv.child.replace_node(g.model_copy(update={"grouping": g.grouping.model_copy(update={"code": code})}))
    with pytest.raises(PolicyViolation, match=rule):
        guard(m, forged, mv.change, ctx)


def test_guard_verifies_the_summary_with_the_independent_lift_verifier(ctx, monkeypatch):
    import semgen.lattice.policy as lattice_guard
    m, mv = _a3_move(ctx)
    monkeypatch.setattr(lattice_guard, "verify_transition", lambda *a, **k: ["refused_by_verifier"])
    with pytest.raises(PolicyViolation, match="group_summary_outside_boundary"):
        guard(m, mv.child, mv.change, ctx)


def test_forged_group_member_changed_is_refused(ctx):
    m, mv = _a3_move(ctx)
    g = mv.child.node("d1")
    forged_member = g.members[1].model_copy(update={"code": DM})
    forged = mv.child.replace_node(g.model_copy(update={"members": (g.members[0], forged_member)}))
    assert not check_group_merge(m, forged, ctx).ok


def test_grouped_nodes_only_compare_to_identical_groups(ctx):
    m, mv = _a3_move(ctx)
    ident = {n: n for n in mv.child.node_ids}
    assert verify_containment(mv.child, mv.child, ident, ctx).ok
    broad = m.without({"d2"}, set())
    r = verify_containment(mv.child, broad, {n: n for n in broad.node_ids}, ctx)
    assert not r.ok and r.reason == "grouped_node_not_compared"


# --- A1 evidence ----------------------------------------------------------------------------------------------

def test_a1_records_unit_validation_and_identity_status(ctx):
    a1 = [(f"o{i}", "Observable", "c1", Interval.point(v, "mEq/L"), tid("t1")) for i, v in enumerate((1, 2))]
    c = dataclasses.replace(ctx, ucum=test_ucum("mEq", "L"))
    (mv,) = by_rule(attribute_aggregation(motif(a1), c), "attr.aggregate.repeated_observation")
    assert mv.change.evidence["unit_validation"] == {"unit": "mEq/L", "status": "valid", "version": "test",
                                                     "sha256": "0" * 64}
    assert mv.change.evidence["canonical_identity"] == {"system": SYS, "status": "terminology_unavailable"}



def test_a3_classification_follows_the_lift_rule():
    """Boundary (hierarchy rule / TOP_REASONS), semantic rejection (any other rejecting rule) and missing evidence
    stay distinct; the classification reads only the lift's own outcome."""
    from semgen.lift import REJECT_REASONS, UNKNOWN_REASONS
    from semgen.operators.attribute_aggregation import _classify as c
    for r in ("hierarchy_root", "top_level_concept", "top_level_hierarchy_lost"):
        assert c(r, "hierarchy") == "lcs_outside_floor"
    assert c("no_parent", None) == "lcs_outside_floor"
    for r, rule in (("semantic_tag_changed", "semantic_tag"), ("mrcm_domain_lost", "mrcm_domain"),
                    ("mrcm_domain_concept", "mrcm_domain"), ("defining_attribute_dropped", "defining_relationships"),
                    ("role_group_dropped", "defining_relationships"), ("not_inferred_parent", "concept")):
        assert c(r, rule) == "lcs_semantic_rejection", r
    for r in sorted(UNKNOWN_REASONS) + ["inactive_concept", "inactive_parent", "not_an_ancestor", "outside_floor"]:
        assert c(r, None) == "ontology_evidence_unknown", r
    assert {c(r, None) for r in REJECT_REASONS} <= {"lcs_outside_floor", "lcs_semantic_rejection",
                                                    "ontology_evidence_unknown"}


def test_a3_semantic_rejection_is_not_reported_as_boundary(ctx):
    """A step concept lift rejects for a semantic reason (here: a semantic tag change) is lcs_semantic_rejection."""
    isa = {**FAKE_ISA, X2: {DM}}
    fsn = {**FAKE_FSN, X2: "Test diabetes finding (finding)"}   # tag differs from its parent's (disorder)
    active = (set(isa) | {p for ps in isa.values() for p in ps}) - {RA_OLD_PARENT}
    h = Hierarchy.from_maps(isa, fsn, active)
    c = GenContext(h, ctx.config, fake_lift(h, fake_concept_model((X2,))))
    res = attribute_aggregation(motif(dx(X2, T1DM)), c)
    assert by_rule(res, ONTOLOGY) == []
    b = next(b for b in res.blocked if b.target == "d1+d2")
    assert (b.reason, b.detail["step"], b.detail["rule"]) == ("lcs_semantic_rejection",
                                                              [X2, DM, "semantic_tag_changed"], "semantic_tag")
