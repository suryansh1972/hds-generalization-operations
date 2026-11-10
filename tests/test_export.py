import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from semgen.export import run_header, write_lattice
from semgen.lattice import enumerate_lattice

REPO = Path(__file__).resolve().parents[1]
CFG = str(REPO / "config" / "generalization.yaml")
MOTIFS = str(REPO / "data" / "motifs" / "synthetic_motifs.json")
R11_KEYS = {"snomed_release", "snomed_edition", "config_sha256", "config_status", "lvef_convention",
            "temporal_semantics", "absent_semantics", "max_depth", "semgen_version", "floor_source",
            "phecode_level", "icd10_map_refset", "icd10_map_release", "phecodex_commit",
            "phecodex_sha256", "ccsr_check", "source_licences", "floor_policy", "max_candidates"}


def test_files_and_header(tmp_path, ctx, fake_m1):
    lat = enumerate_lattice(fake_m1, ctx, 2)
    paths = write_lattice(lat, "M1", tmp_path, run_header(ctx, CFG, 2))
    hdr = json.loads(paths["run_header"].read_text())
    assert hdr["temporal_semantics"] == "certain" and hdr["config_status"].startswith("DRAFT") and len(hdr["config_sha256"]) == 64
    assert hdr["floor_source"] == "phecodex" and len(hdr["phecodex_sha256"]) == 3 and hdr["ccsr_check"] == "unavailable"
    rows = [json.loads(l) for l in paths["candidates"].read_text().splitlines()]
    assert len(rows) == len(lat.candidates) and rows[0]["depth"] == 0
    edge = json.loads(paths["edges"].read_text().splitlines()[0]); assert {"parent", "child", "changes"} <= set(edge)


def test_byte_identical_reruns(tmp_path, ctx, fake_m1):
    h = run_header(ctx, CFG, 2)
    a = write_lattice(enumerate_lattice(fake_m1, ctx, 2), "M1", tmp_path / "a", h)
    b = write_lattice(enumerate_lattice(fake_m1, ctx, 2), "M1", tmp_path / "b", h)
    assert all(a[k].read_bytes() == b[k].read_bytes() for k in a)


def _written(tmp_path, ctx, fake_m1):
    lat = enumerate_lattice(fake_m1, ctx, 2)
    h = run_header(ctx, CFG, 2)
    return lat, write_lattice(lat, "M1", tmp_path, h), h


def test_header_exact_keys(ctx):
    h = run_header(ctx, CFG, 3)
    assert set(h) == R11_KEYS
    assert h["max_depth"] == 3 and h["source_licences"] == {"phecodex": ctx.config.floor_source.licence}
    assert h["phecodex_sha256"] == dict(ctx.config.floor_source.files)
    assert h["absent_semantics"].startswith("closed-world")


def test_sorted_orders(tmp_path, ctx, fake_m1):
    lat, p, _ = _written(tmp_path, ctx, fake_m1)
    cand = [json.loads(l) for l in p["candidates"].read_text().splitlines()]
    assert [(r["depth"], r["hash"]) for r in cand] == sorted((r["depth"], r["hash"]) for r in cand)
    edges = [json.loads(l) for l in p["edges"].read_text().splitlines()]
    assert len(edges) == len(lat.edges)
    assert [(r["parent"], r["child"]) for r in edges] == sorted((r["parent"], r["child"]) for r in edges)
    bl = [json.loads(l) for l in p["blocked"].read_text().splitlines()]
    assert len(bl) == len(lat.blocked)
    key = lambda r: (r["from"], r["op"], r["target"], r["reason"], json.dumps(r["detail"], sort_keys=True))
    assert [key(r) for r in bl] == sorted(key(r) for r in bl)


def test_blocked_order_independent_of_insertion(tmp_path, ctx, fake_m1):
    from dataclasses import replace
    lat = enumerate_lattice(fake_m1, ctx, 2)
    rev = replace(lat, blocked=list(reversed(lat.blocked)), edges=list(reversed(lat.edges)))
    h = run_header(ctx, CFG, 2)
    a = write_lattice(lat, "M1", tmp_path / "a", h)
    b = write_lattice(rev, "M1", tmp_path / "b", h)
    assert all(a[k].read_bytes() == b[k].read_bytes() for k in a)


def test_newline_and_no_timestamps(tmp_path, ctx, fake_m1):
    _, p, _ = _written(tmp_path, ctx, fake_m1)
    for path in p.values():
        text = path.read_text()
        assert text.endswith("\n") and "\r" not in text
        assert not re.search(r"\d{4}-\d{2}-\d{2}T", text)


