"""Fake SNOMED release for unit tests: hierarchy with semantic-tagged FSNs plus a synthetic concept model (MRCM
domains, attribute domains/ranges, defining relationships, OWL axioms), and ``SnomedLift`` over it.

Synthetic (not clinical) data: every disorder carries one grouped finding-site relationship, substances a
disposition, observables a component, so lifts inside a domain keep their attribute axes and stop at the
top-level concepts (FIND, SUBST, OBS), which also name the MRCM domains.
"""
from __future__ import annotations

from pathlib import Path

from semgen.concept_model import ConceptModel, Mrcm, MrcmDomain
from semgen.lift import SnomedLift
from semgen.settings import default_config_path
from semgen.snomed import Hierarchy

CONFIG_PATH = default_config_path()

ROOT, DISEASE, MALIG, NEO_BREAST, MAL_THORAX, BRCA = "138875005", "64572001", "363346000", "126926005", "188361007", "254837009"
DM, T1DM, T2DM, RA, RA_OLD_PARENT = "73211009", "46635009", "44054006", "69896004", "900000000000000001"  # last: inactive
CKD, BIGUANIDE, MET = "709044004", "1363127000", "372567009"
SUBST, ANTHRA, DOX, DAUNO = "105590001", "372540003", "372817009", "372715008"
OBS, LVEF, GFR = "363787002", "250908004", "80274001"
STRUCT = "900000000000000002"
FIND, BODY, DISPV, COMPV = "404684003", "123037004", "766779001", "900000000000000003"
FSITE, DISP, COMP = "363698007", "726542003", "246093002"   # attribute types

FAKE_ISA: dict[str, set[str]] = {
    FIND: {ROOT}, DISEASE: {FIND}, MALIG: {DISEASE}, NEO_BREAST: {DISEASE}, MAL_THORAX: {MALIG},
    BRCA: {NEO_BREAST, MAL_THORAX}, DM: {DISEASE}, T1DM: {DM}, T2DM: {DM}, CKD: {DISEASE},
    RA: {DISEASE, RA_OLD_PARENT}, SUBST: {ROOT}, ANTHRA: {SUBST}, DOX: {ANTHRA},
    DAUNO: {ANTHRA}, BIGUANIDE: {SUBST}, MET: {BIGUANIDE}, OBS: {ROOT}, LVEF: {OBS}, GFR: {OBS},
    STRUCT: {SUBST}, BODY: {ROOT}, DISPV: {ROOT}, COMPV: {ROOT}, ROOT: set(),
}

FAKE_FSN: dict[str, str] = {
    ROOT: "SNOMED CT Concept (SNOMED RT+CTV3)",
    FIND: "Clinical finding (finding)",
    BODY: "Body structure (body structure)",
    DISPV: "Disposition (disposition)",
    COMPV: "Fake component (substance)",
    DISEASE: "Disease (disorder)",
    MALIG: "Malignant neoplastic disease (disorder)",
    NEO_BREAST: "Neoplasm of breast (disorder)",
    MAL_THORAX: "Malignant neoplasm of thorax (disorder)",
    BRCA: "Malignant neoplasm of breast (disorder)",
    DM: "Diabetes mellitus (disorder)",
    T1DM: "Diabetes mellitus type 1 (disorder)",
    T2DM: "Diabetes mellitus type 2 (disorder)",
    RA: "Rheumatoid arthritis (disorder)",
    RA_OLD_PARENT: "Retired arthritis grouper (disorder)",
    CKD: "Chronic kidney disease (disorder)",
    SUBST: "Substance (substance)",
    ANTHRA: "Anthracycline (substance)",
    DOX: "Doxorubicin (substance)",
    DAUNO: "Daunorubicin (substance)",
    BIGUANIDE: "Biguanide (substance)",
    MET: "Metformin (substance)",
    STRUCT: "Substance categorized by structure (substance)",
    OBS: "Observable entity (observable entity)",
    LVEF: "Left ventricular ejection fraction (observable entity)",
    GFR: "Glomerular filtration rate (observable entity)",
}
assert len(set(FAKE_FSN.values())) == len(FAKE_FSN), "fake FSNs must be unique"

FAKE_RELEASE = "TEST"

