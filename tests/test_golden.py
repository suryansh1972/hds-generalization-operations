"""Golden regression check: today's lattice output must equal the saved golden files.

See tests/fixtures/golden/GENERATED_BY.md. A diff here is a regression; never regenerate the files to pass.
``*_lift`` (concept lift only) was generated once from HEAD d450156 and is permanent; ``*_full`` was replaced
once in Task 2 (operators changed) and is checked against the Task 2 operator list from then on.
"""
import copy
from pathlib import Path

import pytest

from semgen.config import load_config
from semgen.context import build_lift
from semgen.export import write_lattice
from semgen.lattice import Budget, enumerate_lattice
from semgen.motif_io import load_motifs, parse_motif
from semgen.operators.attribute_aggregation import attribute_aggregation
from semgen.operators.attribute_deletion import attribute_deletion
from semgen.operators.base import GenContext
from semgen.operators.concept_lift import concept_lift
from semgen.operators.normative_bucketing import normative_bucketing
from semgen.snomed import load_rf2
from tests.support.fake_snomed import CONFIG_PATH, FAKE_M1, FAKE_M2, fake_boundary_policy, fake_hierarchy
from tests.support.ops import with_ops

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "tests" / "fixtures" / "golden"
# ``full`` is the Task 2 operator list (the *_full files were replaced once in Task 2; HEAD's are under head/).
OPS = {"full": [concept_lift, normative_bucketing, attribute_deletion, attribute_aggregation], "lift": [concept_lift]}
CASES = [(f"{src}_{ops}", mid) for src, mids in (("fake", ("M1", "M2")), ("real", ("M1", "M2", "M3", "M4")))
         for ops in ("full", "lift") for mid in mids]


def _fake():
    h = fake_hierarchy()
    ctx = GenContext(h, load_config(CONFIG_PATH), fake_boundary_policy(h))
    return ctx, {m["motif_id"]: parse_motif(copy.deepcopy(m), None) for m in (FAKE_M1, FAKE_M2)}


_REAL: dict = {}


def _real():
    if not _REAL:
        from tests.conftest import require_rf2
        d = require_rf2()
        h = load_rf2(d)
        cfg = load_config(CONFIG_PATH)
        _REAL["v"] = (GenContext(h, cfg, build_lift(h, d)),
                      {m.motif_id: m for m in load_motifs(REPO / "data" / "motifs" / "synthetic_motifs.json", h)})
    return _REAL["v"]


@pytest.mark.parametrize("case,mid", [pytest.param(c, m, id=f"{c}-{m}",
                                                   marks=[pytest.mark.snomed] if c.startswith("real") else [])
                                      for c, m in CASES])
def test_golden(case, mid, tmp_path, monkeypatch):
    src, ops = case.split("_")
    if not (GOLDEN / case / mid).is_dir():
        # real_* outputs carry SNOMED CT content derived from the licensed release: kept locally, never published
        pytest.skip(f"golden outputs {case}/{mid} are local-only (derived from the licensed SNOMED CT release)")
    ctx, motifs = _fake() if src == "fake" else _real()
    lat = enumerate_lattice(motifs[mid], with_ops(ctx, *OPS[ops]), Budget(max_depth=4 if src == "fake" else 2, max_states=10**9))
    write_lattice(lat, mid, tmp_path, {})
    for name in ("candidates.jsonl", "edges.jsonl"):
        assert (tmp_path / mid / name).read_bytes() == (GOLDEN / case / mid / name).read_bytes(), name
