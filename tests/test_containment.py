"""Containment/monotonicity of the generalization lattice on synthetic patients (D16)."""
import ast
import pathlib

import pytest

from semgen.lattice import Budget, enumerate_lattice
from semgen.model import Edge, Interval, Node
from tests.conftest import ANTHRA
from tests.support.matcher import matches
from tests.support.patients import m1_patients, m2_patients

M1_GOLD = {"exact", "extra_condition"}           # written BEFORE running anything
_SRC = pathlib.Path(__file__).resolve().parent.parent / "src"


def _matched(motif, pats, ctx):
    return {pid for pid, p in pats.items() if matches(motif, p, ctx.hierarchy)}


def test_m1_root_gold(ctx, fake_m1):
    got = {pid for pid, p in m1_patients(fake_m1).items() if matches(fake_m1, p, ctx.hierarchy)}
    assert got == M1_GOLD


def test_matcher_is_one_to_one(ctx, fake_m1):
    two = fake_m1.model_copy(update={
        "nodes": fake_m1.nodes + (Node(id="n9", type="Substance", role="exposure", code=ANTHRA),),
        "edges": fake_m1.edges + (Edge(s="P", t="n9", rel="administered_drug", prov="asserted"),)})
    two = two.replace_node(two.node("n2").model_copy(update={"code": ANTHRA, "attrs": {}}))
    assert not matches(two, m1_patients(fake_m1)["exact"], ctx.hierarchy)   # one DOX fact, two pattern drugs


def test_closed_world_descendant_of_absent(ctx, fake_m2):
    ps = m2_patients(fake_m2); assert not matches(fake_m2, ps["has_t1dm"], ctx.hierarchy)


def test_monotone_along_every_lattice_edge(ctx, fake_m1, fake_m2):
    for root, pats in ((fake_m1, m1_patients(fake_m1)), (fake_m2, m2_patients(fake_m2))):
        lat = enumerate_lattice(root, ctx, Budget(max_depth=3))
        sets = {h: {pid for pid, p in pats.items() if matches(c.motif, p, ctx.hierarchy)} for h, c in lat.candidates.items()}
        bad = [(e.parent, e.child) for e in lat.edges if not sets[e.parent] <= sets[e.child]]
        assert bad == []


def test_self_match(ctx, fake_m1, fake_m2):
    for root in (fake_m1, fake_m2):
        patient = root.without({n.id for n in root.nodes if n.polarity == "absent"}, {e.key for e in root.edges if e.t in {n.id for n in root.nodes if n.polarity == "absent"}})
        for c in enumerate_lattice(root, ctx, Budget(max_depth=3)).candidates.values():
            assert matches(c.motif, patient, ctx.hierarchy)


def test_matcher_not_imported_by_production():
    import pathlib
    assert not any("tests.support" in p.read_text() for p in (pathlib.Path(__file__).resolve().parents[1] / "src").rglob("*.py"))


# --- extras ---------------------------------------------------------------------------------
def test_non_vacuous_m1(ctx, fake_m1):
    pats = m1_patients(fake_m1)
    lat = enumerate_lattice(fake_m1, ctx, Budget(max_depth=3))
    sets = {h: _matched(c.motif, pats, ctx) for h, c in lat.candidates.items()}
    assert any(lat.candidates[e.child].depth == 3 and sets[e.child] > sets[e.parent] for e in lat.edges)
    assert len(set().union(*sets.values())) >= 4


def test_m2_root_gold(ctx, fake_m2):
    # Hand derivation: the root has absent T1DM (n2) and requires GFR in [42,42] and a 180 d window.
    #  - has_t1dm: contains a T1DM fact -> violates the closed-world absent constraint.
    #  - egfr_70: value 70 is outside [42,42].
    #  - day_400: window 400 is outside [180,180].
    assert _matched(fake_m2, m2_patients(fake_m2), ctx) == {"exact"}


def test_edge_direction(ctx, fake_m1):
    p = m1_patients(fake_m1)["exact"]
    old = p.edge("n2", "n3")
    flipped = tuple(Edge(s="n3", t="n2", rel=e.rel, prov=e.prov, window=e.window) if e is old else e for e in p.edges)
    p = p.model_copy(update={"edges": flipped})
    assert not matches(fake_m1, p, ctx.hierarchy)


