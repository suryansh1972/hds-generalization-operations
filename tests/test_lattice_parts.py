"""Value operators on the parts of multi-part bundles (design §6, §9).

A drug anchor part plus two lab motifs, each with a test identity, an attached reference range and repeated
observations. Normative bucketing, attribute deletion and A1 must act on the non-anchor parts, and every edge must
be monotone on synthetic patients (child match set ⊇ parent's; ``kept`` edges equal) under ``"all"``, ``"any"``
and unknown semantics (the latter checked under both readings via the test matcher's ``assume=``).
"""
from __future__ import annotations

import dataclasses

import pytest

from semgen.bundle import MotifBundle, MotifPart, Subject
from semgen.config import load_config
from semgen.lattice import Budget, enumerate_lattice
from semgen.model import PATIENT_ID, Edge, Interval, Motif, Node, ReferenceRange, TestIdentity
from semgen.operators.base import GenContext
from tests.support.fake_snomed import CONFIG_PATH, DM, DOX, GFR, T1DM, T2DM, fake_boundary_policy, fake_hierarchy
from tests.support.matcher import matches_bundle
from tests.support.relevance import relaxed, relaxed_bundle
from tests.support.ucum import test_ucum

TEST = TestIdentity(system="urn:s", code="GFR-S", method="calc", specimen="Serum")
RR = ReferenceRange(interval=Interval.closed(30, 50, "u"), kind="reference", test=TEST, source="s", source_ref="r1")
VALUE_OPS = ("normative_bucketing", "attribute_deletion", "attribute_aggregation")
MAX_STATES = 250


def lab(mid: str, dx_code: str, values: list[float]) -> Motif:
    def ns(x: str) -> str:
        return f"{mid}.{x}"
    nodes = [Node(id=PATIENT_ID, type="Patient", role="patient"),
             Node(id=ns("d"), type="Disorder", role="anchor", code=dx_code)]
    edges = [Edge(s=PATIENT_ID, t=ns("d"), rel="has_condition", prov="asserted")]
    for i, v in enumerate(values):
        nodes.append(Node(id=ns(f"g{i}"), type="Observable", role="outcome", code=GFR,
                          value=Interval.point(v, "u"), test=TEST, reference_range=RR))
        edges.append(Edge(s=PATIENT_ID, t=ns(f"g{i}"), rel="has_measurement", prov="asserted"))
    return Motif(motif_id=mid, anchor=ns("d"), nodes=tuple(nodes), edges=tuple(edges))


DRUG = Motif(motif_id="A", anchor="A.d",
             nodes=(Node(id=PATIENT_ID, type="Patient", role="patient"),
                    Node(id="A.d", type="Substance", role="anchor", code=DOX)),
             edges=(Edge(s=PATIENT_ID, t="A.d", rel="administered_drug", prov="asserted"),))
M1, M2 = lab("M1", T2DM, [42, 55]), lab("M2", T1DM, [42, 44])
SUBJECT = Subject(sex="female", age_days=20000)


def root(semantics) -> MotifBundle:
    parts = (MotifPart(part_id="A", motif=DRUG), MotifPart(part_id="M1", motif=M1), MotifPart(part_id="M2", motif=M2))
    return MotifBundle(bundle_id="B", semantics=semantics, anchor_part="A", parts=parts, subject=SUBJECT)


def patient(dx: str | None, drug: bool, values: list[float]) -> Motif:
    facts = ([("x", "Disorder", dx, "has_condition", None)] if dx else []) + \
            ([("y", "Substance", DOX, "administered_drug", None)] if drug else []) + \
            [(f"f{i}", "Observable", GFR, "has_measurement", Interval.point(v, "u")) for i, v in enumerate(values)]
    return Motif(motif_id="PAT", anchor=PATIENT_ID,
                 nodes=(Node(id=PATIENT_ID, type="Patient", role="patient"),) + tuple(
                     Node(id=i, type=t, role="modifier", code=c, value=v) for i, t, c, _, v in facts),
                 edges=tuple(Edge(s=PATIENT_ID, t=i, rel=r, prov="asserted") for i, _, _, r, _ in facts))


PATIENTS = [patient(dx, dr, vals) for dx in (None, T1DM, T2DM, DM) for dr in (False, True)
            for vals in ([], [42], [42, 44], [42, 55], [10], [10, 90], [35, 40, 60])]


@pytest.fixture(scope="module")
def lattices():
    h = fake_hierarchy()
    # Rev 4: every deletion candidate relaxable (tests/support/relevance.py); the gate: tests/test_relevance.py.
    ctx = dataclasses.replace(relaxed(GenContext(h, load_config(CONFIG_PATH), fake_boundary_policy(h))),
                              ucum=test_ucum("u"))
    return ctx, {sem: enumerate_lattice(relaxed_bundle(root(sem)), ctx, Budget(max_states=MAX_STATES))
                 for sem in ("all", "any", None)}


@pytest.mark.parametrize("sem", ["all", "any", None])
def test_value_operators_act_on_non_anchor_parts(lattices, sem):
    _, lats = lattices
    lat = lats[sem]
    assert len(lat.candidates) == MAX_STATES   # the budget, not exhaustion, bounds the run (kept fast)
    on_labs = set()
    for e in lat.edges:
        pb, cb = lat.candidates[e.parent].bundle, lat.candidates[e.child].bundle
        if any(p.part_id in {"M1", "M2"} and p.motif != cb.part(p.part_id).motif
               for p in pb.parts if p.part_id in {q.part_id for q in cb.parts}):
            on_labs |= {ch.op for ch in e.changes}
    assert set(VALUE_OPS) <= on_labs, (sem, on_labs)


@pytest.mark.parametrize("sem", ["all", "any", None])
def test_every_edge_monotone_and_kept_equal(lattices, sem):
    ctx, lats = lattices
    lat, h = lats[sem], ctx.hierarchy
    readings = ("all", "any") if sem is None else (None,)
    for assume in readings:
        ms = {k: frozenset(i for i, p in enumerate(PATIENTS) if matches_bundle(c.bundle, p, h, assume=assume))
              for k, c in lat.candidates.items()}
        assert any(ms.values()), (sem, assume)   # not vacuous
        kept = 0
        for e in lat.edges:
            ops = [ch.op for ch in e.changes]
            assert ms[e.parent] <= ms[e.child], (sem, assume, ops)
            if any(ch.meaning == "kept" for ch in e.changes):
                kept += 1
                assert ms[e.parent] == ms[e.child], (sem, assume, ops)
        assert kept >= 1, (sem, assume)
