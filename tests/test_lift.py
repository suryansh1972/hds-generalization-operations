"""SNOMED CT-only concept lift (``semgen.lift``) and its independent verifier (``semgen.lift_verify``).

Unit tests use the synthetic fake release (tests/support/fake_snomed.py) or a tiny per-test release built below;
the expected outcomes follow from the ontology data given to the evaluator, never from a floor list. Real-release
and MIMIC-IV patient-graph tests skip when the data is absent.
"""
from __future__ import annotations

import gzip
import json
import os
import re
from pathlib import Path

import pytest

from semgen.concept_model import ConceptModel, Mrcm, MrcmDomain
from semgen.lattice import PolicyViolation, guard
from semgen.lift import REJECT_REASONS, UNKNOWN_REASONS, SnomedLift
from semgen.lift_verify import verify_candidate, verify_transition
from semgen.operators.base import ChangeRecord
from semgen.snomed import Hierarchy
from tests.conftest import one_node_motif
from tests.support.fake_snomed import (
    ANTHRA,
    BRCA,
    DISEASE,
    DOX,
    FIND,
    MAL_THORAX,
    MALIG,
    NEO_BREAST,
    RA,
    RA_OLD_PARENT,
    ROOT,
    SUBST,
    T2DM,
    fake_concept_model,
    fake_hierarchy,
    fake_lift,
)


@pytest.fixture
def lift():
    return fake_lift(fake_hierarchy())


# --- a tiny release per test: R -> T (top level, MRCM domain) -> A -> B -> C ---------------------------------------
def tiny(attrs=None, fsn=None, primitive=None, owl_defined=frozenset(), owl_axiom=None, mrcm="default",
         relationships_available=True, owl_available=True, isa=None):
    isa = isa or {"C": {"B"}, "B": {"A"}, "A": {"T"}, "T": {"R"}, "V": {"R"}, "V2": {"V"}, "R": set()}
    ids = set(isa) | {p for ps in isa.values() for p in ps}
    fsn = {c: f"{c} (disorder)" for c in ids} | (fsn or {})
    h = Hierarchy.from_maps(isa, fsn, ids)
    if mrcm == "default":
        mrcm = Mrcm((MrcmDomain("T", "<< T", "<<", "T", None),), frozenset({("S", "T")}), {}, {"S": (("<<", "V"),)})
    attrs = {c: (("S", "V2", "1"),) for c in "ABC"} if attrs is None else attrs
    axiom = frozenset(ids) if owl_axiom is None else owl_axiom
    prim = (frozenset(ids) - owl_defined) if primitive is None else primitive
    cm = ConceptModel(mrcm, attrs, {"t": 1}, prim, relationships_available, owl_axiom=axiom, owl_defined=owl_defined,
                      owl_available=owl_available)
    return SnomedLift(h, cm)


def rule(t, name):
    return next(r for r in t.rules if r["rule"] == name)


# 1. active / inactive -------------------------------------------------------------------------------------------
def test_inactive_concept_is_ineligible_and_inactive_parent_rejected(lift):
    r = lift.explore(RA_OLD_PARENT)
    assert r["eligible"] is False and r["reason"] == "inactive_concept" and r["candidates"] == []
    t = lift.evaluate(RA, RA_OLD_PARENT)
    assert (t.decision, t.reason) == ("rejected", "inactive_parent")


# 2-4, 15-16. parent discovery, multiple parents, multi-branch, intermediates, dedup ----------------------------
def test_every_direct_parent_evaluated_and_all_branches_explored(lift):
    r = lift.explore(BRCA)
    first = {t["parent"] for t in r["transitions"] if t["child"] == BRCA}
    assert first == {NEO_BREAST, MAL_THORAX} == set(lift.h.parents(BRCA))
    cands = [c["concept"] for c in r["candidates"]]
    assert set(cands) == {NEO_BREAST, MAL_THORAX, MALIG, DISEASE}     # every intermediate kept
    assert len(cands) == len(set(cands))                              # DISEASE reached twice, kept once
    disease = next(c for c in r["candidates"] if c["concept"] == DISEASE)
    assert sorted(disease["paths"]) == sorted([[BRCA, MAL_THORAX, MALIG, DISEASE], [BRCA, NEO_BREAST, DISEASE]])
    assert disease["depth"] == 2


