"""Motif aggregation (spec §5): graph anti-unification of bundle parts, verified by the independent checker (§6).

Every generalization is also checked against the reference oracle: each consumed part's matches are matches of the
aggregate (on the inputs themselves as patients and on random patients).
"""
from __future__ import annotations

import dataclasses

from hypothesis import HealthCheck, find, given, settings
from hypothesis import strategies as st

from semgen.interfaces import OperatorSet
from semgen.lattice import enumerate_lattice
from semgen.model import Interval
from semgen.operators import default_operators
from semgen.operators.motif_aggregation import aggregate, generalize, motif_aggregation
from semgen.order import aggregate_part_id, check_bundle_order, decide_aggregation
from tests.support.fake_snomed import (
    CKD,
    DAUNO,
    DISEASE,
    DM,
    DOX,
    MAL_THORAX,
    MET,
    NEO_BREAST,
    RA,
    T1DM,
    T2DM,
)
from tests.support.matcher import matches, matches_bundle
from tests.test_op_motif_deletion import (
    bundle,
    drug,
    dx,
    dx_drug,
    motif,
    node_specs,
    patient_of,
    random_patients,
)

AGE = "age_at_dx"   # an attribute about the patient (concept-independent in the packaged definitions)


def age(lo, hi) -> dict:
    return {"attrs": {AGE: Interval.closed(lo, hi, "a")}}


def only(res):
    (mv,) = res.moves
    return mv


def aggregate_of(mv):
    return mv.child.part(mv.change.after).motif


def changes(mv, pid) -> list[list]:
    return mv.change.evidence["changes"][pid]


def covers(g, inputs, h, extra=()) -> bool:
    """Every input's matches (the inputs as patients, plus ``extra``) are matches of ``g`` (reference oracle)."""
    pats = [patient_of(m) for m in inputs] + list(extra)
    return all(matches(g, p, h) for m in inputs for p in pats if matches(m, p, h))


def test_ctx_check(ctx):
    assert not ctx.config.attr_is_concept_dependent(AGE)


# --- §8.1 cases ----------------------------------------------------------------------------------------------------


def test_identical_motifs_aggregate_to_themselves(ctx):
    b = bundle("any", dx_drug("A", T2DM), dx_drug("B", T2DM))
    mv = only(aggregate(b, ["A", "B"], ctx))
    g = aggregate_of(mv)
    assert {(n.id, n.code) for n in g.nodes} == {(n.id, n.code) for n in b.part("A").motif.nodes}
    assert changes(mv, "A") == [] and changes(mv, "B") == []
    assert mv.child.anchor_part == aggregate_part_id(["A", "B"]) == "agg[A|B]"   # the anchor part was consumed


def test_different_concepts_are_lifted_to_their_common_ancestor(ctx):
    b = bundle("all", drug("A", DOX), dx_drug("S", T1DM), dx_drug("G", T2DM))
    mv = only(aggregate(b, ["S", "G"], ctx))
    g = aggregate_of(mv)
    assert g.node("G.d").code == DM and g.node("G.m").code == MET   # reference = smallest part id, G
    assert changes(mv, "S") == [["code_abstracted", "S.d", f"{T1DM}->{DM}"]]
    assert mv.child.anchor_part == "A" and mv.child.semantics == "all"
    assert covers(g, [b.part("S").motif, b.part("G").motif], ctx.hierarchy)
    assert check_bundle_order(b, mv.child, ctx, mv.certificate).ok


def test_semantics_is_kept(ctx):
    for sem in ("all", "any"):
        b = bundle(sem, drug("A", DOX), drug("B", DAUNO), anchor="A")
        mv = only(aggregate(b, ["A", "B"], ctx))
        assert mv.child.semantics == sem and aggregate_of(mv).node("A.d").code != DOX


def test_attributes_equal_contained_overlapping_and_missing(ctx):
    pairs = [((60, 70), (60, 70), None), ((60, 70), (62, 65), ["attr_widened", "G.d:age_at_dx", None]),
             ((60, 70), (65, 75), "both"), ((60, 70), None, "both")]
    for a_iv, b_iv, expected in pairs:
        s = dx("S", T2DM, **age(*a_iv))
        g = dx("G", T2DM, **(age(*b_iv) if b_iv else {}))
        mv = only(aggregate(bundle("any", g, s, anchor="G"), ["G", "S"], ctx))
        attr = aggregate_of(mv).node("G.d").attrs.get(AGE)
        if expected is None:
            assert attr == Interval.closed(*a_iv, "a") and changes(mv, "S") == []
        elif expected == "both":   # no range is invented: the constraint is dropped and recorded
            assert attr is None
            assert ["attr_dropped", "S.d:age_at_dx", None] in changes(mv, "S")
        else:
            assert attr == Interval.closed(*a_iv, "a") and changes(mv, "G") == [expected]