def test_provenance(ctx, fake_m1):
    p = m1_patients(fake_m1)["exact"]
    old = p.edge("n2", "n4")
    swapped = tuple(old.model_copy(update={"prov": "asserted"}) if e is old else e for e in p.edges)
    p = p.model_copy(update={"edges": swapped})
    assert not matches(fake_m1, p, ctx.hierarchy)


def test_matcher_independence():
    """Rewritten (Task 1): was imports limited to semgen.config/model/snomed (relation hierarchy); now
    semgen.model/bundle/snomed plus stdlib helpers, since relations compare by equality."""
    text = (pathlib.Path(__file__).parent / "support" / "matcher.py").read_text()
    mods = set()
    for n in ast.walk(ast.parse(text)):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            assert n.level == 0
            mods.add(n.module)
    assert mods <= {"__future__", "collections.abc", "datetime", "typing", "semgen.model", "semgen.bundle",
                    "semgen.snomed"}, mods
    assert ".contains(" not in text


def test_interval_holds_point():
    from tests.support.matcher import _interval_holds_point as hp
    iv = lambda lo, hi, lc=True, hc=True, u="%": Interval(lo=lo, hi=hi, lo_closed=lc, hi_closed=hc, unit=u)
    pt = lambda x, u="%": Interval.point(x, u)
    assert not hp(iv(0, 40, hc=False), pt(40))
    assert hp(iv(0, 40), pt(40))
    assert not hp(iv(3, 5, lc=False), pt(3))
    assert hp(iv(3, 5, lc=False), pt(5))
    assert not hp(iv(0, 40), pt(10, "mg"))
    assert hp(iv(65, None), pt(90))
    with pytest.raises(AssertionError):
        hp(iv(0, 40), iv(1, 2))


def test_production_never_imports_tests():
    files = list(_SRC.rglob("*.py"))
    assert files
    for p in files:
        assert "tests.support" not in p.read_text()
        for n in ast.walk(ast.parse(p.read_text())):
            names = [a.name for a in n.names] if isinstance(n, ast.Import) else \
                [n.module or ""] if isinstance(n, ast.ImportFrom) else []
            assert not any(x == "tests" or x.startswith("tests.") for x in names), p


# --- Task 1: bundles, dates, observations ---
import pytest as _pytest

from semgen.bundle import MotifBundle, MotifPart  # noqa: E402
from tests.support.matcher import UnknownBundleSemantics, matches_bundle  # noqa: E402
from tests.support.relevance import relaxed


# Rev 4: deletion moves need a relaxable relevance decision; these tests are about what deletions do, so they
# run with every candidate relaxable (tests/support/relevance.py). The gate itself: tests/test_relevance.py.
@_pytest.fixture
def ctx(ctx):
    return relaxed(ctx)



def _drug_motif(mid, code, rel="administered_drug"):
    from semgen.motif_io import parse_motif
    return parse_motif({"motif_id": mid, "anchor": "d",
                        "nodes": [{"id": "P", "type": "Patient", "role": "patient"},
                                  {"id": "d", "type": "Substance", "code": code, "polarity": "present",
                                   "role": "anchor"}],
                        "edges": [{"s": "P", "t": "d", "rel": rel, "prov": "asserted"}]}, None)


def _patient(*codes):
    m = _drug_motif("PAT", codes[0])
    for i, c in enumerate(codes[1:]):
        m = m.model_copy(update={"nodes": m.nodes + (Node(id=f"x{i}", type="Substance", role="exposure", code=c),),
                                 "edges": m.edges + (Edge(s="P", t=f"x{i}", rel="administered_drug",
                                                          prov="asserted"),)})
    return m


def _two_part(sem):
    from tests.conftest import DOX, MET
    return MotifBundle(bundle_id="B", semantics=sem, anchor_part="A",
                       parts=(MotifPart(part_id="A", motif=_drug_motif("A", DOX)),
                              MotifPart(part_id="C", motif=_drug_motif("C", MET))))


def test_matches_bundle_all_any(ctx):
    from tests.conftest import DAUNO, DOX, MET
    h = ctx.hierarchy
    both, dox, met, neither = _patient(DOX, MET), _patient(DOX), _patient(MET), _patient(DAUNO)
    assert [matches_bundle(_two_part("all"), p, h) for p in (both, dox, met, neither)] == [True, False, False, False]
    assert [matches_bundle(_two_part("any"), p, h) for p in (both, dox, met, neither)] == [True, True, True, False]
    single = MotifBundle.of(_drug_motif("A", DOX))
    assert matches_bundle(single, dox, h) and not matches_bundle(single, met, h)