# 5, 13-14. boundary, dynamic floor, termination: never climbs to the root ----------------------------------------
def test_stops_below_top_level_never_reaches_root(lift):
    for code in (BRCA, T2DM, DOX):
        r = lift.explore(code)
        reached = {c["concept"] for c in r["candidates"]}
        assert ROOT not in reached and FIND not in reached and SUBST not in reached
        assert r["complete"] and r["exhausted"]
    r = lift.explore(BRCA)
    (floor,) = [t for t in r["terminations"] if t["floor"]]
    assert floor["concept"] == DISEASE and floor["stopped"] == [
        {"parent": FIND, "decision": "rejected", "reason": "top_level_concept"}]
    assert [c["concept"] for c in r["candidates"] if c["is_branch_floor"]] == [DISEASE]
    assert r["rejected"] == [[DISEASE, FIND, "top_level_concept"]] and r["unknown"] == []


def test_hierarchy_root_and_top_level_rejected():
    lift = tiny()
    assert lift.evaluate("T", "R").reason == "hierarchy_root"
    assert lift.evaluate("A", "T").reason == "top_level_concept"
    assert lift.evaluate("C", "B").decision == "accepted"


# 6. semantic tag ---------------------------------------------------------------------------------------------------
def test_semantic_tag_change_rejected_and_missing_tag_unknown():
    t = tiny(fsn={"B": "B (finding)"}).evaluate("C", "B")
    assert (t.decision, t.reason) == ("rejected", "semantic_tag_changed")
    assert rule(t, "semantic_tag")["evidence"]["parent_tag"] == "finding"
    t = tiny(fsn={"B": "B without tag"}).evaluate("C", "B")
    assert (t.decision, t.reason) == ("unknown", "no_semantic_tag")


# 7. defining relationships -----------------------------------------------------------------------------------------
def test_dropped_attribute_type_rejected():
    t = tiny(attrs={"C": (("S", "V2", "1"), ("S2", "V2", "2")), "B": (("S", "V2", "1"),)}).evaluate("C", "B")
    assert (t.decision, t.reason) == ("rejected", "defining_attribute_dropped")
    assert rule(t, "defining_relationships")["evidence"]["dropped"] == ["S2"]


def test_value_broadened_to_mrcm_range_focus_counts_as_dropped():
    t = tiny(attrs={"C": (("S", "V2", "1"),), "B": (("S", "V", "1"),)}).evaluate("C", "B")
    assert (t.decision, t.reason) == ("rejected", "defining_attribute_dropped")
    assert rule(t, "defining_relationships")["evidence"]["reduced_to_range_focus"] == ["S"]


def test_fewer_relationship_groups_rejected():
    t = tiny(attrs={"C": (("S", "V2", "1"), ("S", "V2", "2")), "B": (("S", "V2", "1"),)}).evaluate("C", "B")
    assert (t.decision, t.reason) == ("rejected", "role_group_dropped")


# 8. OWL ------------------------------------------------------------------------------------------------------------
def test_owl_axiom_missing_conflicting_or_unavailable_is_unknown():
    assert tiny(owl_axiom=frozenset("ABRTV")).evaluate("C", "B").reason == "owl_axiom_missing"
    assert tiny(owl_defined=frozenset({"B"}), primitive=frozenset("ABCRTV")).evaluate("C", "B").reason \
        == "definition_status_conflict"
    assert tiny(owl_available=False).evaluate("C", "B").reason == "owl_unavailable"