def test_edges_that_differ_are_dropped_and_recorded(ctx):
    s = dx_drug("S", T2DM)
    g = dx_drug("G", T2DM, edges=[("P", "d", "has_condition"), ("P", "m", "administered_drug")])
    mv = only(aggregate(bundle("any", g, s, anchor="G"), ["G", "S"], ctx))
    assert ["edge_dropped", "S.d->S.m", None] in changes(mv, "S")
    assert all(e.rel != "treated_with" for e in aggregate_of(mv).edges)


def test_relations_are_never_abstracted(ctx):
    s = dx("S", T2DM)
    g = motif("G", {"d": {"type": "Disorder", "code": T2DM, "role": "anchor"}}, [("P", "d", "has_finding")])
    mv = only(aggregate(bundle("any", g, s, anchor="G"), ["G", "S"], ctx))
    assert aggregate_of(mv).edges == ()
    assert changes(mv, "S") == [["edge_dropped", "P->S.d", None]]


def _two_disorders(mid, anchor, b_code, c_code, edge):
    return motif(mid, {"a": {"type": "Disorder", "code": anchor, "role": "anchor"},
                       "b": {"type": "Disorder", "code": b_code}, "c": {"type": "Disorder", "code": c_code}},
                 [("P", "a", "h"), ("P", "b", "h"), ("P", "c", "h"), edge])


def test_multiple_correspondences_give_incomparable_generalizations(ctx):
    """Pairing b with y keeps CKD but not the t edge; pairing b with z keeps the t edge but lifts both to DISEASE.
    Neither is more specific, so both are kept."""
    m1 = _two_disorders("M1", T1DM, MAL_THORAX, CKD, ("b", "c", "t"))
    m2 = _two_disorders("M2", T2DM, NEO_BREAST, CKD, ("c", "b", "t"))
    res = aggregate(bundle("any", m1, m2, anchor="M1"), ["M1", "M2"], ctx)
    gs = sorted((sorted(str(n.code) for n in aggregate_of(mv).nodes), len(aggregate_of(mv).edges)) for mv in res.moves)
    assert gs == sorted([(sorted(["None", DM, DISEASE, CKD]), 3), (sorted(["None", DM, DISEASE, DISEASE]), 4)])
    for mv in res.moves:
        assert covers(aggregate_of(mv), [m1, m2], ctx.hierarchy)
    assert res.moves[0].change.evidence["summary"]["correspondences"] == 2


def test_duplicate_generalizations_are_merged(ctx):
    m1 = _two_disorders("M1", T1DM, CKD, CKD, ("P", "a", "h"))
    m2 = _two_disorders("M2", T2DM, CKD, CKD, ("P", "a", "h"))
    cands, summary = generalize([m1, m2], ctx)
    assert (summary["correspondences"], summary["distinct"], len(cands)) == (2, 1, 1)


def test_a_more_general_candidate_is_dropped_only_when_proven(ctx):
    """Pairing CKD with CKD gives CKD; pairing CKD with T1DM gives DISEASE, proven more general, so it goes."""
    m1 = motif("M1", {"a": {"type": "Substance", "code": MET, "role": "anchor"}, "b": {"type": "Disorder", "code": CKD},
                      "c": {"type": "Disorder", "code": T1DM}}, [("P", "a", "x"), ("P", "b", "h"), ("P", "c", "h")])
    m2 = motif("M2", {"a": {"type": "Substance", "code": MET, "role": "anchor"}, "b": {"type": "Disorder", "code": CKD},
                      "c": {"type": "Disorder", "code": T2DM}}, [("P", "a", "x"), ("P", "b", "h"), ("P", "c", "h")])
    cands, summary = generalize([m1, m2], ctx)
    assert summary["distinct"] == 2 and len(cands) == 1
    assert sorted(str(n.code) for n in cands[0].motif.nodes) == sorted(["None", MET, CKD, DM])


