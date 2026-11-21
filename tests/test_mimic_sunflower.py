"""Real-SNOMED checks on the MIMIC-00081 sunflower bundle (restricted local data, never committed).

Opt-in: point ``SEMGEN_MIMIC_BUNDLE`` at the bundle file (default: ``data/motifs/mimic_00081_sunflower.json``, which
``.gitignore`` excludes). Skipped when the bundle, the RF2 release or the UCUM essence is missing.

One real MIMIC-IV demo patient (ODbL) at the centre. KG petals are 6-hop OptimusKG mechanism paths
(drug -> target gene -> pathway -> gene -> GO process -> gene -> condition); petal02 is a 2-hop branch of petal01;
petal03 holds hyponatremia and three real serum sodium results. BioPathNet was not run (bpn_score null).
Every operator except A1 has a real move on this bundle: the sodium results are recorded in ``mEq/L``, which is
not a valid case-sensitive UCUM unit (UCUM writes ``meq/L``), so A1 blocks ``unit_invalid`` rather than merging
them. Skipped when the RF2 release or the UCUM essence is missing.
"""
import os
from pathlib import Path

import pytest

from semgen.bundle import MotifBundle
from semgen.lattice import Budget, enumerate_lattice
from semgen.model import PATIENT_ID, Edge, Motif
from semgen.motif_io import load_bundles
from semgen.order import check_bundle_order
from tests.support.matcher import matches_bundle

pytestmark = pytest.mark.snomed

BUNDLE = Path(os.environ.get("SEMGEN_MIMIC_BUNDLE")
              or Path(__file__).resolve().parent.parent / "data/motifs/mimic_00081_sunflower.json")
ALLOPURINOL, GOUT = "387135004", "90560007"
KG_PETALS = ("petal01", "petal04", "petal05", "petal06", "petal07")


@pytest.fixture(scope="module")
def sunflower(real_h):
    if not BUNDLE.is_file():
        pytest.skip("MIMIC sunflower bundle not available (set SEMGEN_MIMIC_BUNDLE)")
    (b,) = load_bundles(BUNDLE, real_h)
    return b


@pytest.fixture(scope="module")
def lattice(sunflower, real_ctx):
    if real_ctx.ucum is None:
        pytest.skip("UCUM essence not found (A1 cannot validate units)")
    return enumerate_lattice(sunflower, real_ctx, Budget(max_depth=1))


def _record(bundle, drop_drug: str | None = None) -> Motif:
    """The patient's own graph: the union of every petal. Coded facts without values are shared across petals
    (one node per type and code); results keep their own node."""
    key_of, nodes, edges = {}, {}, {}
    for part in bundle.parts:
        for n in part.motif.nodes:
            if n.code is not None and n.code == drop_drug:
                continue
            k = n.id if n.id == PATIENT_ID or n.value is not None else f"{n.type}:{n.code}"
            key_of[n.id] = k
            nodes.setdefault(k, n.model_copy(update={"id": k}))
        for e in part.motif.edges:
            s, t = key_of.get(e.s), key_of.get(e.t)
            if s in nodes and t in nodes:
                edges[(s, t)] = Edge(s=s, t=t, rel=e.rel, prov=e.prov)
    return Motif(motif_id="REC", anchor=f"Disorder:{GOUT}", nodes=tuple(nodes.values()), edges=tuple(edges.values()))


def _root_ops(lat):
    return [c for e in lat.edges if e.parent == lat.root for c in e.changes]


def test_kg_petals_are_six_hop_chains_from_the_patient(sunflower):
    assert sunflower.semantics == "all" and len(sunflower.parts) == 7
    for part in sunflower.parts:
        m = part.motif
        if part.part_id not in KG_PETALS:
            continue
        drug = next(n for n in m.nodes if n.role == "exposure")
        cond = m.node(m.anchor)
        assert {(e.s, e.t) for e in m.edges if e.prov == "asserted"} == {(PATIENT_ID, drug.id), (PATIENT_ID, cond.id)}
        ctx = [e for e in m.edges if e.prov == "context"]
        assert len(ctx) == 6 and all(e.bpn_score is None for e in ctx)
        nxt, walk = {e.s: e.t for e in ctx}, [drug.id]
        while walk[-1] in nxt:
            walk.append(nxt[walk[-1]])
        assert walk[-1] == cond.id and [m.node(i).type for i in walk[1:-1]] == [
            "Gene", "Pathway", "Gene", "BiologicalProcess", "Gene"]