def test_multi_change_edge_keeps_order(tmp_path, ctx, fake_m1):
    from dataclasses import replace
    lat = enumerate_lattice(fake_m1, ctx, 1)
    e = lat.edges[0]
    ch = e.changes[0]
    two = (ch, replace(ch, target="zzz"), replace(ch, target="aaa"))
    lat2 = replace(lat, edges=[replace(e, changes=two)] + lat.edges[1:])
    p = write_lattice(lat2, "M1", tmp_path, run_header(ctx, CFG, 1))
    rows = [json.loads(l) for l in p["edges"].read_text().splitlines()]
    row = next(r for r in rows if r["parent"] == e.parent and r["child"] == e.child)
    assert [c["target"] for c in row["changes"]] == [ch.target, "zzz", "aaa"]


def _cli(*args):
    return subprocess.run([sys.executable, "-m", "semgen", *args], capture_output=True, text=True, cwd=REPO)


def test_cli_help_ok():
    assert _cli("run", "--help").returncode == 0


def test_cli_missing_out_is_usage_error():
    r = _cli("run", "--motifs", "x.json")
    assert r.returncode == 2


def test_cli_bad_config_exit_1():
    r = _cli("run", "--motifs", MOTIFS, "--config", "/nonexistent.yaml", "--out", "/tmp/never")
    assert r.returncode == 1 and r.stderr.strip() and "Traceback" not in r.stderr


@pytest.mark.snomed
@pytest.mark.phecodex
def test_cli_end_to_end(tmp_path, real_ctx):
    r = _cli("run", "--motifs", MOTIFS, "--config", CFG, "--floor-policy", "phecodex",
             "--depth", "1", "--out", str(tmp_path))
    assert r.returncode == 0, r.stderr
    lines = r.stdout.strip().splitlines()
    assert len(lines) == 4 and all(re.fullmatch(r"\S+ depth=1 candidates=\d+ edges=\d+ blocked=\d+ status=\w+", l) for l in lines)
    dirs = [d for d in tmp_path.iterdir() if d.is_dir()]
    assert len(dirs) == 4
    hs = [json.loads((d / "run_header.json").read_text()) for d in dirs]
    assert all(h["max_depth"] == 1 and h["floor_policy"]["mode"] == "phecodex" for h in hs)
    assert all({"floor_source", "phecodex_commit", "phecodex_sha256", "source_licences"} <= set(h) for h in hs)


@pytest.mark.parametrize("bad", ["../x", "/abs", "", ".", "..", "a/b"])
def test_unsafe_motif_id_rejected(tmp_path, ctx, fake_m1, bad):
    from semgen.motif_io import MotifError
    lat = enumerate_lattice(fake_m1, ctx, 0)
    with pytest.raises(MotifError):
        write_lattice(lat, bad, tmp_path / "out", run_header(ctx, CFG, 0))
    assert not list(tmp_path.rglob("*.jsonl"))


def test_normal_motif_id_ok(tmp_path, ctx, fake_m1):
    p = write_lattice(enumerate_lattice(fake_m1, ctx, 0), "M-1_a.b", tmp_path, run_header(ctx, CFG, 0))
    assert p["candidates"].parent == tmp_path / "M-1_a.b"


@pytest.mark.snomed
@pytest.mark.phecodex
def test_cli_duplicate_ids_exit_1_writes_nothing(tmp_path, real_ctx):
    raw = json.loads(Path(MOTIFS).read_text())
    items = raw if isinstance(raw, list) else raw[next(k for k, v in raw.items() if isinstance(v, list))]
    dup = [items[0], items[0]]
    f = tmp_path / "dup.json"
    f.write_text(json.dumps(dup if isinstance(raw, list) else {next(k for k, v in raw.items() if isinstance(v, list)): dup}))
    out = tmp_path / "out"
    r = _cli("run", "--motifs", str(f), "--config", CFG, "--out", str(out))
    assert r.returncode == 1 and "Traceback" not in r.stderr and "duplicate" in r.stderr
    assert not out.exists() or not list(out.rglob("*"))


def test_cli_negative_depth_is_usage_error():
    r = _cli("run", "--motifs", "x.json", "--out", "/tmp/never", "--depth", "-1")
    assert r.returncode == 2 and "Traceback" not in r.stderr


def test_termination_json_written(tmp_path, ctx, fake_m1):
    lat = enumerate_lattice(fake_m1, ctx, 0, climb=False)
    paths = write_lattice(lat, "M1", tmp_path, run_header(ctx, CFG, 0))
    text = paths["termination"].read_text()
    assert text.endswith("\n")
    assert json.loads(text) == {"status": "depth_limited", "complete": False, "max_depth": 0,
                                "max_candidates": ctx.config.max_candidates, "unexpanded_frontier": 1, "candidates": 1,
                                "axes": {}}
    assert text == json.dumps(json.loads(text), sort_keys=True, indent=2) + "\n"


