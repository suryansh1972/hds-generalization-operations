"""Real-SNOMED integration checks under the DRAFT snomed_boundary policy over the SYNTHETIC M1-M4 motifs.

Need only the RF2 release (no PhecodeX). Characterisation of finished behaviour, not clinical validation.
"""
import json

import pytest

from semgen.config import load_config
from semgen.export import run_header, write_lattice
from semgen.lattice import enumerate_lattice
from semgen.operators.base import GenContext
from semgen.order import check_order
from semgen.snomed_floor import SnomedBoundaryPolicy
from tests.conftest import _CONFIG_PATH
from tests.support.matcher import matches
from tests.support.patients import m1_patients, m2_patients

pytestmark = pytest.mark.snomed

RA, ARTHRITIS, T2DM, DM, DM_TOP = "69896004", "3723001", "44054006", "73211009", "126877002"
INDOLE, PTERIDINE, ANTIFOLATE = "18858006", "36326009", "372612001"


@pytest.fixture(scope="module")
def real_boundary_ctx(real_h):
    cfg = load_config(_CONFIG_PATH)
    return GenContext(real_h, cfg, SnomedBoundaryPolicy(real_h, cfg.floor_policy.snomed_boundary))


@pytest.fixture(scope="module")
def lats4(real_motifs, real_boundary_ctx):
    return {m.motif_id: enumerate_lattice(m, real_boundary_ctx, 4) for m in real_motifs}


def _motif(real_motifs, mid):
    return next(m for m in real_motifs if m.motif_id == mid)


def _code(motif, nid):
    return next((n.code for n in motif.nodes if n.id == nid), None)   # None when the node was dropped


def _matched(motif, pats, ctx):
    return {pid for pid, p in pats.items() if matches(motif, p, ctx.hierarchy, ctx.config.relations)}


def test_ra_lifts_to_arthritis(lats4):
    assert ARTHRITIS in lats4["M4"].axes["n1"].reached


def test_ra_arthritis_within_ceiling_counts_distinct(real_h, real_boundary_ctx):
    assert real_h.descendant_count(ARTHRITIS) == 1295
    assert len(real_h.descendants_or_self(ARTHRITIS)) == 1296
    assert 1295 <= real_boundary_ctx.floors._cfg.max_descendants


def test_t2dm_climbs_multiple_levels(real_h, real_motifs, lats4):
    reached = set(lats4["M2"].axes["n1"].reached)
    assert {DM, DM_TOP} <= reached
    assert DM_TOP not in real_h.parents(T2DM) and DM_TOP in real_h.ancestors(T2DM)   # not one step


def test_m3_climb_exceeds_depth_cap(real_motifs, lats4):
    lat, root = lats4["M3"], _motif(real_motifs, "M3")
    reached = set(lat.axes["n1"].reached)
    deep = [c for c in lat.candidates.values() if c.origin == "axis" and c.depth > 4
            and _code(c.motif, "n1") in reached
            and all(_code(c.motif, n.id) == n.code for n in root.nodes if n.id != "n1")]
    assert deep
    assert lat.status != "exhausted"


def test_no_finding_targets_for_disorders(real_h, real_motifs, lats4):
    for mid, lat in lats4.items():
        for nid, ax in lat.axes.items():
            if _motif(real_motifs, mid).node(nid).type == "Disorder":
                assert all(real_h.semantic_tag(c) != "finding" for c in ax.reached), (mid, nid)


def test_structural_targets_rejected(real_h, real_motifs, lats4):
    for mid, nid, bad in (("M3", "n3", INDOLE), ("M4", "n2", PTERIDINE)):
        code = _motif(real_motifs, mid).node(nid).code
        assert bad in real_h.parents(code)   # the block is on the actual parent edge
        lat = lats4[mid]
        assert bad not in lat.axes[nid].reached
        assert not any(_code(c.motif, nid) == bad for c in lat.candidates.values())
        assert any(b.target == nid and b.reason == "excluded_ancestor_root" and b.detail["parent"] == bad
                   for _, b in lat.blocked)


def test_mechanism_target_still_allowed(lats4):
    assert ANTIFOLATE in lats4["M4"].axes["n2"].reached   # documented limitation


def test_dose_substance_stays_restricted(real_motifs, lats4):
    lat, root = lats4["M1"], _motif(real_motifs, "M1")
    assert lat.axes["n2"].status == "policy_restricted"
    assert lat.axes["n2"].reached == ()
    assert all(_code(c.motif, "n2") in (root.node("n2").code, None) for c in lat.candidates.values())


def test_lvef_lift_after_value_removal(real_motifs, real_boundary_ctx):
    lat = enumerate_lattice(_motif(real_motifs, "M1"), real_boundary_ctx, 2)
    lifts = [e for e in lat.edges if any(c.op == "concept_lift" and c.target == "n3" for c in e.changes)]
    assert lifts
    assert all(lat.candidates[e.parent].motif.node("n3").value is None for e in lifts)


def test_every_edge_proven(real_motifs, real_boundary_ctx):
    for m in real_motifs:
        lat = enumerate_lattice(m, real_boundary_ctx, 2)
        assert lat.edges
        for e in lat.edges:
            assert check_order(lat.candidates[e.parent].motif, lat.candidates[e.child].motif, real_boundary_ctx).ok


def test_containment_on_synthetic_patients(real_motifs, real_boundary_ctx):
    for mid, make, gold in (("M1", m1_patients, {"exact", "extra_condition"}), ("M2", m2_patients, {"exact"})):
        root = _motif(real_motifs, mid)
        pats = make(root)
        assert _matched(root, pats, real_boundary_ctx) == gold
        lat = enumerate_lattice(root, real_boundary_ctx, 4)
        sets = {h: _matched(c.motif, pats, real_boundary_ctx) for h, c in lat.candidates.items()}
        assert [(e.parent, e.child) for e in lat.edges if not sets[e.parent] <= sets[e.child]] == []
        assert any(sets[e.parent] < sets[e.child] for e in lat.edges)


def test_no_silent_completeness_claim(real_motifs, real_boundary_ctx, lats4, tmp_path):
    incomplete = 0
    for m in real_motifs:
        lat = lats4[m.motif_id]
        paths = write_lattice(lat, m.motif_id, tmp_path, run_header(real_boundary_ctx, _CONFIG_PATH, 4))
        term = json.loads(paths["termination"].read_text())
        assert term["complete"] == (lat.status == "exhausted")
        if lat.status != "exhausted":
            incomplete += 1
            assert term["complete"] is False
    assert incomplete   # non-vacuous: depth 4 is not exhaustive on the real release
