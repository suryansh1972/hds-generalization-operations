"""The combined bundle lattice (design §9): per-motif operators on every part, the bundle operator (motif deletion),
proofs and monotonicity on synthetic patients. There is no motif aggregation: AND is never turned into OR."""
from __future__ import annotations

import copy
import itertools
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import semgen.lattice as L
from semgen.bundle import MotifBundle
from semgen.lattice import Budget, enumerate_lattice
from semgen.model import PATIENT_ID, Edge, Motif, Node
from semgen.order import check_bundle_order
from tests.support.fake_snomed import CKD, DAUNO, DISEASE, DM, DOX, FAKE_M1, FAKE_M2, MET, T1DM, T2DM, write_fake_rf2
from tests.support.matcher import matches_bundle
from tests.test_op_motif_deletion import bundle, drug, dx

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "tests" / "fixtures" / "golden"


def b_all() -> MotifBundle:
    return bundle("all", drug("A", DOX), dx("M1", T1DM), dx("M2", T2DM))


def patients() -> list[Motif]:
    """At most one drug and any subset of three disorders: 32 synthetic patients over the fake hierarchy."""
    out = []
    for drug_code in (None, DOX, DAUNO, MET):
        for k in range(4):
            for dxs in itertools.combinations((T1DM, T2DM, CKD), k):
                facts = ([("f0", "Substance", drug_code, "administered_drug")] if drug_code else []) + \
                        [(f"f{i + 1}", "Disorder", c, "has_condition") for i, c in enumerate(dxs)]
                out.append(Motif(motif_id="PAT", anchor=PATIENT_ID,
                                 nodes=(Node(id=PATIENT_ID, type="Patient", role="patient"),) + tuple(
                                     Node(id=i, type=t, role="modifier", code=c) for i, t, c, _ in facts),
                                 edges=tuple(Edge(s=PATIENT_ID, t=i, rel=r, prov="asserted") for i, _, _, r in facts)))
    return out


def lifts_of(ns, target: str) -> list:
    return [n for n in ns if any(ch.op == "concept_lift" and ch.target == target for ch in n.changes)]


def _find(lat, pred) -> str:
    (h,) = [h for h, c in lat.candidates.items() if pred(c.bundle)]
    return h


def test_motif_aggregation_is_not_a_generalization_operator(ctx):
    import semgen.operators as ops
    assert [op.__name__ for op in ops.BUNDLE_OPERATORS] == ["motif_deletion"]
    assert "motif_aggregation" not in {op.__name__ for op in ops.ALL_OPERATORS}
    with pytest.raises(ModuleNotFoundError):
        __import__("semgen.operators.motif_aggregation")
    lat = enumerate_lattice(b_all(), ctx)
    assert "motif_aggregation" not in {ch.op for e in lat.edges for ch in e.changes}
    assert "motif_aggregation" not in {b.op for _, b in lat.blocked}


def test_boolean_structure_is_never_changed(ctx):
    """Every reachable state keeps the root's semantics, and each part is the root's part or a generalization of it
    (none merged into an OR group): AND stays AND, OR alternatives stay intact."""
    for sem, lat in _lattices(ctx).items():
        root_ids = {p.part_id for p in b_all().parts}
        for c in lat.candidates.values():
            assert c.bundle.semantics == sem
            assert {p.part_id for p in c.bundle.parts} <= root_ids
            assert all(p.motif.motif_id == p.part_id for p in c.bundle.parts)


def _lattices(ctx):
    return {sem: enumerate_lattice(b_all().model_copy(update={"semantics": sem}), ctx) for sem in ("all", "any", None)}


def _certificate(ch):
    return ch.evidence["mapping"] if ch.op == "motif_deletion" else None


def _match_set(b: MotifBundle, pats, h, assume) -> frozenset[int]:
    return frozenset(i for i, p in enumerate(pats) if matches_bundle(b, p, h, assume=assume))


def test_every_edge_proven_and_monotone(ctx):
    pats, h = patients(), ctx.hierarchy
    for sem, lat in _lattices(ctx).items():
        assert lat.status == "exhausted" and len(lat.edges) > 20, sem
        for e in lat.edges:
            parent, child = lat.candidates[e.parent].bundle, lat.candidates[e.child].bundle
            for ch in e.changes:
                assert check_bundle_order(parent, child, ctx, _certificate(ch)).ok, (sem, ch)
            for assume in (("all", "any") if sem is None else (None,)):
                assert _match_set(parent, pats, h, assume) <= _match_set(child, pats, h, assume), (sem, e.changes)
        ops = {ch.op for e in lat.edges for ch in e.changes}
        expected = {"all": {"concept_lift", "motif_deletion"},
                    "any": {"concept_lift", "motif_deletion"}, None: {"concept_lift"}}[sem]
        assert ops == expected, (sem, ops)


