"""Identical inputs and budgets (without a wall-clock cutoff) give byte-identical output (design §3, §12; C3).

No test here uses ``--time-budget``: a run it stops is not covered by the byte-identity guarantee.
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.support.fake_snomed import BIGUANIDE, DOX, MET, T1DM, T2DM, write_fake_rf2
from tests.test_lattice_bundles import _cli, cli_env


def _motif(mid: str, typ: str, code: str, rel: str, **node) -> dict:
    return {"motif_id": mid, "anchor": "d",
            "nodes": [{"id": "P", "type": "Patient", "role": "patient"},
                      {"id": "d", "type": typ, "code": code, "role": "anchor", **node}],
            "edges": [{"s": "P", "t": "d", "rel": rel, "prov": "asserted"}]}


def bundle_file(tmp_path: Path) -> Path:
    """Three bundles (``all`` with aggregation and deletion, ``any``, unknown semantics) plus clashing node ids."""
    drug = _motif("A", "Substance", DOX, "administered_drug")
    bundles = [
        {"bundle_id": "B_all", "semantics": "all", "anchor_motif": "A", "subject": {"sex": "female", "age_days": 20000},
         "motifs": [drug, _motif("M1", "Disorder", T1DM, "has_condition"),
                    _motif("M2", "Disorder", T2DM, "has_condition",
                           attrs={"age_at_dx": {"interval": [50, 50], "unit": "a"}})]},
        {"bundle_id": "B_any", "semantics": "any", "anchor_motif": "A",
         "motifs": [drug, _motif("M1", "Disorder", T1DM, "has_condition"),
                    _motif("M2", "Substance", MET, "administered_drug")]},
        {"bundle_id": "B_unknown", "anchor_motif": "A",
         "motifs": [drug, _motif("M1", "Substance", BIGUANIDE, "administered_drug")]},
    ]
    f = tmp_path / "bundles.json"
    f.write_text(json.dumps({"bundles": bundles}))
    return f


def _tree(d: Path) -> dict[str, bytes]:
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def _run_twice(tmp_path: Path, *budget: str) -> tuple[dict, dict, list]:
    rf2, motifs, env = write_fake_rf2(tmp_path / "rf2"), bundle_file(tmp_path), cli_env(tmp_path)
    trees, terms = [], []
    for run in ("a", "b"):
        out = tmp_path / run
        r = _cli("run", "--motifs", str(motifs), "--rf2", str(rf2), *budget, "--out", str(out), env=env)
        assert r.returncode == 0, r.stderr
        trees.append(_tree(out))
        terms.append({b: json.loads((out / b / "termination.json").read_text()) for b in ("B_all", "B_any", "B_unknown")})
    return trees[0], trees[1], terms


def test_two_cli_runs_identical(tmp_path):
    a, b, terms = _run_twice(tmp_path, "--progress")
    assert a == b   # every file, byte for byte (diff -r), the streamed progress files included
    assert {k.split("/")[0] for k in a} == {"B_all", "B_any", "B_unknown"}
    streamed = [json.loads(line) for line in a["B_all/progress.jsonl"].decode().splitlines()]
    final = [json.loads(line) for line in a["B_all/candidates.jsonl"].decode().splitlines()]
    assert sorted(streamed, key=lambda r: (r["depth"], r["hash"])) == final   # same rows; final file sorted
    assert all(t["status"] == "exhausted" and t["complete"] for t in terms[0].values())
    rows = [json.loads(line) for line in a["B_all/candidates.jsonl"].decode().splitlines()]
    assert any("bundle" in r for r in rows) and rows[0]["depth"] == 0


def test_two_bounded_runs_identical(tmp_path):
    a, b, terms = _run_twice(tmp_path, "--max-states", "12", "--max-depth-budget", "2")
    assert a == b
    t = terms[0]["B_all"]
    assert t["status"] == "budget_limited" and t["budget"] == {"max_states": 12, "max_depth": 2, "seconds": None}