def test_incompatible_motifs_have_no_correspondence(ctx):
    res = aggregate(bundle("any", drug("A", DOX), dx("B", T2DM)), ["A", "B"], ctx)
    assert res.moves == [] and [b.reason for b in res.blocked] == ["no_correspondence"]


def test_three_inputs_and_composition(ctx):
    b = bundle("any", drug("A", DOX), dx_drug("S", T1DM), dx_drug("T", T2DM), dx_drug("U", T1DM), anchor="A")
    mv3 = only(aggregate(b, ["S", "T", "U"], ctx))
    g3 = aggregate_of(mv3)
    assert g3.motif_id == "agg[S|T|U]" and g3.node("S.d").code == DM
    assert covers(g3, [b.part(p).motif for p in "STU"], ctx.hierarchy)
    step = only(aggregate(b, ["S", "T"], ctx))
    again = only(aggregate(step.child, ["agg[S|T]", "U"], ctx))
    assert again.change.after == "agg[S|T|U]"
    assert [p.part_id for p in again.child.parts] == [p.part_id for p in mv3.child.parts]   # paths converge


def test_valued_and_context_nodes_are_not_abstracted(ctx):
    """A node with a value keeps its code or is not corresponded; a context node needs an equal code."""
    s = dx_drug("S", T1DM, m_kw={"value": Interval.closed(1, 2, "mg")})
    g = dx_drug("G", T2DM, m_kw={"code": DOX, "value": Interval.closed(1, 2, "mg")})
    mv = only(aggregate(bundle("any", g, s, anchor="G"), ["G", "S"], ctx))
    assert "G.m" not in aggregate_of(mv).node_ids and ["node_dropped", "S.m", None] in changes(mv, "S")
    s = dx_drug("S", T1DM, m_kw={"role": "context"})
    g = dx_drug("G", T2DM, m_kw={"role": "context", "code": DOX})
    mv = only(aggregate(bundle("any", g, s, anchor="G"), ["G", "S"], ctx))
    assert "G.m" not in aggregate_of(mv).node_ids


def test_role_differences_are_recorded(ctx):
    s, g = dx_drug("S", T1DM, m_kw={"role": "modifier"}), dx_drug("G", T2DM)
    mv = only(aggregate(bundle("any", g, s, anchor="G"), ["G", "S"], ctx))
    assert aggregate_of(mv).node("G.m").role == "exposure"
    assert ["role_differs", "S.m", "modifier->exposure"] in changes(mv, "S")


def test_absent_nodes_kept_when_every_input_forbids_as_much(ctx):
    def with_absent(mid, code, absent):
        return motif(mid, {"d": {"type": "Disorder", "code": code, "role": "anchor"},
                           "x": {"type": "Disorder", "code": absent, "polarity": "absent"}},
                     [("P", "d", "has_condition"), ("P", "x", "has_condition")])
    same = only(aggregate(bundle("any", with_absent("G", T2DM, CKD), with_absent("S", T1DM, CKD), anchor="G"),
                          ["G", "S"], ctx))
    g = aggregate_of(same)
    assert [n.code for n in g.nodes if n.polarity == "absent"] == [CKD]
    assert same.change.evidence["completeness"]["negation"] == "complete"
    narrower = only(aggregate(bundle("any", with_absent("G", T2DM, DM), with_absent("S", T1DM, T1DM), anchor="G"),
                              ["G", "S"], ctx))
    g = aggregate_of(narrower)
    assert [n.code for n in g.nodes if n.polarity == "absent"] == [T1DM]   # T1DM lies below DM: forbidden by both
    assert ["absent_narrowed", "G.x", f"{DM}->{T1DM}"] in changes(narrower, "G")
    assert narrower.change.evidence["completeness"]["negation"] == "partial"
    unrelated = only(aggregate(bundle("any", with_absent("G", T2DM, CKD), with_absent("S", T1DM, RA), anchor="G"),
                               ["G", "S"], ctx))
    assert all(n.polarity == "present" for n in aggregate_of(unrelated).nodes)
    assert ["node_dropped", "S.x", None] in changes(unrelated, "S")   # negation is never dropped silently


def test_unknown_semantics_blocks(ctx):
    res = aggregate(bundle(None, dx("A", T1DM), dx("B", T2DM)), ["A", "B"], ctx)
    assert [b.reason for b in res.blocked] == ["unknown_bundle_semantics"] and res.moves == []


