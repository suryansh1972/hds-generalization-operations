import pytest

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