# 9. MRCM -----------------------------------------------------------------------------------------------------------
def test_mrcm_domain_constraints():
    sub = Mrcm((MrcmDomain("T", "<< T", "<<", "T", None), MrcmDomain("B", "<< B", "<<", "B", "T")),
               frozenset({("S", "T")}), {}, {"S": (("<<", "V"),)})
    assert tiny(mrcm=sub).evaluate("C", "B").reason == "mrcm_domain_concept"   # B names a domain
    lost = Mrcm((MrcmDomain("T", "<< T", "<<", "T", None), MrcmDomain("X", "C", "", "C", "T")),
                frozenset({("S", "T")}), {}, {"S": (("<<", "V"),)})
    assert tiny(mrcm=lost).evaluate("C", "B").reason == "mrcm_domain_lost"
    assert tiny(mrcm=None).evaluate("C", "B").reason == "mrcm_unavailable"
    none = Mrcm((), frozenset(), {}, {})
    assert tiny(mrcm=none).evaluate("C", "B").reason == "no_mrcm_domain"
    no_attr = Mrcm((MrcmDomain("T", "<< T", "<<", "T", None),), frozenset(), {}, {"S": (("<<", "V"),)})
    assert tiny(mrcm=no_attr).evaluate("C", "B").reason == "attribute_outside_mrcm_domain"
    t = tiny(attrs={"C": (("S", "R", "1"),), "B": (("S", "R", "1"),)}).evaluate("C", "B")
    assert t.reason == "attribute_value_outside_mrcm_range"


# 10. primitive / fully defined: evidence, not a stopping rule -------------------------------------------------------
def test_primitive_and_fully_defined_parents_both_generalize():
    t = tiny().evaluate("C", "B")
    assert t.decision == "accepted" and rule(t, "definition")["evidence"]["parent_definition"] == "primitive"
    t = tiny(owl_defined=frozenset({"B"})).evaluate("C", "B")
    assert t.decision == "accepted" and rule(t, "definition")["evidence"]["parent_definition"] == "fully_defined"


# 11-12. missing ontology information -> unknown, never accepted --------------------------------------------------
def test_missing_relationships_are_unknown_and_not_candidates():
    assert tiny(relationships_available=False).evaluate("C", "B").reason == "relationships_unavailable"
    lift = tiny(attrs={})
    t = lift.evaluate("C", "B")
    assert (t.decision, t.reason) == ("unknown", "no_defining_relationships")
    r = lift.explore("C")
    assert r["candidates"] == [] and r["unknown"] == [["C", "B", "no_defining_relationships"]]
    assert r["origin_floor"] and r["complete"]


def test_reasons_are_partitioned_and_every_transition_has_one_outcome(lift):
    assert not REJECT_REASONS & UNKNOWN_REASONS
    for code in (BRCA, RA, T2DM, DOX):
        for t in lift.explore(code)["transitions"]:
            assert t["decision"] in {"accepted", "rejected", "unknown"}
            assert (t["reason"] is None) == (t["decision"] == "accepted")
            assert t["reason"] is None or t["reason"] in (REJECT_REASONS if t["decision"] == "rejected" else UNKNOWN_REASONS)


# 17. provenance ----------------------------------------------------------------------------------------------------
def test_candidates_carry_provenance_and_are_verified(lift):
    r = lift.explore(BRCA)
    pairs = {(t["child"], t["parent"]): t for t in r["transitions"]}
    for c in r["candidates"]:
        assert c["original"] == BRCA and c["snomed_release"] == lift.h.release and c["fingerprint"] == lift.fingerprint
        assert c["verification"] == {"status": "verified", "problems": []}
        for path in c["paths"]:
            assert all(pairs[(a, b)]["decision"] == "accepted" for a, b in zip(path, path[1:]))


# 18. independent verifier, adversarial -----------------------------------------------------------------------------
def test_verifier_rejects_what_a_mocked_generator_accepts(lift, monkeypatch, ctx):
    from semgen.lift import Transition
    monkeypatch.setattr(SnomedLift, "evaluate", lambda self, c, p: Transition(c, p, "accepted", None, ()))
    assert ctx.floors.check_lift(DISEASE, FIND).ok                     # the generator is fooled ...
    m = one_node_motif(DISEASE)
    child = m.replace_node(m.node("n1").model_copy(update={"code": FIND}))
    rec = ChangeRecord("concept_lift", "n1", "code", DISEASE, FIND,
                       {"isa": [DISEASE, FIND], "transition": {"child": DISEASE, "parent": FIND, "decision": "accepted"},
                        "fingerprint": ctx.floors.fingerprint})
    with pytest.raises(PolicyViolation, match="lift_verification_failed.*reaches_hierarchy_top"):
        guard(m, child, rec, ctx)                                     # ... the verifier is not


