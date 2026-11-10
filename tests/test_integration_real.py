"""Real-SNOMED integration checks over the SYNTHETIC M1-M4 motifs (not BioPathNet output).

Expectations follow the Stage 1 PhecodeX floors. Skipped when RF2 or PhecodeX files are missing.
"""
import pytest

from semgen.canonical import canonical_json
from semgen.lattice import enumerate_lattice
from semgen.order import check_order
from tests.support.matcher import matches
from tests.support.patients import m1_patients, m2_patients

pytestmark = [pytest.mark.snomed, pytest.mark.phecodex]


def lat_of(real_motifs, real_ctx, mid, d):
    return enumerate_lattice(next(m for m in real_motifs if m.motif_id == mid), real_ctx, d)


def changes(lat):
    return [c for e in lat.edges for c in e.changes]


@pytest.mark.parametrize("depth", [2, 4])
def test_all_motifs_zero_proof_failures(real_motifs, real_ctx, depth):
    for m in real_motifs:
        lat = enumerate_lattice(m, real_ctx, depth)
        assert all(check_order(m, c.motif, real_ctx).ok for c in lat.candidates.values())


def test_m1_check2(real_motifs, real_ctx):
    ch = changes(lat_of(real_motifs, real_ctx, "M1", 1))
    lifts = {(c.target, c.after) for c in ch if c.op == "concept_lift"}
    assert lifts == set()   # Stage 1: both parents (126926005, 188361007) are outside_floor
    lat = lat_of(real_motifs, real_ctx, "M1", 1)
    assert {(b.target, b.detail["parent"]) for _, b in lat.blocked
            if b.op == "concept_lift" and b.reason == "outside_floor" and b.target == "n1"} == {
        ("n1", "126926005"), ("n1", "188361007")}
    assert ("P->n2", "exposed_to_drug") in {(c.target, c.after) for c in ch if c.op == "relation_relaxation"}


def test_m2_check3(real_motifs, real_ctx):
    lat = lat_of(real_motifs, real_ctx, "M2", 4)
    assert {c.after for c in changes(lat) if c.op == "concept_lift" and c.target == "n1"} == set()   # DM blocked by 105401000119101
    assert not any(c.target in ("n2", "P->n2") for c in changes(lat))


def test_m3_anchor_lift(real_motifs, real_ctx):
    assert ("n1", "254637007") in {(c.target, c.after) for c in changes(lat_of(real_motifs, real_ctx, "M3", 1))
                                   if c.op == "concept_lift"}


def test_m4_alt_and_ra_blocked(real_motifs, real_ctx):
    lat = lat_of(real_motifs, real_ctx, "M4", 1)
    assert ("n3", (3, 5)) in {(c.target, (c.after["lo"], c.after["hi"])) for c in changes(lat)
                              if c.op == "range_coarsening"}
    assert ("concept_lift", "n1", "outside_floor") in {(b.op, b.target, b.reason) for _, b in lat.blocked}


def test_drug_lifts_blocked_without_floor(real_motifs, real_ctx):
    lat = lat_of(real_motifs, real_ctx, "M1", 1)
    assert not any(c.op == "concept_lift" and c.target == "n2" for c in changes(lat))


# --- extras ------------------------------------------------------------------------------------
def _motif(real_motifs, mid):
    return next(m for m in real_motifs if m.motif_id == mid)


def _matched(motif, pats, ctx):
    return {pid for pid, p in pats.items() if matches(motif, p, ctx.hierarchy, ctx.config.relations)}


def test_real_containment_depth4(real_motifs, real_ctx):
    for mid, make, gold in (("M1", m1_patients, {"exact", "extra_condition"}), ("M2", m2_patients, {"exact"})):
        root = _motif(real_motifs, mid)
        pats = make(root)
        assert _matched(root, pats, real_ctx) == gold
        lat = enumerate_lattice(root, real_ctx, 4)
        sets = {h: _matched(c.motif, pats, real_ctx) for h, c in lat.candidates.items()}
        assert [(e.parent, e.child) for e in lat.edges if not sets[e.parent] <= sets[e.child]] == []
        assert any(sets[e.parent] < sets[e.child] for e in lat.edges)   # non-vacuous: some edge strictly grows


def test_real_no_policy_or_order_errors_depth4(real_motifs, real_ctx):
    for m in real_motifs:
        lat = enumerate_lattice(m, real_ctx, 4)   # raises PolicyViolation / GeneralizationOrderError on failure
        assert all(check_order(m, c.motif, real_ctx).ok for c in lat.candidates.values())


def test_real_lattice_deterministic(real_motifs, real_ctx):
    for m in real_motifs:
        a, b = enumerate_lattice(m, real_ctx, 2), enumerate_lattice(m, real_ctx, 2)
        assert list(a.candidates) == list(b.candidates)
        assert a.edges == b.edges
        assert a.blocked == b.blocked
        assert {h: canonical_json(c.motif) for h, c in a.candidates.items()} == \
               {h: canonical_json(c.motif) for h, c in b.candidates.items()}
        assert {h: c.depth for h, c in a.candidates.items()} == {h: c.depth for h, c in b.candidates.items()}


def test_phecodex_m3_n1_climb_still_stops_at_anchor(real_motifs, real_ctx):
    lat = enumerate_lattice(_motif(real_motifs, "M3"), real_ctx, 4)
    assert lat.axes["n1"].reached == ("254637007",)
