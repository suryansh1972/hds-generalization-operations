import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import semgen.floors as floors_mod
from semgen.config import ConfigError
from semgen.context import build_context
from semgen.export import run_header
from semgen.floors import PhecodeFloorPolicy
from semgen.icd10map import Icd10Map
from semgen.snomed_floor import SnomedBoundaryPolicy
from semgen.sources import SourceError

REPO = Path(__file__).resolve().parents[1]
CFG = REPO / "config" / "generalization.yaml"
FIX = str(Path(__file__).resolve().parent / "fixtures" / "rf2")


@pytest.fixture
def cfg_path(tmp_path):
    raw = yaml.safe_load(CFG.read_text())
    raw["floor_policy"]["snomed_boundary"]["excluded_ancestor_roots"] = [
        {"fsn": "Bee (disorder)", "reason": "fixture exclusion"}]
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml.safe_dump(raw))
    return p


def _no_phecodex(*a, **k):
    raise AssertionError("PhecodeX touched in snomed_boundary mode")


def test_default_context_uses_snomed_boundary(cfg_path):
    ctx = build_context(cfg_path, FIX)
    assert isinstance(ctx.floors, SnomedBoundaryPolicy)


def test_snomed_mode_does_not_touch_phecodex(cfg_path, monkeypatch):
    monkeypatch.setattr(floors_mod, "verify_phecodex", _no_phecodex)
    monkeypatch.setattr(floors_mod, "load_icd10_map", _no_phecodex)
    assert isinstance(build_context(cfg_path, FIX).floors, SnomedBoundaryPolicy)


def test_phecodex_mode_selected_on_fixture(cfg_path, monkeypatch):
    monkeypatch.setattr(floors_mod, "verify_phecodex", lambda d, src: None)
    monkeypatch.setattr(floors_mod, "load_icd10_map", lambda *a, **k: Icd10Map.from_maps({}))
    ctx = build_context(cfg_path, FIX, REPO / "tests" / "fixtures" / "phecodex", floor_mode="phecodex")
    assert isinstance(ctx.floors, PhecodeFloorPolicy) and ctx.floors.provenance["mode"] == "phecodex"


@pytest.mark.snomed
@pytest.mark.phecodex
def test_phecodex_mode_selectable_real_data(real_h, real_floors):
    ctx = build_context(CFG, floor_mode="phecodex")
    assert isinstance(ctx.floors, PhecodeFloorPolicy) and ctx.floors.provenance["mode"] == "phecodex"


def test_phecodex_missing_files_fail_not_fallback(cfg_path, tmp_path):
    with pytest.raises(SourceError):
        build_context(cfg_path, FIX, tmp_path, floor_mode="phecodex")


def test_unknown_mode_raises(cfg_path):
    with pytest.raises(ConfigError):
        build_context(cfg_path, FIX, floor_mode="bogus")


def test_override_without_config_block_raises(cfg_path, tmp_path):
    raw = yaml.safe_load(cfg_path.read_text())
    del raw["floor_source"]
    p = tmp_path / "nosrc.yaml"
    p.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError, match="floor_source"):
        build_context(p, FIX, floor_mode="phecodex")
    raw = yaml.safe_load(cfg_path.read_text())
    raw["floor_policy"] = {"mode": "phecodex"}
    p2 = tmp_path / "noblock.yaml"
    p2.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError, match="snomed_boundary"):
        build_context(p2, FIX, floor_mode="snomed_boundary")


def test_header_records_snomed_policy_and_draft(cfg_path):
    h = run_header(build_context(cfg_path, FIX), cfg_path, 2)
    assert h["config_status"].startswith("DRAFT") and "max_candidates" in h
    fp = h["floor_policy"]
    assert fp["mode"] == "snomed_boundary" and fp["status"].startswith("DRAFT")
    assert fp["max_descendants"] == 2500 and fp["characteristic_type"] == "inferred"
    assert fp["snomed_release"] and fp["snomed_edition"] and h["snomed_edition"] == fp["snomed_edition"]
    assert h["snomed_release"] == fp["snomed_release"] and fp["excluded_ancestor_roots"] == [
        {"concept_id": "B", "fsn": "Bee (disorder)", "reason": "fixture exclusion"}]
    assert "phecodex_commit" not in h and "floor_source" not in h and "source_licences" not in h