def test_unknown_semantics_raises_without_assume(ctx):
    from tests.conftest import DOX
    with pytest.raises(UnknownBundleSemantics):
        matches_bundle(_two_part(None), _patient(DOX), ctx.hierarchy)


def test_assume_override_evaluates_both(ctx):
    from tests.conftest import DOX, MET
    b, h = _two_part(None), ctx.hierarchy
    assert not matches_bundle(b, _patient(DOX), h, assume="all")
    assert matches_bundle(b, _patient(DOX), h, assume="any")
    assert matches_bundle(b, _patient(DOX, MET), h, assume="all")


def test_or_alternatives_match_iff_some_alternative_matches(ctx):
    """Grouped OR alternatives are an "any" bundle of plain parts; no common summary decides membership."""
    from tests.conftest import ANTHRA, DAUNO, DOX
    h = ctx.hierarchy
    b = MotifBundle(bundle_id="B", semantics="any", anchor_part="M1",
                    parts=(MotifPart(part_id="M1", motif=_drug_motif("M1", DOX)),
                           MotifPart(part_id="M2", motif=_drug_motif("M2", DAUNO))))
    summary_only = _patient(ANTHRA)   # their common ancestor alone matches neither alternative
    assert matches(_drug_motif("L", ANTHRA), summary_only, h) and not matches_bundle(b, summary_only, h)
    assert matches_bundle(b, _patient(DOX), h) and matches_bundle(b, _patient(DAUNO), h)
    assert not matches_bundle(b.model_copy(update={"semantics": "all"}), _patient(DOX), h)   # AND is not OR


def test_relations_compare_by_equality(ctx):
    from tests.conftest import DOX
    pat = _drug_motif("A", DOX, rel="exposed_to_drug")
    assert not matches(pat, _patient(DOX), ctx.hierarchy) and matches(pat, _drug_motif("P1", DOX, "exposed_to_drug"),
                                                                       ctx.hierarchy)


def test_date_equality_in_matcher(ctx):
    from tests.conftest import DOX
    h = ctx.hierarchy
    pat = _drug_motif("A", DOX)
    pat = pat.replace_node(pat.node("d").model_copy(update={"dates": {"start": "2026-01-02"}}))
    def fact(d=None, edge=None):
        p = _patient(DOX)
        if d is not None:
            p = p.replace_node(p.node("d").model_copy(update={"dates": d}))
        if edge is not None:
            p = p.replace_edge(p.edge("P", "d").model_copy(update={"dates": edge}))
        return p
    assert matches(pat, fact({"start": "2026-01-02", "other": "2020-01-01"}), h)
    assert not matches(pat, fact({"start": "2026-01-03"}), h) and not matches(pat, fact(), h)
    epat = pat.replace_node(pat.node("d").model_copy(update={"dates": {}}))
    epat = epat.replace_edge(epat.edge("P", "d").model_copy(update={"dates": {"seen": "2026-05-05"}}))
    assert matches(epat, fact(edge={"seen": "2026-05-05"}), h) and not matches(epat, fact(edge={"seen": "2026-05-06"}), h)


def test_observations_need_one_distinct_fact_each(ctx):
    from semgen.model import Motif, Observation
    from tests.conftest import DISEASE, GFR
    h = ctx.hierarchy
    def lab(mid, *vals):
        nodes = [Node(id="P", type="Patient", role="patient"), Node(id="a", type="Disorder", role="anchor", code=DISEASE)]
        edges = [Edge(s="P", t="a", rel="has_condition", prov="asserted")]
        for i, v in enumerate(vals):
            nodes.append(Node(id=f"g{i}", type="Observable", role="outcome", code=GFR, value=Interval.point(v, "u")))
            edges.append(Edge(s="P", t=f"g{i}", rel="has_measurement", prov="asserted"))
        return Motif(motif_id=mid, anchor="a", nodes=tuple(nodes), edges=tuple(edges))
    obs = tuple(Observation(value=Interval(lo=lo, hi=hi, unit="u"), source_node=f"g{i}")
                for i, (lo, hi) in enumerate(((40, 45), (40, 45))))
    pat = lab("PAT", 42).replace_node(lab("PAT", 42).node("g0").model_copy(update={"value": None, "observations": obs}))
    assert matches(pat, lab("X", 41, 44), h)
    assert not matches(pat, lab("X", 41), h)            # one fact cannot serve two observations
    assert not matches(pat, lab("X", 41, 50), h)