# Raw fake motifs M1/M2 (parse with ``parse_motif(copy.deepcopy(...), None)``).
OPT_GENE, OPT_PATHWAY = "ENSG00000077097", "REACT:R-HSA-PLACEHOLDER-1"
FAKE_M1: dict = {
    "motif_id": "M1", "anchor": "n1",
    "nodes": [
        {"id": "P", "type": "Patient", "role": "patient"},
        {"id": "n1", "type": "Disorder", "code": BRCA, "polarity": "present", "role": "anchor",
         "attrs": {"age_at_dx": {"interval": [67, 67], "unit": "a"}}},
        {"id": "n2", "type": "Substance", "code": DOX, "polarity": "present", "role": "exposure",
         "attrs": {"cumulative_dose": {"interval": [360, 360], "unit": "mg/m2"}}},
        {"id": "n3", "type": "Observable", "code": LVEF, "polarity": "present", "role": "outcome",
         "value": {"interval": [38, 38], "unit": "%"}},
        {"id": "n4", "type": "Gene", "label": "TOP2B", "code": OPT_GENE, "polarity": "present", "role": "context"},
        {"id": "n5", "type": "Pathway", "label": "DNA topoisomerase II pathway", "code": OPT_PATHWAY,
         "polarity": "present", "role": "context"}],
    "edges": [
        {"s": "P", "t": "n1", "rel": "has_condition", "prov": "asserted"},
        {"s": "P", "t": "n2", "rel": "administered_drug", "prov": "asserted"},
        {"s": "P", "t": "n3", "rel": "has_measurement", "prov": "asserted"},
        {"s": "n2", "t": "n3", "rel": "followed_by", "prov": "asserted", "time": {"window": [23, 23], "unit": "d"}},
        {"s": "n2", "t": "n4", "rel": "targets", "prov": "context", "bpn_score": 0.81},
        {"s": "n4", "t": "n5", "rel": "participates_in", "prov": "context", "bpn_score": 0.64}],
}
FAKE_M2: dict = {
    "motif_id": "M2", "anchor": "n1",
    "nodes": [
        {"id": "P", "type": "Patient", "role": "patient"},
        {"id": "n1", "type": "Disorder", "code": T2DM, "polarity": "present", "role": "anchor"},
        {"id": "n2", "type": "Disorder", "code": T1DM, "polarity": "absent", "role": "modifier"},
        {"id": "n3", "type": "Substance", "code": MET, "polarity": "present", "role": "exposure"},
        {"id": "n4", "type": "Disorder", "code": CKD, "polarity": "present", "role": "modifier"},
        {"id": "n5", "type": "Observable", "code": GFR, "polarity": "present", "role": "outcome",
         "value": {"interval": [42, 42], "unit": "mL/min/1.73m2"}},
        {"id": "n6", "type": "Disorder", "label": "Lactic acidosis", "code": "MESH:PLACEHOLDER-LACTIC-ACIDOSIS",
         "polarity": "present", "role": "context"}],
    "edges": [
        {"s": "P", "t": "n1", "rel": "has_condition", "prov": "asserted"},
        {"s": "P", "t": "n2", "rel": "has_condition", "prov": "asserted"},
        {"s": "P", "t": "n3", "rel": "administered_drug", "prov": "asserted"},
        {"s": "P", "t": "n4", "rel": "has_condition", "prov": "asserted"},
        {"s": "P", "t": "n5", "rel": "has_measurement", "prov": "asserted"},
        {"s": "n3", "t": "n5", "rel": "followed_by", "prov": "asserted", "time": {"window": [180, 180], "unit": "d"}},
        {"s": "n3", "t": "n6", "rel": "associated_with", "prov": "context", "bpn_score": 0.72}],
}


def fake_hierarchy() -> Hierarchy:
    active = (set(FAKE_ISA) | {p for ps in FAKE_ISA.values() for p in ps}) - {RA_OLD_PARENT}
    return Hierarchy.from_maps(FAKE_ISA, FAKE_FSN, active, FAKE_RELEASE, FAKE_RELEASE)


DISORDERS = (DISEASE, MALIG, NEO_BREAST, MAL_THORAX, BRCA, DM, T1DM, T2DM, RA, CKD)
SUBSTANCES = (ANTHRA, DOX, DAUNO, BIGUANIDE, MET, STRUCT)
FAKE_ATTRS: dict[str, tuple[tuple[str, str, str], ...]] = {
    **{c: ((FSITE, BODY, "1"),) for c in DISORDERS}, **{c: ((DISP, DISPV, "0"),) for c in SUBSTANCES},
    LVEF: ((COMP, COMPV, "0"),), GFR: ((COMP, COMPV, "0"),)}
FAKE_DOMAINS = ((FIND, f"<< {FIND}"), (SUBST, f"<< {SUBST}"), (OBS, f"<< {OBS}"))
FAKE_ATTR_DOMAINS = ((FSITE, FIND), (DISP, SUBST), (COMP, OBS))
FAKE_RANGES = {FSITE: (("<<", BODY),), DISP: (("<<", DISPV),), COMP: (("<<", COMPV),)}


def fake_concept_model(extra_disorders: tuple[str, ...] = ()) -> ConceptModel:
    """``extra_disorders``: test-only concepts given the disorders' synthetic definition."""
    mrcm = Mrcm(tuple(MrcmDomain(c, k, "<<", c, None) for c, k in FAKE_DOMAINS), frozenset(FAKE_ATTR_DOMAINS),
                {"source": "fake"}, dict(FAKE_RANGES))
    concepts = (frozenset(FAKE_FSN) | set(extra_disorders)) - {RA_OLD_PARENT}
    attrs = {**FAKE_ATTRS, **{c: ((FSITE, BODY, "1"),) for c in extra_disorders}}
    return ConceptModel(mrcm, attrs, {"source": "fake"}, primitive=concepts, owl_axiom=concepts,
                        owl_defined=frozenset(), owl_available=True)


