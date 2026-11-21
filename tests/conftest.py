import copy
import os
import tempfile
from pathlib import Path

# Parsed-release caches go to a throwaway directory unless the developer points SEMGEN_CACHE_DIR somewhere (e.g. to
# reuse a cache of the full release); tests never write into the user's cache.
os.environ.setdefault("SEMGEN_CACHE_DIR", tempfile.mkdtemp(prefix="semgen-test-cache-"))

import pytest

from semgen.motif_io import load_motifs, parse_motif
from semgen.snomed import default_rf2_dir, load_rf2

# Fake concept constants live in tests.support.fake_snomed (shared with the golden generator); re-exported here.
from tests.support.fake_snomed import (  # noqa: F401
    ANTHRA,
    BIGUANIDE,
    BRCA,
    CKD,
    DAUNO,
    DISEASE,
    DM,
    DOX,
    FAKE_M1,
    FAKE_M2,
    GFR,
    LVEF,
    MAL_THORAX,
    MALIG,
    MET,
    NEO_BREAST,
    OBS,
    RA,
    RA_OLD_PARENT,
    ROOT,
    STRUCT,
    SUBST,
    T1DM,
    T2DM,
    fake_boundary_policy,
    fake_hierarchy,
)


@pytest.fixture
def fake_h():
    return fake_hierarchy()


def require_rf2() -> Path:
    """The licensed release named by SEMGEN_RF2_DIR; tests that need it are skipped when it is unset or missing."""
    d = default_rf2_dir()
    if d is None or not d.exists():
        pytest.skip("SNOMED CT RF2 release not available (set SEMGEN_RF2_DIR to run real-SNOMED tests)")
    return d


@pytest.fixture(scope="session")
def real_h():
    return load_rf2(require_rf2())


# --- motif fixtures (Task 4) -------------------------------------------------
_FAKE_M1, _FAKE_M2 = FAKE_M1, FAKE_M2


@pytest.fixture
def fake_m1():
    return parse_motif(copy.deepcopy(_FAKE_M1), None)


@pytest.fixture
def fake_m2():
    return parse_motif(copy.deepcopy(_FAKE_M2), None)


@pytest.fixture(scope="session")
def real_motifs(real_h):
    return load_motifs(Path(__file__).resolve().parent.parent / "data/motifs/synthetic_motifs.json", real_h)


# --- operator fixtures (Task 6); SNOMED-only concept lift (semgen.lift) ------------------
from semgen.config import load_config  # noqa: E402
from semgen.context import build_lift  # noqa: E402
from semgen.model import Motif  # noqa: E402
from semgen.operators.base import GenContext  # noqa: E402
from semgen.settings import default_config_path  # noqa: E402

_CONFIG_PATH = default_config_path()


@pytest.fixture
def ctx(fake_h):
    return GenContext(fake_h, load_config(_CONFIG_PATH), fake_boundary_policy(fake_h))


@pytest.fixture(scope="session")
def real_ctx(real_h):
    from semgen.context import open_ucum
    cfg = load_config(_CONFIG_PATH)
    return GenContext(real_h, cfg, build_lift(real_h, default_rf2_dir()), ucum=open_ucum(cfg.ucum))


def one_node_motif(code) -> Motif:
    return parse_motif({
        "motif_id": "ONE", "anchor": "n1",
        "nodes": [{"id": "P", "type": "Patient", "role": "patient"},
                  {"id": "n1", "type": "Disorder", "code": code, "polarity": "present", "role": "anchor"}],
        "edges": [{"s": "P", "t": "n1", "rel": "has_condition", "prov": "asserted"}]}, None)
