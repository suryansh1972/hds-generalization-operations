"""The independent checker (spec §6) rejects every faulty aggregation and deletion, whatever the generator claims.

Faulty candidates are submitted straight to the checker (``check_bundle_order``) and, through a generator whose own
acceptance is bypassed, to the lattice, which must refuse them (``GeneralizationOrderError``). UNKNOWN is never
accepted.
"""
from __future__ import annotations

import dataclasses

import pytest

import semgen.operators.motif_aggregation as agg_mod
import semgen.operators.motif_deletion as del_mod
from semgen.bundle import MotifBundle, MotifPart
from semgen.containment import Verdict
from semgen.interfaces import BundleMove, BundleOperatorResult, ChangeRecord, OperatorSet
from semgen.lattice import GeneralizationOrderError, PolicyViolation, bundle_neighbors
from semgen.model import PATIENT_ID, Edge, Interval, Motif, Node
from semgen.operators.motif_aggregation import aggregate, motif_aggregation
from semgen.operators.motif_deletion import motif_deletion
from semgen.order import check_bundle_order, decide_aggregation, decide_part_removal
from tests.support.fake_snomed import DISEASE, DM, DOX, FIND, MET, RA_OLD_PARENT, SUBST, T1DM, T2DM
from tests.support.matcher import matches, matches_bundle
from tests.test_op_motif_deletion import bundle, drug, dx, dx_drug, motif

# --- aggregation ---------------------------------------------------------------------------------------------------


@pytest.fixture
def honest(ctx):
    """A bundle, a verified aggregation move of S and G (T1DM, T2DM -> DM) and its aggregate."""
    b = bundle("any", drug("A", DOX), dx_drug("S", T1DM), dx_drug("G", T2DM), anchor="A")
    (mv,) = aggregate(b, ["G", "S"], ctx).moves
    return b, mv, mv.child.part("agg[G|S]").motif


def forged(b: MotifBundle, mv, g: Motif) -> MotifBundle:
    return mv.child.model_copy(update={"parts": tuple(p for p in mv.child.parts if p.part_id != g.motif_id)
                                       + (MotifPart(part_id=g.motif_id, motif=g),)})


def recorded(mv, **changes) -> dict:
    """``mv``'s certificate with some parts' recorded changes replaced."""
    return {"maps": mv.certificate["maps"], "changes": mv.certificate["changes"] | changes}


def test_honest_aggregate_is_valid(ctx, honest):
    b, mv, _ = honest
    assert decide_aggregation(b, mv.child, ctx, mv.certificate).ok


def test_aggregate_that_does_not_cover_an_input(ctx, honest):
    """The generator's claim is ignored: a narrower code is not covered, and the counterexample shows it."""
    b, mv, g = honest
    bad = g.replace_node(g.node("G.d").model_copy(update={"code": T2DM}))
    v = decide_aggregation(b, forged(b, mv, bad), ctx, recorded(mv, G=[]))   # G's record is consistent: only S fails
    assert (v.status, v.reason, v.evidence["part"]) == ("INVALID", "not_covered", "S")
    cx = Motif.model_validate(v.evidence["counterexample"])
    assert matches(b.part("S").motif, cx, ctx.hierarchy) and not matches(bad, cx, ctx.hierarchy)


def test_incorrect_node_correspondence(ctx, honest):
    b, mv, _ = honest
    swapped = {"G.d": "S.m", "G.m": "S.d", "P": "P"}
    cert = {"maps": mv.certificate["maps"] | {"S": swapped}, "changes": mv.certificate["changes"]}
    v = decide_aggregation(b, mv.child, ctx, cert)
    assert not v.ok and (v.status, v.reason) == ("UNKNOWN", "certificate_unverified")


def test_incorrect_edge_correspondence(ctx, honest):
    b, mv, g = honest
    reversed_edge = tuple(Edge(s=e.t, t=e.s, rel=e.rel, prov=e.prov) if e.rel == "treated_with" else e for e in g.edges)
    v = decide_aggregation(b, forged(b, mv, g.model_copy(update={"edges": reversed_edge})), ctx, mv.certificate)
    assert (v.status, v.reason) == ("INVALID", "not_covered")


