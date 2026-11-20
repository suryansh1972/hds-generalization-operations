import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from semgen.export import run_header, write_lattice
from semgen.lattice import Budget, enumerate_lattice

REPO = Path(__file__).resolve().parents[1]
from semgen.settings import default_config_path  # noqa: E402

CFG = str(default_config_path())
MOTIFS = str(REPO / "data" / "motifs" / "synthetic_motifs.json")
R11_KEYS = {"snomed_release", "snomed_edition", "config_sha256", "config_status",
            "temporal_semantics", "absent_semantics", "budget", "attribute_definitions_sha256", "semgen_version",
            "floor_policy", "sources"}


def test_files_and_header(tmp_path, ctx, fake_m1):
    """Rewritten (Task 1): was hdr["floor_source"] == "phecodex" with phecodex_sha256 and ccsr_check; now the
    SNOMED-only floor policy and the pinned attribute definitions are recorded instead."""
    lat = enumerate_lattice(fake_m1, ctx, Budget(max_depth=2))
    paths = write_lattice(lat, "M1", tmp_path, run_header(ctx, CFG, Budget(max_depth=2)))
    hdr = json.loads(paths["run_header"].read_text())
    assert hdr["temporal_semantics"] == "certain" and hdr["config_status"].startswith("DRAFT") and len(hdr["config_sha256"]) == 64
    assert hdr["floor_policy"]["mode"] == "snomed_ontology" and len(hdr["attribute_definitions_sha256"]) == 64
    rows = [json.loads(l) for l in paths["candidates"].read_text().splitlines()]
    assert len(rows) == len(lat.candidates) and rows[0]["depth"] == 0
    edge = json.loads(paths["edges"].read_text().splitlines()[0]); assert {"parent", "child", "changes"} <= set(edge)


def test_byte_identical_reruns(tmp_path, ctx, fake_m1):
    h = run_header(ctx, CFG, Budget(max_depth=2))
    a = write_lattice(enumerate_lattice(fake_m1, ctx, Budget(max_depth=2)), "M1", tmp_path / "a", h)
    b = write_lattice(enumerate_lattice(fake_m1, ctx, Budget(max_depth=2)), "M1", tmp_path / "b", h)
    assert all(a[k].read_bytes() == b[k].read_bytes() for k in a)


def _written(tmp_path, ctx, fake_m1):
    lat = enumerate_lattice(fake_m1, ctx, Budget(max_depth=2))
    h = run_header(ctx, CFG, Budget(max_depth=2))
    return lat, write_lattice(lat, "M1", tmp_path, h), h