def test_kept_edges_equal_match_set(ctx):
    pats, h = patients(), ctx.hierarchy
    kept = 0
    for sem, lat in _lattices(ctx).items():
        for e in lat.edges:
            if any(ch.meaning == "kept" for ch in e.changes):
                kept += 1
                parent, child = lat.candidates[e.parent].bundle, lat.candidates[e.child].bundle
                assert _match_set(parent, pats, h, None) == _match_set(child, pats, h, None), (sem, e.changes)
    assert kept >= 4   # not vacuous: deletions under "all" and "any"


def test_unbounded_exhausted_and_budget_limited_reported(ctx):
    lat = enumerate_lattice(b_all(), ctx)
    assert (lat.status, lat.budget_hit, lat.refused, lat.unexpanded) == ("exhausted", (), 0, 0)
    assert set(lat.axes) == {"A/A.d", "M1/M1.d", "M2/M2.d"}   # multi-part bundles: axes per (part, node)
    assert lat.axes["M1/M1.d"].reached == tuple(sorted((DM, DISEASE)))
    # (1 + 1 ancestor of DOX) * (1 + 2 of T1DM) * (1 + 2 of T2DM); the root has no motif deletion
    assert lat.state_space_estimate == 18   # orientation only: not an upper bound on the candidates
    small = enumerate_lattice(b_all(), ctx, Budget(max_states=5))
    assert (small.status, small.budget_hit) == ("budget_limited", ("max_states",)) and small.refused >= 1
    shallow = enumerate_lattice(b_all(), ctx, Budget(max_depth=1))
    assert (shallow.status, shallow.budget_hit) == ("budget_limited", ("max_depth",))
    root = lat.candidates[lat.root]
    assert root.depth == 0 and root.bundle == b_all()
    with pytest.raises(ValueError):
        root.motif   # a multi-part bundle has no single motif


def test_progress_file_streams_bfs_order(ctx, tmp_path):
    p = tmp_path / "progress.jsonl"
    lat = enumerate_lattice(b_all(), ctx, progress=p)
    rows = [json.loads(line) for line in p.read_text().splitlines()]
    assert len(rows) == len(lat.candidates) and {r["hash"] for r in rows} == set(lat.candidates)
    assert rows[0]["hash"] == lat.root and rows[0]["depth"] == 0
    bfs = [r["depth"] for r in rows if r["origin"] == "lattice"]
    assert bfs == sorted(bfs)   # accepted level by level
    assert list(lat.candidates) == [r["hash"] for r in rows]   # the order of acceptance
    assert all(("bundle" in r) != ("motif" in r) for r in rows)


def test_bundle_of_one_root_proof_and_climb_unchanged(ctx, fake_m1):
    """A bundle of one runs today's single-motif path: the same lattice as for the bare motif."""
    a = enumerate_lattice(fake_m1, ctx, Budget(max_depth=2))
    b = enumerate_lattice(MotifBundle.of(fake_m1), ctx, Budget(max_depth=2))
    assert list(a.candidates) == list(b.candidates) and a.edges == b.edges and a.blocked == b.blocked
    assert a.axes == b.axes and set(a.axes) == {"n1", "n2", "n3"}
    assert all(c.bundle.is_single and c.motif == c.bundle.single_motif for c in a.candidates.values())


def test_subject_reaches_the_operators(ctx, monkeypatch):
    from semgen.bundle import Subject
    seen = []
    from tests.support.ops import with_ops
    real = L.operators_of(ctx).motif[0]
    ctx = with_ops(ctx, lambda m, c: (seen.append(c.subject), real(m, c))[1])
    s = Subject(sex="F", age_days=10)
    enumerate_lattice(b_all().model_copy(update={"subject": s}), ctx, Budget(max_depth=0), climb=False)
    enumerate_lattice(dx("M1", T1DM), ctx, Budget(max_depth=0), climb=False)
    assert seen[0] == s and seen[-1] is None


