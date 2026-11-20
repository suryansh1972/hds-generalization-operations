"""UCUM validation against the pinned essence file (skips when it is not on disk)."""
from pathlib import Path

import pytest

from semgen.config import load_config
from semgen.context import open_ucum
from semgen.ucum import Ucum

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ucum():
    u = open_ucum(load_config().ucum)
    if u is None:
        pytest.skip("UCUM essence not available (set SEMGEN_UCUM_ESSENCE)")
    return u


@pytest.mark.parametrize("unit", ["mmol/L", "meq/L", "U/L", "%", "mg/dL", "10*9/L", "mL/min/{1.73_m2}", "kg/m2",
                                  "/uL", "a", "mm[Hg]", "g.m-2", "{cells}/uL", "mg/(24.h)"])
def test_valid(ucum, unit):
    assert ucum.is_valid(unit), unit


@pytest.mark.parametrize("unit", ["mEq/L", "MG/DL", "mg/ dL", "foo", "mL/min/1.73m2", "", "mg/(dL", "U/LL"])
def test_invalid(ucum, unit):
    assert not ucum.is_valid(unit), unit


def test_sha_mismatch_rejected(tmp_path):
    p = tmp_path / "u.xml"
    p.write_text('<root version="x"/>')
    with pytest.raises(ValueError):
        Ucum.load(p, "0" * 64)