def test_header_exact_keys(ctx):
    """Rewritten (Task 1): was the PhecodeX keys plus max_depth == 3 and max_candidates; now budget and
    attribute_definitions_sha256 replace them. Task 2: lvef_convention left with the ladders; sources added."""
    h = run_header(ctx, CFG, Budget(max_depth=3))
    assert set(h) == R11_KEYS
    assert h["budget"] == {"max_states": None, "max_depth": 3, "seconds": None}
    assert h["attribute_definitions_sha256"] == ctx.config.attribute_definitions_sha256
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
    lat = enumerate_lattice(fake_m1, ctx, Budget(max_depth=2))
    rev = replace(lat, blocked=list(reversed(lat.blocked)), edges=list(reversed(lat.edges)))
    h = run_header(ctx, CFG, Budget(max_depth=2))
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
    lat = enumerate_lattice(fake_m1, ctx, Budget(max_depth=1))
    e = lat.edges[0]
    ch = e.changes[0]
    two = (ch, replace(ch, target="zzz"), replace(ch, target="aaa"))
    lat2 = replace(lat, edges=[replace(e, changes=two)] + lat.edges[1:])
    p = write_lattice(lat2, "M1", tmp_path, run_header(ctx, CFG, Budget(max_depth=1)))
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
def test_cli_end_to_end(tmp_path, real_ctx):
    """Rewritten (Task 1): was a --floor-policy phecodex run at --depth 1 asserting the PhecodeX header keys; now
    the default SNOMED-only run, bounded by --max-depth-budget 1 (the search bound) with --depth 1 (the filter)."""
    r = _cli("run", "--motifs", MOTIFS, "--config", CFG, "--max-depth-budget", "1", "--depth", "1",
             "--out", str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert "note:" not in r.stderr
    lines = r.stdout.strip().splitlines()
    assert len(lines) == 4 and all(re.fullmatch(r"\S+ depth=1 candidates=\d+ edges=\d+ blocked=\d+ status=\w+", l) for l in lines)
    dirs = [d for d in tmp_path.iterdir() if d.is_dir()]
    assert len(dirs) == 4
    hs = [json.loads((d / "run_header.json").read_text()) for d in dirs]
    assert all(h["budget"]["max_depth"] == 1 and h["floor_policy"]["mode"] == "snomed_ontology" for h in hs)
    assert not any({"floor_source", "phecodex_commit", "phecodex_sha256", "source_licences"} & set(h) for h in hs)


@pytest.mark.parametrize("bad", ["../x", "/abs", "", ".", "..", "a/b"])
def test_unsafe_motif_id_rejected(tmp_path, ctx, fake_m1, bad):
    from semgen.motif_io import MotifError
    lat = enumerate_lattice(fake_m1, ctx, Budget(max_depth=0))
    with pytest.raises(MotifError):
        write_lattice(lat, bad, tmp_path / "out", run_header(ctx, CFG, Budget(max_depth=0)))
    assert not list(tmp_path.rglob("*.jsonl"))


def test_normal_motif_id_ok(tmp_path, ctx, fake_m1):
    p = write_lattice(enumerate_lattice(fake_m1, ctx, Budget(max_depth=0)), "M-1_a.b", tmp_path, run_header(ctx, CFG, Budget(max_depth=0)))
    assert p["candidates"].parent == tmp_path / "M-1_a.b"


@pytest.mark.snomed
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
    """Rewritten (Task 1): was {"status": "depth_limited", "max_depth": 0, "max_candidates": ...}; now
    budget_limited with the budget, budget_hit and refused."""
    lat = enumerate_lattice(fake_m1, ctx, Budget(max_depth=0), climb=False)
    paths = write_lattice(lat, "M1", tmp_path, run_header(ctx, CFG, Budget(max_depth=0)))
    text = paths["termination"].read_text()
    assert text.endswith("\n")
    assert json.loads(text) == {"status": "budget_limited", "complete": False,
                                "budget": {"max_states": None, "max_depth": 0, "seconds": None},
                                "budget_hit": ["max_depth"], "refused": 0, "unexpanded_frontier": 1, "candidates": 1,
                                "axes": {}, "state_space_estimate": lat.state_space_estimate}
    assert isinstance(lat.state_space_estimate, int) and lat.state_space_estimate > 1
    assert text == json.dumps(json.loads(text), sort_keys=True, indent=2) + "\n"


def test_termination_complete_when_exhausted(tmp_path):
    from tests.test_lattice import _gctx, _gm
    c = _gctx()
    lat = enumerate_lattice(_gm(), c, Budget(max_depth=30))
    paths = write_lattice(lat, "G", tmp_path, {"budget": Budget(max_depth=30).to_json()})
    t = json.loads(paths["termination"].read_text())
    assert t["complete"] is True and t["status"] == "exhausted" and t["budget"]["max_depth"] == 30


def test_chain_longer_than_depth_is_not_claimed_complete(tmp_path):
    from tests.test_lattice import _gctx, _gm
    c = _gctx()
    lat = enumerate_lattice(_gm(), c, Budget(max_depth=3))
    paths = write_lattice(lat, "G", tmp_path, {"budget": Budget(max_depth=3).to_json()})
    assert json.loads(paths["termination"].read_text())["complete"] is False


@pytest.mark.parametrize("make", ["budget", "hand_built"])
def test_non_exhausted_lattice_is_not_complete(tmp_path, make):
    """Rewritten (Task 1): was status "candidate_limited" for the budget run; now budget_limited."""
    from semgen.lattice import Lattice
    from tests.test_lattice import _gctx, _gm
    c = _gctx()
    lat = enumerate_lattice(_gm(), c, Budget(max_depth=30, max_states=3)) if make == "budget" else Lattice("r", {}, [], [])
    paths = write_lattice(lat, "G", tmp_path, {"budget": Budget(max_depth=30, max_states=3).to_json()})
    t = json.loads(paths["termination"].read_text())
    assert t["complete"] is False and t["status"] == ("budget_limited" if make == "budget" else "unknown")


def test_termination_written_last(tmp_path, monkeypatch):
    import semgen.export as E
    from tests.test_lattice import _gctx, _gm
    lat = enumerate_lattice(_gm(), _gctx(), Budget(max_depth=30))
    real = E._write
    def boom(path, text):
        if path.name == "blocked.jsonl":
            raise OSError("disk full")
        real(path, text)
    monkeypatch.setattr(E, "_write", boom)
    with pytest.raises(OSError):
        write_lattice(lat, "G", tmp_path, {})
    assert not (tmp_path / "G" / "termination.json").exists()


def test_axes_in_termination_json(tmp_path):
    """Rewritten (Task 1): was t["status"] == "depth_limited"; now budget_limited, same budget value."""
    from tests.test_lattice import _gctx, _gm
    c = _gctx({"BLOCKED"})
    lat = enumerate_lattice(_gm(), c, Budget(max_depth=2))
    paths = write_lattice(lat, "G", tmp_path, {"budget": Budget(max_depth=2).to_json()})
    t = json.loads(paths["termination"].read_text())
    ax = lat.axes["n1"]
    assert t["axes"] == {"n1": {"status": "reached_floor", "reached": list(ax.reached),
                                "stopped_by": ["defining_attribute_dropped", "inactive_parent", "top_level_concept"]}}
    assert ax.reached == tuple(sorted(ax.reached))
    assert t["status"] == "budget_limited" and t["complete"] is False and t["candidates"] == len(lat.candidates)


def test_origin_in_candidates(tmp_path):
    from tests.test_lattice import _gctx, _gm
    c = _gctx()
    lat = enumerate_lattice(_gm(), c, Budget(max_depth=1))
    paths = write_lattice(lat, "G", tmp_path, {"budget": Budget(max_depth=1).to_json()})
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
    lat = enumerate_lattice(m, c, Budget(max_depth=1))
    assert lat.axes == {}
    paths = write_lattice(lat, "NONE", tmp_path, {"budget": Budget(max_depth=1).to_json()})
    assert json.loads(paths["termination"].read_text())["axes"] == {}


# --- Task 1: --depth is an output filter; budgets bound the search -----------------------------------
FAKE_RF2 = REPO / "tests" / "fixtures" / "rf2"


def _fake_files(tmp_path):
    """The fake M1 motif and a copy of the config (M1's codes are not in the tiny fixture RF2, so concept lift
    blocks as unknown_concept; attribute removal and range coarsening still give depth > 1)."""
    import yaml

    from tests.support.fake_snomed import FAKE_M1
    tmp_path.mkdir(parents=True, exist_ok=True)
    raw = yaml.safe_load(Path(CFG).read_text())
    raw["attribute_definitions"]["path"] = str(Path(CFG).parent / raw["attribute_definitions"]["path"])
    cfg = tmp_path / "cfg.yaml"; cfg.write_text(yaml.safe_dump(raw))
    # Rev 4: deletions need a declared relaxable decision. The bundle declares a cohort relaxing two constraints on
    # the anchor (relationship anchor_self, so no KG is needed): the search still reaches depth 2.
    m1 = json.loads(json.dumps(FAKE_M1))
    m1["nodes"][1]["dates"] = {"onset": "2020-01-01"}
    cohort = {"id": "test", "version": "1", "source": "test_export", "constraints": [
        {"target": "n1", "field": "attrs.age_at_dx", "necessity": "relaxable"},
        {"target": "n1", "field": "dates.onset", "necessity": "relaxable"}]}
    motifs = tmp_path / "m.json"
    motifs.write_text(json.dumps({"bundles": [{"bundle_id": "M1", "cohort_definition": cohort, "motifs": [m1]}]}))
    return cfg, motifs


def _run_fake(tmp_path, *extra):
    cfg, motifs = _fake_files(tmp_path)
    out = tmp_path / "out"
    r = _cli("run", "--motifs", str(motifs), "--config", str(cfg), "--rf2", str(FAKE_RF2), *extra, "--out", str(out))
    assert r.returncode == 0, r.stderr
    d = out / "M1"
    rows = [json.loads(l) for l in (d / "candidates.jsonl").read_text().splitlines()]
    edges = [json.loads(l) for l in (d / "edges.jsonl").read_text().splitlines()]
    return r, rows, edges, json.loads((d / "termination.json").read_text())


def test_cli_depth_filters_output_only(tmp_path):
    r, rows, edges, term = _run_fake(tmp_path, "--depth", "1")
    _, all_rows, all_edges, full = _run_fake(tmp_path / "full")
    assert rows and max(x["depth"] for x in rows) <= 1 < max(x["depth"] for x in all_rows)
    kept = {x["hash"] for x in rows}
    assert kept == {x["hash"] for x in all_rows if x["depth"] <= 1}
    assert edges == [e for e in all_edges if e["parent"] in kept and e["child"] in kept]
    assert term == full and term["status"] == "exhausted" and term["candidates"] == len(all_rows)
    assert re.search(rf"M1 depth=1 candidates={len(rows)} edges={len(edges)} ", r.stdout)
    # blocked rows are filtered the same way (by their ``from`` candidate), and the summary counts what is written
    blocked = (tmp_path / "out" / "M1" / "blocked.jsonl").read_text().splitlines()
    all_blocked = (tmp_path / "full" / "out" / "M1" / "blocked.jsonl").read_text().splitlines()
    assert blocked == [b for b in all_blocked if json.loads(b)["from"] in kept] and len(blocked) < len(all_blocked)
    assert re.search(rf"M1 depth=1 candidates={len(rows)} edges={len(edges)} blocked={len(blocked)} ", r.stdout)


def test_cli_max_depth_budget_bounds_search(tmp_path):
    _, rows, _, term = _run_fake(tmp_path, "--max-depth-budget", "1")
    assert term["status"] == "budget_limited" and term["budget_hit"] == ["max_depth"] and term["complete"] is False
    assert term["budget"] == {"max_states": None, "max_depth": 1, "seconds": None}


def test_cli_depth_without_budget_warns(tmp_path):
    r, *_ = _run_fake(tmp_path, "--depth", "1")
    assert ("note: --depth only filters output; the search is bounded by --max-depth-budget/--max-states/"
            "--time-budget (none given: unbounded)") in r.stderr
    r2, *_ = _run_fake(tmp_path / "b", "--depth", "1", "--max-depth-budget", "1")
    assert "note:" not in r2.stderr


def test_time_budget_run_marked(tmp_path):
    _, rows, _, term = _run_fake(tmp_path, "--time-budget", "0")
    assert term["status"] == "budget_limited" and "seconds" in term["budget_hit"] and term["complete"] is False
    assert term["budget"]["seconds"] == 0


def test_cli_max_states_budget(tmp_path):
    _, rows, _, term = _run_fake(tmp_path, "--max-states", "3")
    assert term["budget_hit"] == ["max_states"] and term["refused"] >= 1 and term["candidates"] >= 3


def test_header_records_mayo_source(ctx, tmp_path, monkeypatch):
    """Updated (Task 4, C3): ``sources.mayo`` no longer records the machine-specific ``path``."""
    import dataclasses

    from semgen.refrange import MayoSource
    from tests.support import mayo_fixture
    monkeypatch.delenv("SEMGEN_MAYO_DB", raising=False)
    h = run_header(ctx, CFG, Budget())
    assert h["sources"] == {"mayo": {"sha256": ctx.config.mayo.sha256, "available": False, "test_map_sha256": None}}
    db = mayo_fixture.build(tmp_path, [])
    tm = mayo_fixture.write_map(tmp_path, [])
    src = MayoSource.open(db, mayo_fixture.sha256(db), tm)
    h = run_header(dataclasses.replace(ctx, refranges=src), CFG, Budget())
    assert h["sources"]["mayo"] == {"sha256": mayo_fixture.sha256(db), "available": True,
                                    "test_map_sha256": mayo_fixture.sha256(tm)}
    src = MayoSource.open(db, mayo_fixture.sha256(db), None)
    assert run_header(dataclasses.replace(ctx, refranges=src), CFG, Budget())["sources"]["mayo"][
        "test_map_sha256"] is None


def _strings(v):
    if isinstance(v, dict):
        for x in v.values():
            yield from _strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from _strings(x)
    elif isinstance(v, str):
        yield v


def test_run_header_has_no_absolute_paths(ctx, tmp_path, monkeypatch):
    """C3: the run header is machine-independent: no string value is an absolute path or names the home directory."""
    import dataclasses

    from semgen.refrange import MayoSource
    from tests.support import mayo_fixture
    monkeypatch.delenv("SEMGEN_MAYO_DB", raising=False)
    db = mayo_fixture.build(tmp_path, [])
    tm = mayo_fixture.write_map(tmp_path, [])
    with_mayo = dataclasses.replace(ctx, refranges=MayoSource.open(db, mayo_fixture.sha256(db), tm))
    home = str(Path.home())
    for c in (ctx, with_mayo):
        values = list(_strings(run_header(c, CFG, Budget(max_states=3))))
        assert values
        bad = [v for v in values if v.startswith("/") or re.match(r"[A-Za-z]:[\\/]", v) or home in v]
        assert not bad, bad