def test_header_phecodex_keeps_legacy_keys(ctx):
    h = run_header(ctx, CFG, 3)
    legacy = {"floor_source", "phecode_level", "icd10_map_refset", "icd10_map_release", "phecodex_commit",
              "phecodex_sha256", "ccsr_check", "source_licences"}
    common = {"snomed_release", "snomed_edition", "config_sha256", "config_status", "lvef_convention",
              "temporal_semantics", "absent_semantics", "max_depth", "semgen_version"}
    assert set(h) == legacy | common | {"floor_policy", "max_candidates"}
    assert h["floor_policy"]["mode"] == "phecodex"


def test_header_other_mode_writes_common_keys_only(fake_h, cfg_path):
    from semgen.config import load_config
    from semgen.operators.base import GenContext
    from tests.support.hierarchy_graph import AllowExcept
    h = run_header(GenContext(fake_h, load_config(cfg_path), AllowExcept(set())), cfg_path, 1)
    assert h["floor_policy"] == {"mode": "test"} and "floor_source" not in h


def _cli(*args, mod="semgen"):
    return subprocess.run([sys.executable, "-m", mod, *args], capture_output=True, text=True, cwd=REPO)


def test_cli_phecodex_flag_conflict_exit_1(tmp_path):
    for mod, extra in (("semgen", ["run", "--out", str(tmp_path / "o")]), ("semgen.floor_report", [])):
        r = _cli(*extra, "--motifs", "x.json", "--phecodex", str(tmp_path), mod=mod)
        assert r.returncode == 1 and r.stderr.startswith("error:") and "Traceback" not in r.stderr
        assert "--phecodex" in r.stderr and "snomed_boundary" in r.stderr


MOTIFS = str(REPO / "data" / "motifs" / "synthetic_motifs.json")
LEGACY = {"floor_source", "phecode_level", "icd10_map_refset", "icd10_map_release", "phecodex_commit",
          "phecodex_sha256", "ccsr_check", "source_licences"}


@pytest.mark.snomed
def test_cli_run_default_writes_snomed_header(tmp_path, real_h):
    r = _cli("run", "--motifs", MOTIFS, "--depth", "1", "--out", str(tmp_path))
    assert r.returncode == 0, r.stderr
    dirs = [d for d in tmp_path.iterdir() if d.is_dir()]
    assert len(dirs) == 4
    for d in dirs:
        h = json.loads((d / "run_header.json").read_text())
        assert h["floor_policy"]["mode"] == "snomed_boundary" and not (LEGACY & set(h))


def _report(*extra):
    r = _cli("--motifs", MOTIFS, *extra, mod="semgen.floor_report")
    assert r.returncode == 0, r.stderr
    head, *lines = r.stdout.splitlines()
    return [dict(zip(head.split("\t"), l.split("\t"))) for l in lines]


@pytest.mark.snomed
@pytest.mark.phecodex
def test_cli_floor_report_policy_flag_selects_phecodex(real_h, real_floors):
    px = [r for r in _report("--floor-policy", "phecodex") if r["motif_id"] == "M1" and r["node"] == "n1"]
    assert any(r["decision"] == "outside_floor" and r["anchors"] for r in px)
    sb = [r for r in _report() if r["motif_id"] == "M1" and r["node"] == "n1"]
    assert sb and not any(r["decision"] == "outside_floor" for r in sb) and not any(r["anchors"] for r in sb)


@pytest.mark.parametrize("args,mod", [(["run", "--out", "OUT"], "semgen"), ([], "semgen.floor_report")])
def test_cli_unresolved_excluded_fsn_exit_1(tmp_path, args, mod):
    args = [str(tmp_path / "o") if a == "OUT" else a for a in args]
    r = _cli(*args, "--motifs", MOTIFS, "--rf2", FIX, mod=mod)   # default config's excluded FSN is absent from the fixture RF2
    assert r.returncode == 1 and r.stderr.startswith("error:") and "Traceback" not in r.stderr