def test_termination_complete_when_exhausted(tmp_path):
    from tests.test_lattice import _gctx, _gm
    c = _gctx()
    lat = enumerate_lattice(_gm(), c, 30)
    paths = write_lattice(lat, "G", tmp_path, {"max_depth": 30, "max_candidates": c.config.max_candidates})
    t = json.loads(paths["termination"].read_text())
    assert t["complete"] is True and t["status"] == "exhausted" and t["max_depth"] == 30


def test_chain_longer_than_depth_is_not_claimed_complete(tmp_path):
    from tests.test_lattice import _gctx, _gm
    c = _gctx()
    lat = enumerate_lattice(_gm(), c, 3)
    paths = write_lattice(lat, "G", tmp_path, {"max_depth": 3, "max_candidates": c.config.max_candidates})
    assert json.loads(paths["termination"].read_text())["complete"] is False


@pytest.mark.parametrize("make", ["budget", "hand_built"])
def test_non_exhausted_lattice_is_not_complete(tmp_path, make):
    from semgen.lattice import Lattice
    from tests.test_lattice import _gctx, _gm
    c = _gctx()
    lat = enumerate_lattice(_gm(), c, 30, 3) if make == "budget" else Lattice("r", {}, [], [])
    paths = write_lattice(lat, "G", tmp_path, {"max_depth": 30, "max_candidates": 3})
    t = json.loads(paths["termination"].read_text())
    assert t["complete"] is False and t["status"] == ("candidate_limited" if make == "budget" else "unknown")


def test_termination_written_last(tmp_path, monkeypatch):
    import semgen.export as E
    from tests.test_lattice import _gctx, _gm
    lat = enumerate_lattice(_gm(), _gctx(), 30)
    real = E._write
    def boom(path, text):
        if path.name == "blocked.jsonl":
            raise OSError("disk full")
        real(path, text)
    monkeypatch.setattr(E, "_write", boom)
    with pytest.raises(OSError):
        write_lattice(lat, "G", tmp_path, {"max_depth": 30, "max_candidates": 3})
    assert not (tmp_path / "G" / "termination.json").exists()


def test_axes_in_termination_json(tmp_path):
    from tests.test_lattice import _gctx, _gm
    c = _gctx({"BLOCKED"})
    lat = enumerate_lattice(_gm(), c, 2)
    paths = write_lattice(lat, "G", tmp_path, {"max_depth": 2, "max_candidates": c.config.max_candidates})
    t = json.loads(paths["termination"].read_text())
    ax = lat.axes["n1"]
    assert t["axes"] == {"n1": {"status": "reached_hierarchy_top", "reached": list(ax.reached),
                                "stopped_by": ["inactive_parent", "no_parent", "outside_floor"]}}
    assert ax.reached == tuple(sorted(ax.reached))
    assert t["status"] == "depth_limited" and t["complete"] is False and t["candidates"] == len(lat.candidates)


def test_origin_in_candidates(tmp_path):
    from tests.test_lattice import _gctx, _gm
    c = _gctx()
    lat = enumerate_lattice(_gm(), c, 1)
    paths = write_lattice(lat, "G", tmp_path, {"max_depth": 1, "max_candidates": c.config.max_candidates})
    rows = [json.loads(l) for l in paths["candidates"].read_text().splitlines()]
    assert {r["hash"]: r["origin"] for r in rows} == {h: x.origin for h, x in lat.candidates.items()}
    assert {r["origin"] for r in rows if r["depth"] <= 1} == {"lattice"} and {r["origin"] for r in rows if r["depth"] > 1} == {"axis"}
    assert [(r["depth"], r["hash"]) for r in rows] == sorted((r["depth"], r["hash"]) for r in rows)


def test_axes_present_and_empty_without_liftable_node(tmp_path):
    from semgen.motif_io import parse_motif
    from tests.test_lattice import _gctx
    m = parse_motif({"motif_id": "NONE", "anchor": "n1",
                     "nodes": [{"id": "P", "type": "Patient", "role": "patient"},
                               {"id": "n1", "type": "Disorder", "code": "SPEC", "polarity": "absent", "role": "anchor"}],
                     "edges": [{"s": "P", "t": "n1", "rel": "has_condition", "prov": "asserted"}]}, None)
    c = _gctx()
    lat = enumerate_lattice(m, c, 1)
    assert lat.axes == {}
    paths = write_lattice(lat, "NONE", tmp_path, {"max_depth": 1, "max_candidates": c.config.max_candidates})
    assert json.loads(paths["termination"].read_text())["axes"] == {}