def test_every_operator_has_a_real_move(lattice):
    """Rev 4: the bundle declares no cohort definition, so the relevance gate leaves every attribute-deletion
    candidate ``unknown``: blocked, never a move (no cohort is invented for real data)."""
    ops = {c.op for c in _root_ops(lattice)}
    # Motif aggregation is not an operator (it turned AND into OR). A1 is blocked: "mEq/L" is not valid UCUM.
    assert ops == {"concept_lift", "normative_bucketing", "motif_deletion"}
    assert len(lattice.candidates) == 24   # 25 before UCUM validation was enforced: the one A1 merge
    gated = [b for h, b in lattice.blocked if h == lattice.root and b.op == "attribute_deletion"]
    assert gated and {b.reason for b in gated} == {"relevance_unknown"}
    assert {b.detail["reason"] for b in gated} == {"no cohort definition declared"}


def test_depth1_every_candidate_proven_against_root(lattice, real_ctx):
    """A deletion's proof needs its containment certificate, which enumerate_lattice re-checks itself (it raises
    otherwise); every other depth-1 candidate is re-proven here from the two bundles alone."""
    root = lattice.candidates[lattice.root].bundle
    deleted = {e.child for e in lattice.edges if any(c.op == "motif_deletion" for c in e.changes)}
    checked = 0
    for c in lattice.candidates.values():
        if c.depth == 1 and c.hash not in deleted:
            assert check_bundle_order(root, c.bundle, real_ctx).ok
            checked += 1
    assert checked >= 11 and len(deleted) == 1


def test_record_matches_every_candidate_and_edges_are_monotone(sunflower, lattice, real_h):
    rec = _record(sunflower)
    assert all(matches_bundle(c.bundle, rec, real_h) for c in lattice.candidates.values())
    assert not matches_bundle(sunflower, _record(sunflower, drop_drug=ALLOPURINOL), real_h)
    pts = [rec, _record(sunflower, drop_drug=ALLOPURINOL)]
    for e in lattice.edges:
        a, b = lattice.candidates[e.parent].bundle, lattice.candidates[e.child].bundle
        for p in pts:
            assert not matches_bundle(a, p, real_h) or matches_bundle(b, p, real_h)


def test_sodium_results_bucket_low_and_a1_blocks_on_the_unit(lattice):
    ch = _root_ops(lattice)
    buckets = [c for c in ch if c.op == "normative_bucketing"]
    assert len(buckets) == 3 and {c.evidence["bucket"] for c in buckets} == {"below_reference_interval"}
    assert not [c for c in ch if c.op == "attribute_aggregation"]
    (b,) = [b for h, b in lattice.blocked if h == lattice.root and b.op == "attribute_aggregation"]
    assert (b.reason, b.detail["unit"], b.detail["status"]) == ("unit_invalid", "mEq/L", "invalid")
    assert b.detail["nodes"] == ["petal03.na1", "petal03.na2", "petal03.na3"]


def test_branch_petal_deleted_both_ways(sunflower, lattice, real_ctx):
    (d,) = [c for c in _root_ops(lattice) if c.op == "motif_deletion"]
    assert (d.target, d.evidence["subsumed_by"], d.evidence["direction"]) == ("petal02", "petal01", "deleted_is_broader")
    any_b = MotifBundle(bundle_id="ANY", semantics="any", anchor_part="petal03", parts=sunflower.parts)
    lat = enumerate_lattice(any_b, real_ctx, Budget(max_depth=1))
    (d,) = [c for c in _root_ops(lat) if c.op == "motif_deletion"]
    assert (d.target, d.evidence["subsumed_by"], d.evidence["direction"]) == ("petal01", "petal02", "deleted_is_narrower")


def test_gout_allopurinol_climb_and_no_motif_aggregation(lattice):
    """Gout stops at Inflammatory disorder (its other parent and every step above drop a defining attribute); the
    dementia and anxiety petals (both on risperidone) stay two AND-ed parts: nothing merges them into an OR."""
    ax = lattice.axes["petal01/petal01.cond"]
    assert set(ax.reached) == {"128139000"} and ax.status == "reached_floor"
    assert "419262004" in lattice.axes["petal01/petal01.drug"].reached   # xanthine oxidase inhibitor mechanism
    assert not [c for c in _root_ops(lattice) if c.op == "motif_aggregation"]
    assert not [b for _, b in lattice.blocked if b.op == "motif_aggregation"]
    assert all({"petal05", "petal06"} <= {p.part_id for p in c.bundle.parts} or c.depth == 1
               for c in lattice.candidates.values())