def test_progress_partial_until_proven_and_stale_removed(ctx, tmp_path, monkeypatch):
    p = tmp_path / "progress.jsonl"
    p.write_text("stale\n")
    enumerate_lattice(b_all(), ctx, Budget(max_depth=1), progress=p)
    assert "stale" not in p.read_text() and not (tmp_path / "progress.jsonl.partial").exists()
    import semgen.lattice.search as S
    monkeypatch.setattr(S, "check_bundle_order", lambda *a, **k: L.OrderResult(False, "forced", "x"))
    with pytest.raises(L.GeneralizationOrderError, match="forced"):
        enumerate_lattice(b_all(), ctx, progress=p)
    assert not p.exists()                                   # the earlier complete file is gone ...
    assert (tmp_path / "progress.jsonl.partial").exists()   # ... and the failed run left only the partial one


# --- CLI: an old-format motif list (Review Focus 5) ----------------------------------------------


def _cli(*args, env):
    return subprocess.run([sys.executable, "-m", "semgen", *args], capture_output=True, text=True, cwd=REPO, env=env)


def cli_env(tmp_path) -> dict:
    return {**os.environ, "SEMGEN_CACHE_DIR": str(tmp_path / "cache")}


def test_old_motif_list_cli_matches_golden(tmp_path):
    rf2 = write_fake_rf2(tmp_path / "rf2")
    motifs = tmp_path / "motifs.json"
    motifs.write_text(json.dumps([copy.deepcopy(FAKE_M1), copy.deepcopy(FAKE_M2)]))
    out = tmp_path / "out"
    r = _cli("run", "--motifs", str(motifs), "--rf2", str(rf2), "--max-depth-budget", "4",
             "--max-states", str(10**9), "--out", str(out), env=cli_env(tmp_path))
    assert r.returncode == 0, r.stderr
    assert [line.split()[0] for line in r.stdout.splitlines()] == ["M1", "M2"]
    import re
    fp = re.compile(rb'"fingerprint":"[0-9a-f]{64}"')   # the CLI's concept model is loaded from RF2 files, the
    for mid in ("M1", "M2"):                           # golden's built in memory: same content, other provenance
        for name in ("candidates.jsonl", "edges.jsonl"):
            got, want = (out / mid / name).read_bytes(), (GOLDEN / "fake_full" / mid / name).read_bytes()
            assert len(set(fp.findall(got))) <= 1, (mid, name)
            assert fp.sub(b'"fingerprint":"X"', got) == fp.sub(b'"fingerprint":"X"', want), (mid, name)


@pytest.mark.parametrize("hostile", ["../escape", "ABSOLUTE", "a/b", ".."])
@pytest.mark.parametrize("progress", [True, False])
def test_hostile_bundle_id_writes_nothing(tmp_path, hostile, progress):
    """A bundle id that is unsafe or would escape OUT exits 1 before anything is written or enumerated."""
    work = tmp_path / "work"
    work.mkdir()
    rf2 = write_fake_rf2(tmp_path / "rf2")
    bid = str(work / "abs_escape") if hostile == "ABSOLUTE" else hostile
    raw = {"bundle_id": bid, "semantics": "all", "anchor_motif": "A",
           "motifs": [{"motif_id": m, "anchor": "d", "nodes": [{"id": "P", "type": "Patient", "role": "patient"},
                                                               {"id": "d", "type": "Disorder", "code": c,
                                                                "role": "anchor"}],
                       "edges": [{"s": "P", "t": "d", "rel": "has_condition", "prov": "asserted"}]}
                      for m, c in (("A", T1DM), ("M1", T2DM))]}
    good = {**raw, "bundle_id": "OK"}
    motifs = tmp_path / "bundles.json"
    motifs.write_text(json.dumps({"bundles": [good, raw]}))   # the safe bundle comes first: still nothing written
    out = work / "out"
    before = sorted(p.name for p in work.iterdir())
    r = _cli("run", "--motifs", str(motifs), "--rf2", str(rf2), *(["--progress"] if progress else []),
             "--out", str(out), env=cli_env(tmp_path))
    assert r.returncode == 1 and ("unsafe id" in r.stderr or "escapes" in r.stderr), r.stderr
    assert "Traceback" not in r.stderr and r.stdout == ""   # exits before any enumeration
    assert sorted(p.name for p in work.iterdir()) == before   # nothing next to OUT, OUT itself not created