def test_pairwise_operator_and_determinism(ctx):
    b = bundle("any", drug("A", DOX), dx_drug("S", T1DM), dx_drug("T", T2DM), anchor="A")
    first, second = motif_aggregation(b, ctx), motif_aggregation(b, ctx)
    assert [m.change.after for m in first.moves] == [m.change.after for m in second.moves] == ["agg[S|T]"]
    assert [m.change.to_json() for m in first.moves] == [m.change.to_json() for m in second.moves]


def test_aggregate_in_an_and_bundle_is_matched_at_the_shared_patient_fact(ctx):
    """In an AND bundle the aggregate and the retained parts are matched at the same Patient fact: the child matches
    every patient the parent matches, over the synthetic patient set."""
    from tests.test_lattice_bundles import patients
    b = bundle("all", drug("A", DOX), dx("S", T1DM), dx("T", T2DM), anchor="A")
    mv = only(aggregate(b, ["S", "T"], ctx))
    assert aggregate_of(mv).node("S.d").code == DM
    pats = patients()
    assert any(matches_bundle(b, p, ctx.hierarchy) for p in pats)
    for p in pats:
        assert not matches_bundle(b, p, ctx.hierarchy) or matches_bundle(mv.child, p, ctx.hierarchy)


# --- lattice integration (opt-in) ----------------------------------------------------------------------------------


def test_aggregation_is_opt_in(ctx):
    assert "motif_aggregation" not in default_operators().names


def test_lattice_accepts_only_verified_aggregates(ctx):
    b = bundle("any", drug("A", DOX), dx("S", T1DM), dx("T", T2DM), anchor="A")
    ops = OperatorSet((), (motif_aggregation,))
    lat = enumerate_lattice(b, dataclasses.replace(ctx, operators=ops), climb=False)
    assert lat.status == "exhausted"
    agg = [c for c in lat.candidates.values() if any(p.part_id.startswith("agg[") for p in c.bundle.parts)]
    assert agg
    pats = [patient_of(p.motif) for p in b.parts]
    for c in agg:
        assert all(not matches_bundle(b, p, ctx.hierarchy) or matches_bundle(c.bundle, p, ctx.hierarchy) for p in pats)
    default = enumerate_lattice(b, dataclasses.replace(ctx, operators=OperatorSet((), default_operators().bundle)),
                                climb=False)
    assert not any(p.part_id.startswith("agg[") for c in default.candidates.values() for p in c.bundle.parts)


# --- property: every accepted aggregate covers its inputs ----------------------------------------------------------

PROPERTY = settings(suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
                    deadline=None, max_examples=80, derandomize=True)


@PROPERTY
@given(node_specs(1, 3), node_specs(1, 3), random_patients(), st.sampled_from(["all", "any"]))
def test_aggregate_never_loses_a_match(ctx, spec1, spec2, pats, sem):
    m1, m2 = motif("M1", *spec1), motif("M2", *spec2)
    b = bundle(sem, m1, m2, anchor="M1")
    res = aggregate(b, ["M1", "M2"], ctx)
    for mv in res.moves:
        assert decide_aggregation(b, mv.child, ctx, mv.certificate).ok
        assert covers(aggregate_of(mv), [m1, m2], ctx.hierarchy, pats), mv.change.evidence
        both = patient_of(m1, m2)
        assert not matches_bundle(b, both, ctx.hierarchy) or matches_bundle(mv.child, both, ctx.hierarchy)
    for blk in res.blocked:
        assert blk.reason == "no_correspondence" or blk.detail["status"] in {"INVALID", "UNKNOWN"}


def test_property_generator_is_not_vacuous(ctx):
    """The generator reaches aggregates that abstract a code and that drop structure."""
    def kinds(c):
        res = aggregate(bundle("any", motif("M1", *c[0]), motif("M2", *c[1]), anchor="M1"), ["M1", "M2"], ctx)
        return {ch[0] for mv in res.moves for cs in mv.change.evidence["changes"].values() for ch in cs}
    pairs = st.tuples(node_specs(1, 3), node_specs(1, 3))
    tune = settings(database=None, max_examples=2000, suppress_health_check=list(HealthCheck))
    for kind in ("code_abstracted", "node_dropped", "edge_dropped"):
        find(pairs, lambda c, k=kind: k in kinds(c), settings=tune)
