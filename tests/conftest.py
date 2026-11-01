import copy
from pathlib import Path

import pytest

from semgen.motif_io import load_motifs, parse_motif
from semgen.snomed import Hierarchy, default_rf2_dir, load_rf2

ROOT, DISEASE, MALIG, NEO_BREAST, MAL_THORAX, BRCA = "138875005", "64572001", "363346000", "126926005", "188361007", "254837009"
DM, T1DM, T2DM, RA, RA_OLD_PARENT = "73211009", "46635009", "44054006", "69896004", "900000000000000001"  # last: inactive
CKD, BIGUANIDE, MET = "709044004", "1363127000", "372567009"
SUBST, ANTHRA, DOX, DAUNO = "105590001", "372540003", "372817009", "372715008"
OBS, LVEF, GFR = "363787002", "250908004", "80274001"


_ISA = {
    DISEASE: {ROOT}, MALIG: {DISEASE}, NEO_BREAST: {DISEASE}, MAL_THORAX: {MALIG},
    BRCA: {NEO_BREAST, MAL_THORAX}, DM: {DISEASE}, T1DM: {DM}, T2DM: {DM}, CKD: {DISEASE},
    RA: {DISEASE, RA_OLD_PARENT}, SUBST: {ROOT}, ANTHRA: {SUBST}, DOX: {ANTHRA},
    DAUNO: {ANTHRA}, BIGUANIDE: {SUBST}, MET: {BIGUANIDE}, OBS: {ROOT}, LVEF: {OBS}, GFR: {OBS},
    ROOT: set(),
}


@pytest.fixture
def fake_h():
    active = (set(_ISA) | {p for ps in _ISA.values() for p in ps}) - {RA_OLD_PARENT}
    return Hierarchy.from_maps(_ISA, {}, active)


@pytest.fixture(scope="session")
def real_h():
    d = default_rf2_dir()
    if not d.exists():
        pytest.skip(f"RF2 directory not found: {d}")
    return load_rf2(d)


# --- motif fixtures (Task 4) -------------------------------------------------
_OPT_GENE, _OPT_PATHWAY = "ENSG00000077097", "REACT:R-HSA-PLACEHOLDER-1"
_FAKE_M1 = {
    "motif_id": "M1", "anchor": "n1",
    "nodes": [
        {"id": "P", "type": "Patient", "role": "patient"},
        {"id": "n1", "type": "Disorder", "code": BRCA, "polarity": "present", "role": "anchor",
         "attrs": {"age_at_dx": {"interval": [67, 67], "unit": "a"}}},
        {"id": "n2", "type": "Substance", "code": DOX, "polarity": "present", "role": "exposure",
         "attrs": {"cumulative_dose": {"interval": [360, 360], "unit": "mg/m2"}}},
        {"id": "n3", "type": "Observable", "code": LVEF, "polarity": "present", "role": "outcome",
         "value": {"interval": [38, 38], "unit": "%"}},
        {"id": "n4", "type": "Gene", "label": "TOP2B", "code": _OPT_GENE, "polarity": "present", "role": "context"},
        {"id": "n5", "type": "Pathway", "label": "DNA topoisomerase II pathway", "code": _OPT_PATHWAY,
         "polarity": "present", "role": "context"}],
    "edges": [
        {"s": "P", "t": "n1", "rel": "has_condition", "prov": "asserted"},
        {"s": "P", "t": "n2", "rel": "administered_drug", "prov": "asserted"},
        {"s": "P", "t": "n3", "rel": "has_measurement", "prov": "asserted"},
        {"s": "n2", "t": "n3", "rel": "followed_by", "prov": "asserted", "time": {"window": [23, 23], "unit": "d"}},
        {"s": "n2", "t": "n4", "rel": "targets", "prov": "context", "bpn_score": 0.81},
        {"s": "n4", "t": "n5", "rel": "participates_in", "prov": "context", "bpn_score": 0.64}],
}
_FAKE_M2 = {
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


@pytest.fixture
def fake_m1():
    return parse_motif(copy.deepcopy(_FAKE_M1), None)


@pytest.fixture
def fake_m2():
    return parse_motif(copy.deepcopy(_FAKE_M2), None)


@pytest.fixture(scope="session")
def real_motifs(real_h):
    return load_motifs(Path(__file__).resolve().parent.parent / "data/motifs/synthetic_motifs.json", real_h)