def test_missing_or_relabelled_relationship(ctx, honest):
    b, mv, g = honest
    relabelled = tuple(e.model_copy(update={"rel": "caused_by"}) if e.rel == "treated_with" else e for e in g.edges)
    assert decide_aggregation(b, forged(b, mv, g.model_copy(update={"edges": relabelled})), ctx,
                              mv.certificate).reason == "not_covered"
    dropped = tuple(e for e in g.edges if e.rel != "treated_with")   # covered, but the loss is not recorded
    v = decide_aggregation(b, forged(b, mv, g.model_copy(update={"edges": dropped})), ctx, mv.certificate)
    assert (v.status, v.reason) == ("INVALID", "unrecorded_change")


def test_unsupported_variable_abstraction(ctx, honest):
    b, mv, g = honest
    bad = g.replace_node(g.node("G.d").model_copy(update={"code": None}))
    v = decide_aggregation(b, forged(b, mv, bad), ctx, mv.certificate)
    assert (v.status, v.reason) == ("INVALID", "code_variable_unsupported")


def test_abstraction_outside_the_lift_boundary(ctx, honest):
    """Lifting to a top-level concept covers both inputs but is not a step concept lift's verifier accepts."""
    b, mv, g = honest
    bad = g.replace_node(g.node("G.d").model_copy(update={"code": FIND}))
    cert = recorded(mv, S=[["code_abstracted", "S.d", f"{T1DM}->{FIND}"]],
                    G=[["code_abstracted", "G.d", f"{T2DM}->{FIND}"]])
    v = decide_aggregation(b, forged(b, mv, bad), ctx, cert)
    assert (v.status, v.reason) == ("INVALID", "abstraction_outside_lift_boundary")


def test_abstraction_on_a_valued_node(ctx):
    """Drugs with a dose are not abstracted (the generator drops the pair); an aggregate that lifts them anyway is
    refused even though it covers both inputs."""
    dose = {"value": Interval.closed(1, 2, "mg")}
    s, g = dx_drug("S", T2DM, m_kw=dose), dx_drug("G", T2DM, m_kw=dose | {"code": DOX})
    b = bundle("any", drug("A", DOX), s, g, anchor="A")
    (mv,) = aggregate(b, ["G", "S"], ctx).moves
    agg = mv.child.part("agg[G|S]").motif
    assert "G.m" not in agg.node_ids
    lifted = Node(id="G.m", type="Substance", role="exposure", code=SUBST, value=Interval.closed(1, 2, "mg"))
    bad = agg.model_copy(update={"nodes": agg.nodes + (lifted,)})
    maps = {"G": mv.certificate["maps"]["G"] | {"G.m": "G.m"}, "S": mv.certificate["maps"]["S"] | {"G.m": "S.m"}}
    v = decide_aggregation(b, forged(b, mv, bad), ctx, {"maps": maps, "changes": mv.certificate["changes"]})
    assert (v.status, v.reason) == ("INVALID", "abstraction_on_constrained_node")


def test_lost_attribute_must_be_recorded(ctx):
    s = dx("S", T2DM, attrs={"age_at_dx": Interval.closed(60, 70, "a")})
    g = dx("G", T2DM, attrs={"age_at_dx": Interval.closed(60, 70, "a")})
    b = bundle("any", drug("A", DOX), s, g, anchor="A")
    (mv,) = aggregate(b, ["G", "S"], ctx).moves
    agg = mv.child.part("agg[G|S]").motif
    bad = agg.replace_node(agg.node("G.d").model_copy(update={"attrs": {}}))
    v = decide_aggregation(b, forged(b, mv, bad), ctx, mv.certificate)
    assert (v.status, v.reason) == ("INVALID", "unrecorded_change")
    honest_record = recorded(mv, S=[["attr_dropped", "S.d:age_at_dx", None]], G=[["attr_dropped", "G.d:age_at_dx",
                                                                                   None]])
    assert decide_aggregation(b, forged(b, mv, bad), ctx, honest_record).ok   # recorded: a permitted drop