# --- Task 2: bucketing, attribute deletion and A1 on synthetic patients ---
def _lab_root():
    """SYNTHETIC: two repeated GFR results of one fully identified test, each with its attached range."""
    import dataclasses

    from semgen.bundle import Subject
    from semgen.model import Motif, ReferenceRange, TestIdentity
    from tests.conftest import DISEASE, GFR
    t = TestIdentity(system="urn:synthetic:lab", code="GFR-S", method="calc", specimen="Serum")
    rr = ReferenceRange(interval=Interval.closed(30, 50, "u"), kind="reference", test=t, source="synthetic",
                        source_ref="r1")
    nodes = [Node(id="P", type="Patient", role="patient"), Node(id="a", type="Disorder", role="anchor", code=DISEASE)]
    edges = [Edge(s="P", t="a", rel="has_condition", prov="asserted")]
    for i, (v, d) in enumerate(((42, "2026-01-01"), (55, "2026-02-01")), start=1):
        nodes.append(Node(id=f"g{i}", type="Observable", role="outcome", code=GFR, value=Interval.point(v, "u"),
                          dates={"taken": d}, test=t, reference_range=rr))
        edges.append(Edge(s="P", t=f"g{i}", rel="has_measurement", prov="asserted"))
    return Motif(motif_id="LAB", anchor="a", nodes=tuple(nodes), edges=tuple(edges)), \
        (lambda ctx: dataclasses.replace(ctx, subject=Subject(sex="female", age_days=20000)))


def _lab_patients():
    from semgen.model import Motif
    from tests.conftest import DM, GFR, LVEF

    def pat(*facts, code=GFR):
        nodes = [Node(id="P", type="Patient", role="patient"), Node(id="x", type="Disorder", role="anchor", code=DM)]
        edges = [Edge(s="P", t="x", rel="has_condition", prov="asserted")]
        for i, (v, d) in enumerate(facts):
            nodes.append(Node(id=f"f{i}", type="Observable", role="outcome", code=code,
                              value=Interval.point(v, "u"), dates={"taken": d} if d else {}))
            edges.append(Edge(s="P", t=f"f{i}", rel="has_measurement", prov="asserted"))
        return Motif(motif_id="PAT", anchor="x", nodes=tuple(nodes), edges=tuple(edges))
    return {"exact": pat((42, "2026-01-01"), (55, "2026-02-01")),
            "both_reference": pat((35, "2026-01-01"), (40, "2026-02-01")),
            "low_and_high": pat((10, "2026-01-01"), (90, "2026-02-01")),
            "dates_swapped": pat((42, "2026-02-01"), (55, "2026-01-01")),
            "undated": pat((42, None), (55, None)),
            "one_result": pat((42, "2026-01-01")),
            "other_observable": pat((42, "2026-01-01"), (55, "2026-02-01"), code=LVEF)}


def _lab_lattice(ctx):
    import dataclasses

    from tests.support.ucum import test_ucum
    root, with_subject = _lab_root()
    c = dataclasses.replace(with_subject(ctx), ucum=test_ucum("u"))   # A1 validates units against UCUM
    lat = enumerate_lattice(root, c, Budget(max_depth=4))
    pats = _lab_patients()
    sets = {h: _matched(cand.motif, pats, c) for h, cand in lat.candidates.items()}
    return lat, sets


def test_monotone_with_new_operators(ctx):
    lat, sets = _lab_lattice(ctx)
    ops = {ch.op for e in lat.edges for ch in e.changes}
    assert {"normative_bucketing", "attribute_deletion", "attribute_aggregation"} <= ops
    bad = [(e.parent, e.child) for e in lat.edges if not sets[e.parent] <= sets[e.child]]
    assert bad == []
    assert sets[lat.root] == {"exact"}
    assert any(sets[e.parent] < sets[e.child] for e in lat.edges)      # non-vacuous


def test_kept_edges_preserve_match_set(ctx):
    lat, sets = _lab_lattice(ctx)
    kept = [e for e in lat.edges if e.changes and all(ch.meaning == "kept" for ch in e.changes)]
    assert kept and all(ch.op == "attribute_aggregation" for e in kept for ch in e.changes)
    assert [(e.parent, e.child) for e in kept if sets[e.parent] != sets[e.child]] == []
