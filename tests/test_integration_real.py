"""Real-SNOMED integration checks over the SYNTHETIC M1-M4 motifs (not BioPathNet output).

Expectations follow the SNOMED-only snomed_boundary floor (D14; they were PhecodeX floors before Task 1).
Skipped when the RF2 release is missing.
"""
import pytest
import pytest as _pytest

from semgen.canonical import canonical_json
from semgen.lattice import Budget, enumerate_lattice
from semgen.order import check_order
from tests.support.matcher import matches
from tests.support.patients import m1_patients, m2_patients
from tests.support.relevance import relaxed


# Rev 4: deletion moves need a relaxable relevance decision; these tests are about what deletions do, so they
# run with every candidate relaxable (tests/support/relevance.py). The gate itself: tests/test_relevance.py.
@_pytest.fixture
def real_ctx(real_ctx):
    return relaxed(real_ctx)


pytestmark = pytest.mark.snomed


def lat_of(real_motifs, real_ctx, mid, d):
    return enumerate_lattice(next(m for m in real_motifs if m.motif_id == mid), real_ctx, Budget(max_depth=d))


def changes(lat):
    return [c for e in lat.edges for c in e.changes]


@pytest.mark.parametrize("depth", [2, 4])
def test_all_motifs_zero_proof_failures(real_motifs, real_ctx, depth):
    for m in real_motifs:
        lat = enumerate_lattice(m, real_ctx, Budget(max_depth=depth))
        assert all(check_order(m, c.motif, real_ctx).ok for c in lat.candidates.values())


def test_m1_check2(real_motifs, real_ctx):
    """Rewritten (Task 1): was no n1 lift (both parents outside_floor) plus a relation_relaxation P->n2 move; now
    both parents are lifted (as in golden real_lift/M1), nothing is outside_floor, and relations never change."""
    lat = lat_of(real_motifs, real_ctx, "M1", 1)
    ch = changes(lat)
    lifts = {(c.target, c.after) for e in lat.edges if e.parent == lat.root for c in e.changes
             if c.op == "concept_lift" and c.target == "n1"}   # root step only (the climb goes further)
    assert lifts == {("n1", "126926005"), ("n1", "188361007")}
    assert not any(b.reason == "outside_floor" for _, b in lat.blocked)
    assert not any(c.op == "relation_relaxation" for c in ch)


def test_m2_check3(real_motifs, real_ctx):
    """Rewritten (Task 1): was no n1 lift (DM blocked by 105401000119101); now T2DM lifts to DM."""
    lat = lat_of(real_motifs, real_ctx, "M2", 4)
    assert "73211009" in {c.after for c in changes(lat) if c.op == "concept_lift" and c.target == "n1"}
    assert not any(c.target in ("n2", "P->n2") for c in changes(lat))


def test_m3_anchor_lift(real_motifs, real_ctx):
    assert ("n1", "254637007") in {(c.target, c.after) for c in changes(lat_of(real_motifs, real_ctx, "M3", 1))
                                   if c.op == "concept_lift"}


def test_m4_alt_and_ra_lift(real_motifs, real_ctx):
    """Rewritten (SNOMED-only lift): RA does not lift: Arthritis drops its Pathological process and Autoimmune disease
    its Finding site / morphology (defining_attribute_dropped, from the release's inferred relationships).
    Rewritten (Task 2): was ALT n3 coarsened to the x ULN ladder rung (3, 5] by range_coarsening; ladders are gone,
    the real ALT node has no test identity, so it is not bucketed and only its value can be deleted."""
    lat = lat_of(real_motifs, real_ctx, "M4", 1)
    n3 = [(c.op, c.field) for c in changes(lat) if c.target == "n3"]
    assert ("attribute_deletion", "value") in n3 and not any(op == "normative_bucketing" for op, _ in n3)
    assert ("normative_bucketing", "n3", "no_test_identity") in {(b.op, b.target, b.reason) for _, b in lat.blocked}
    assert not {c.after for e in lat.edges if e.parent == lat.root for c in e.changes
                if c.op == "concept_lift" and c.target == "n1"}
    assert {(b.detail["parent"], b.reason) for h, b in lat.blocked if h == lat.root and b.op == "concept_lift"
            and b.target == "n1"} == {("3723001", "defining_attribute_dropped"), ("85828009", "defining_attribute_dropped")}


def test_drug_lifts_blocked_without_floor(real_motifs, real_ctx):
    lat = lat_of(real_motifs, real_ctx, "M1", 1)
    assert not any(c.op == "concept_lift" and c.target == "n2" for c in changes(lat))


# --- extras ------------------------------------------------------------------------------------
def _motif(real_motifs, mid):
    return next(m for m in real_motifs if m.motif_id == mid)


def _matched(motif, pats, ctx):
    return {pid for pid, p in pats.items() if matches(motif, p, ctx.hierarchy)}


def test_real_containment_depth4(real_motifs, real_ctx):
    for mid, make, gold in (("M1", m1_patients, {"exact", "extra_condition"}), ("M2", m2_patients, {"exact"})):
        root = _motif(real_motifs, mid)
        pats = make(root)
        assert _matched(root, pats, real_ctx) == gold
        lat = enumerate_lattice(root, real_ctx, Budget(max_depth=4))
        sets = {h: _matched(c.motif, pats, real_ctx) for h, c in lat.candidates.items()}
        assert [(e.parent, e.child) for e in lat.edges if not sets[e.parent] <= sets[e.child]] == []
        assert any(sets[e.parent] < sets[e.child] for e in lat.edges)   # non-vacuous: some edge strictly grows


def test_real_no_policy_or_order_errors_depth4(real_motifs, real_ctx):
    for m in real_motifs:
        lat = enumerate_lattice(m, real_ctx, Budget(max_depth=4))   # raises PolicyViolation / GeneralizationOrderError on failure
        assert all(check_order(m, c.motif, real_ctx).ok for c in lat.candidates.values())


def test_real_lattice_deterministic(real_motifs, real_ctx):
    for m in real_motifs:
        a, b = enumerate_lattice(m, real_ctx, Budget(max_depth=2)), enumerate_lattice(m, real_ctx, Budget(max_depth=2))
        assert list(a.candidates) == list(b.candidates)
        assert a.edges == b.edges
        assert a.blocked == b.blocked
        assert {h: canonical_json(c.motif) for h, c in a.candidates.items()} == \
               {h: canonical_json(c.motif) for h, c in b.candidates.items()}
        assert {h: c.depth for h, c in a.candidates.items()} == {h: c.depth for h, c in b.candidates.items()}