def test_verifier_checks_each_constraint_independently():
    h, cm = fake_hierarchy(), fake_concept_model()
    ok = {"child": BRCA, "parent": NEO_BREAST, "decision": "accepted"}
    assert verify_transition(h, cm, BRCA, NEO_BREAST, ok, "f", "f") == []
    assert verify_transition(h, cm, BRCA, MALIG, None, "f", "f") == ["not_an_inferred_parent"]
    assert "fingerprint_mismatch" in verify_transition(h, cm, BRCA, NEO_BREAST, ok, "old", "f")
    assert "record_mismatch" in verify_transition(h, cm, BRCA, NEO_BREAST, {**ok, "decision": "unknown"}, "f", "f")
    assert verify_transition(h, cm, RA, RA_OLD_PARENT, None, "f", "f") == ["inactive_concept"]
    dropped = ConceptModel(cm.mrcm, {**cm.attributes, NEO_BREAST: ()}, {}, cm.primitive, owl_axiom=cm.owl_axiom,
                           owl_available=True)
    assert any(p.startswith("relationship_not_subsumed") for p in verify_transition(h, dropped, BRCA, NEO_BREAST, None, "f", "f"))
    assert "semantic_tag_not_preserved" in verify_transition(h, cm, ANTHRA, SUBST, None, "f", "f") or \
        "reaches_hierarchy_top" in verify_transition(h, cm, ANTHRA, SUBST, None, "f", "f")


def test_verifier_rejects_forged_candidate_paths(lift):
    r = lift.explore(BRCA)
    pairs = {(t["child"], t["parent"]): t for t in r["transitions"]}
    cand = next(c for c in r["candidates"] if c["concept"] == DISEASE)
    ok, _ = verify_candidate(lift.h, lift.concept_model, {**cand, "paths": [[BRCA, MALIG, DISEASE]]}, pairs,
                             lift.fingerprint)
    assert not ok                                                       # BRCA -> MALIG skips a level
    ok, probs = verify_candidate(lift.h, lift.concept_model, {**cand, "snomed_release": "OTHER"}, pairs, lift.fingerprint)
    assert not ok and "release_mismatch" in probs


# 19-20. determinism and budget -------------------------------------------------------------------------------------
def test_deterministic(lift):
    a = json.dumps(lift.explore(BRCA), sort_keys=True)
    assert a == json.dumps(lift.explore(BRCA), sort_keys=True) == json.dumps(fake_lift(fake_hierarchy()).explore(BRCA), sort_keys=True)


def test_budget_reports_incomplete_never_exhausted(lift):
    r = lift.explore(BRCA, max_transitions=2)
    assert r["complete"] is False and r["exhausted"] is False and r["pending"]
    assert r["transitions_evaluated"] <= 2
    assert lift.explore(BRCA)["complete"] is True


def test_no_clinical_constants_in_lift_modules():
    src = Path(__file__).resolve().parents[1] / "src" / "semgen"
    for f in ("lift.py", "lift_verify.py", "operators/concept_lift.py"):
        assert not re.search(r"(?<![\w.])\d{6,18}(?![\w.])", (src / f).read_text()), f


# --- real release ---------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def real_lift(real_h):
    from semgen.context import build_lift
    from semgen.snomed import default_rf2_dir
    return build_lift(real_h, default_rf2_dir())


def _real_top_levels(h):
    return lambda c: (not h.parents(c)) or all(not h.parents(q) for q in h.parents(c))