def test_transition_shape_is_checked(ctx, honest):
    b, mv, g = honest
    wrong_id = forged(b, mv, g).model_copy(update={"parts": tuple(
        MotifPart(part_id="M9", motif=g.model_copy(update={"motif_id": "M9"})) if p.part_id == g.motif_id else p
        for p in mv.child.parts)})
    assert check_bundle_order(b, wrong_id, ctx, mv.certificate).reason == "aggregate_id_mismatch"
    retained = mv.child.model_copy(update={"parts": tuple(
        MotifPart(part_id="A", motif=drug("A", MET)) if p.part_id == "A" else p for p in mv.child.parts)})
    assert check_bundle_order(b, retained, ctx, mv.certificate).reason == "unsupported_transition"
    other_patient = g.replace_node(Node(id=PATIENT_ID, type="Patient", role="patient", code=DISEASE))
    assert decide_aggregation(b, forged(b, mv, other_patient), ctx, mv.certificate).reason == "patient_node_changed"
    moved_anchor = mv.child.model_copy(update={"anchor_part": g.motif_id})   # A was not consumed
    assert check_bundle_order(b, moved_anchor, ctx, mv.certificate).reason == "unsupported_transition"
    with pytest.raises(PolicyViolation):
        from semgen.lattice import bundle_guard
        bundle_guard(b, moved_anchor)


def _rogue(moves_of):
    def rogue(bundle, ctx):
        return BundleOperatorResult(moves_of(bundle, ctx), [])
    rogue.op_name = "rogue"
    return rogue


def test_lattice_refuses_a_generator_that_accepts_an_invalid_aggregate(ctx, honest, monkeypatch):
    b, mv, g = honest
    bad = g.replace_node(g.node("G.d").model_copy(update={"code": T2DM}))
    move = BundleMove(forged(b, mv, bad), mv.change, mv.certificate)
    with pytest.raises(GeneralizationOrderError):
        bundle_neighbors(b, dataclasses.replace(ctx, operators=OperatorSet((), (_rogue(lambda *_: [move]),))))
    # the real generator with its own acceptance patched out: the lattice still checks every move
    monkeypatch.setattr(agg_mod, "decide_aggregation", lambda *a, **k: Verdict("VALID", "patched"))
    monkeypatch.setattr(agg_mod, "_merge_interval", lambda ivs: ivs[0])   # keeps the first input's interval
    wide = bundle("any", drug("A", DOX), dx_drug("S", T2DM, d_kw={"attrs": {"age_at_dx": Interval.closed(1, 5, "a")}}),
                  dx_drug("G", T2DM, d_kw={"attrs": {"age_at_dx": Interval.closed(3, 9, "a")}}), anchor="A")
    with pytest.raises(GeneralizationOrderError):
        bundle_neighbors(wide, dataclasses.replace(ctx, operators=OperatorSet((), (motif_aggregation,))))


# --- deletion ------------------------------------------------------------------------------------------------------

X, Y = dx("X", T2DM), dx("Y", DM)   # X ⊑ Y
A = drug("A", DOX)


def without(b: MotifBundle, pid: str) -> MotifBundle:
    return b.model_copy(update={"parts": tuple(p for p in b.parts if p.part_id != pid)})


def test_non_redundant_removal_and_wrong_direction_are_rejected(ctx):
    for sem, wrong in (("all", "X"), ("any", "Y")):   # AND keeps the narrower part, OR the broader one
        b = bundle(sem, A, X, Y)
        for cert in (None, {"P": "P", "Y.d": "X.d"}, {"P": "P", "X.d": "Y.d"}):
            r = check_bundle_order(b, without(b, wrong), ctx, cert)
            assert (r.ok, r.reason) == (False, "not_contained"), (sem, cert)
        right = "Y" if sem == "all" else "X"
        assert check_bundle_order(b, without(b, right), ctx).ok


def test_whole_expression_equivalence(ctx):
    """OR: a drug in [0, 10] is covered by [0, 5] OR [5, 10] although by neither alone; one more gap breaks it."""
    def dosed(mid, lo, hi):
        return motif(mid, {"m": {"type": "Substance", "code": MET, "role": "anchor",
                                 "value": Interval.closed(lo, hi, "mg")}}, [("P", "m", "administered_drug")])
    b = bundle("any", A, dosed("W", 0, 10), dosed("L", 0, 5), dosed("U", 5, 10))
    assert decide_part_removal(b, "W", ctx).ok
    (mv,) = [m for m in motif_deletion(b, ctx).moves if m.change.evidence["deleted"] == "W"]
    assert mv.change.rule_id == "motif.delete.expression_redundant"
    gap = bundle("any", A, dosed("W", 0, 10), dosed("L", 0, 5), dosed("U", 6, 10))
    v = decide_part_removal(gap, "W", ctx)
    assert v.status == "INVALID"
    cx = Motif.model_validate(v.evidence["counterexample"])
    assert matches_bundle(gap, cx, ctx.hierarchy) != matches_bundle(without(gap, "W"), cx, ctx.hierarchy)