def fake_lift(h: Hierarchy, cm: ConceptModel | None = None) -> SnomedLift:
    return SnomedLift(h, cm or fake_concept_model())


fake_boundary_policy = fake_lift   # name kept for existing callers


def write_fake_rf2(directory: Path) -> Path:
    """Write the fake hierarchy as a minimal RF2 Snapshot (inferred IS-A, FSNs; ``RA_OLD_PARENT`` inactive), so CLI
    runs load exactly ``fake_hierarchy()``. Returns ``directory``."""
    from semgen.snomed import FSN_TYPE, INFERRED, IS_A
    directory.mkdir(parents=True, exist_ok=True)
    ids = sorted(set(FAKE_ISA) | {p for ps in FAKE_ISA.values() for p in ps})
    module, t = "900000000000207008", "\t".join
    concepts = [t(["id", "effectiveTime", "active", "moduleId", "definitionStatusId"])] + [
        t([c, "20990101", "0" if c == RA_OLD_PARENT else "1", module, "900000000000074008"]) for c in ids]
    descriptions = [t(["id", "effectiveTime", "active", "moduleId", "conceptId", "languageCode", "typeId", "term",
                       "caseSignificanceId"])] + [
        t([str(i), "20990101", "1", module, c, "en", FSN_TYPE, FAKE_FSN[c], "900000000000448009"])
        for i, c in enumerate(ids, 1)]
    pairs = sorted((c, p) for c, ps in FAKE_ISA.items() for p in ps)
    relationships = [t(["id", "effectiveTime", "active", "moduleId", "sourceId", "destinationId", "relationshipGroup",
                        "typeId", "characteristicTypeId", "modifierId"])] + [
        t([str(i), "20990101", "1", module, c, p, "0", IS_A, INFERRED, "900000000000451002"])
        for i, (c, p) in enumerate(pairs, 1)]
    attrs = sorted((c, t, v, g) for c, rs in FAKE_ATTRS.items() for t, v, g in rs)
    relationships += [t([str(len(pairs) + i), "20990101", "1", module, c, v, g, ty, INFERRED, "900000000000451002"])
                      for i, (c, ty, v, g) in enumerate(attrs, 1)]
    owl = [t(["id", "effectiveTime", "active", "moduleId", "refsetId", "referencedComponentId", "owlExpression"])] + [
        t([f"owl-{c}", "20990101", "1", module, "733073007", c, f"SubClassOf(:{c} :{min(FAKE_ISA.get(c) or {ROOT})})"])
        for c in ids if c != RA_OLD_PARENT]
    meta = directory.parent / "Refset" / "Metadata"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "der2_sssssssRefset_MRCMDomainSnapshot_INT_20990101.txt").write_text("\n".join(
        [t(["id", "effectiveTime", "active", "moduleId", "refsetId", "referencedComponentId", "domainConstraint",
            "parentDomain", "proximalPrimitiveConstraint", "proximalPrimitiveRefinement",
            "domainTemplateForPrecoordination", "domainTemplateForPostcoordination", "guideURL"])]
        + [t([f"d{c}", "20990101", "1", module, "723560006", c, k, "", k, "", "", "", ""]) for c, k in FAKE_DOMAINS])
        + "\n", encoding="utf-8")
    (meta / "der2_cissccRefset_MRCMAttributeDomainSnapshot_INT_20990101.txt").write_text("\n".join(
        [t(["id", "effectiveTime", "active", "moduleId", "refsetId", "referencedComponentId", "domainId", "grouped",
            "attributeCardinality", "attributeInGroupCardinality", "ruleStrengthId", "contentTypeId"])]
        + [t([f"a{a}{d}", "20990101", "1", module, "723561005", a, d, "1", "0..*", "0..1", "723597001", "723596005"])
           for a, d in FAKE_ATTR_DOMAINS]) + "\n", encoding="utf-8")
    (meta / "der2_ssccRefset_MRCMAttributeRangeSnapshot_INT_20990101.txt").write_text("\n".join(
        [t(["id", "effectiveTime", "active", "moduleId", "refsetId", "referencedComponentId", "rangeConstraint",
            "attributeRule", "ruleStrengthId", "contentTypeId"])]
        + [t([f"r{a}", "20990101", "1", module, "723562003", a, " OR ".join(f"{o} {f}" for o, f in r), "",
              "723597001", "723596005"]) for a, r in FAKE_RANGES.items()]) + "\n", encoding="utf-8")
    for name, rows in (("sct2_Concept_Snapshot_INT_20990101.txt", concepts),
                       ("sct2_sRefset_OWLExpressionSnapshot_INT_20990101.txt", owl),
                       ("sct2_Description_Snapshot-en_INT_20990101.txt", descriptions),
                       ("sct2_Relationship_Snapshot_INT_20990101.txt", relationships)):
        (directory / name).write_text("\n".join(rows) + "\n", encoding="utf-8")
    return directory