@pytest.mark.snomed
@pytest.mark.parametrize("code", ["44054006", "254837009", "372817009", "69896004", "90560007"])
def test_real_exploration_is_verified_complete_and_below_top_level(real_lift, code):
    r = real_lift.explore(code)
    top = _real_top_levels(real_lift.h)
    assert r["eligible"] and r["complete"] and r["exhausted"]
    assert all(c["verification"]["status"] == "verified" for c in r["candidates"])
    assert not any(top(c["concept"]) for c in r["candidates"])


@pytest.mark.snomed
def test_real_multi_branch_and_floor(real_lift):
    r = real_lift.explore("254837009")   # malignant neoplasm of breast: two inferred parents
    first = {t["parent"] for t in r["transitions"] if t["child"] == "254837009" and t["decision"] == "accepted"}
    assert len(first) == 2 and first == set(real_lift.h.parents("254837009"))
    assert any(c["is_branch_floor"] for c in r["candidates"])


@pytest.mark.snomed
def test_real_generalization_can_also_stop_immediately(real_lift):
    r = real_lift.explore("69896004")    # rheumatoid arthritis: both parents drop a defining attribute
    assert r["candidates"] == [] and r["origin_floor"]
    assert {x[2] for x in r["rejected"]} == {"defining_attribute_dropped"}


@pytest.mark.snomed
def test_real_disposition_does_not_broaden_to_its_range_focus(real_lift):
    r = real_lift.explore("372817009")                                                 # doxorubicin
    cands = {c["concept"] for c in r["candidates"]}
    assert "372540003" in cands                                                         # anthracycline
    focus = [t for t in r["transitions"] if any(x["evidence"].get("reduced_to_range_focus") for x in t["rules"])]
    assert focus and all(t["decision"] == "rejected" and t["parent"] not in cands for t in focus)


@pytest.mark.snomed
def test_real_owl_and_definition_status_agree(real_lift):
    cm = real_lift.concept_model
    assert cm.owl_available and len(cm.owl_defined) > 100000
    for c in ("44054006", "73211009", "254837009"):
        assert c in cm.owl_axiom and (c in cm.owl_defined) != (c in cm.primitive)


# --- MIMIC-IV demo patient graphs (SNOMED-coded facts only) -------------------------------------------------------
# Restricted data, never in the repository: point SEMGEN_MIMIC_GRAPHS at patient_graphs.jsonl.gz to run this check.
GRAPHS = Path(os.environ.get("SEMGEN_MIMIC_GRAPHS", "patient_graphs.jsonl.gz.not-configured"))


def _mimic_codes() -> list[str]:
    codes: set[str] = set()
    with gzip.open(GRAPHS, "rt") as f:
        for line in f:
            for facts in json.loads(line)["stays"].values():
                # a label may carry the reader's note: "diagnosis|SCTID:10295004 [read broader than the record]"
                codes |= {x.split("|SCTID:", 1)[1].split(" [", 1)[0] for x in facts if "|SCTID:" in x}
    return sorted(codes)


@pytest.mark.snomed
def test_mimic_patient_graph_codes(real_lift):
    if not GRAPHS.is_file():
        pytest.skip("MIMIC patient graphs not available (set SEMGEN_MIMIC_GRAPHS)")
    codes = _mimic_codes()
    assert codes
    top = _real_top_levels(real_lift.h)
    lifted = 0
    for code in codes:
        r = real_lift.explore(code)
        if not r["eligible"]:   # not an active concept of the International release (e.g. a US-extension id)
            assert r["reason"] == "inactive_concept" and not real_lift.h.is_active(code)
            continue
        assert r["complete"] and r["exhausted"]
        assert all(c["verification"]["status"] == "verified" for c in r["candidates"]), code
        assert not any(top(c["concept"]) for c in r["candidates"]), code
        lifted += bool(r["candidates"])
    assert 0 < lifted < len(codes)          # some concepts generalize, some stop at once: not "always climb"
    sample = codes[:: max(1, len(codes) // 20)]
    fresh = SnomedLift(real_lift.h, real_lift.concept_model)
    assert [json.dumps(real_lift.explore(c), sort_keys=True) for c in sample] == \
        [json.dumps(fresh.explore(c), sort_keys=True) for c in sample]