def test_conjunction_redundancy_needs_the_whole_expression(ctx):
    """AND: MB (P -> T2DM) and MC (P -> T1DM) together imply MA (P -> two disorders, one under DM), because every
    part is matched at the same Patient fact; neither alone does. A pairwise-only check could not find it."""
    def on_p(mid, *codes, type="Disorder"):
        nodes = {f"n{i}": {"type": type, "code": c} for i, c in enumerate(codes)}
        return motif(mid, nodes, [("P", k, "has_condition") for k in nodes])
    a0, ma = on_p("A0", DOX, type="Substance"), on_p("MA", DM, DISEASE)
    mb, mc = on_p("MB", T2DM), on_p("MC", T1DM)
    assert decide_part_removal(bundle("all", a0, ma, mb, mc, anchor="A0"), "MA", ctx).ok
    assert decide_part_removal(bundle("all", a0, ma, mb, anchor="A0"), "MA", ctx).status == "INVALID"
    assert decide_part_removal(bundle("all", a0, ma, mc, anchor="A0"), "MA", ctx).status == "INVALID"
    b = bundle("all", a0, ma, mb, mc, anchor="A0")
    res = motif_deletion(b, ctx)
    (mv,) = [m for m in res.moves if m.change.evidence["deleted"] == "MA"]
    assert mv.change.rule_id == "motif.delete.expression_redundant" and mv.change.evidence["subsumed_by"] is None
    from tests.test_lattice_bundles import patients
    for p in patients():
        assert matches_bundle(b, p, ctx.hierarchy) == matches_bundle(mv.child, p, ctx.hierarchy)


def test_retained_part_modified_is_rejected(ctx):
    b = bundle("all", A, X, Y)
    changed = without(b, "Y").model_copy(update={"parts": (b.part("A"), MotifPart(part_id="X", motif=dx("X", T1DM)))})
    assert check_bundle_order(b, changed, ctx).reason == "unsupported_transition"


def test_lattice_refuses_a_generator_that_removes_a_non_redundant_part(ctx, monkeypatch):
    b = bundle("all", A, X, Y)
    bad = BundleMove(without(b, "X"), ChangeRecord("motif_deletion", "X", "part", "X", None, {}, meaning="kept"),
                     {"P": "P", "Y.d": "X.d"})
    with pytest.raises(GeneralizationOrderError):
        bundle_neighbors(b, dataclasses.replace(ctx, operators=OperatorSet((), (_rogue(lambda *_: [bad]),))))
    monkeypatch.setattr(del_mod, "decide_part_removal", lambda *a, **k: Verdict("VALID", "patched"))
    with pytest.raises(GeneralizationOrderError):   # every part is now "deleted": X and A's removal are refused
        bundle_neighbors(b, dataclasses.replace(ctx, operators=OperatorSet((), (motif_deletion,))))


def test_unknown_is_never_accepted(ctx, monkeypatch):
    b = bundle("all", A, dx("S", T2DM), dx("G", RA_OLD_PARENT))
    v = decide_part_removal(b, "G", ctx)
    assert (v.status, v.ok) == ("UNKNOWN", False)
    assert check_bundle_order(b, without(b, "G"), ctx).reason == "snomed_mapping_missing"
    monkeypatch.setattr(del_mod, "decide_part_removal", lambda *a, **k: Verdict("VALID", "patched"))
    (mv,) = [m for m in motif_deletion(b, ctx).moves if m.change.evidence["deleted"] == "G"]
    with pytest.raises(GeneralizationOrderError):
        bundle_neighbors(b, dataclasses.replace(ctx, operators=OperatorSet((), (_rogue(lambda *_: [mv]),))))
