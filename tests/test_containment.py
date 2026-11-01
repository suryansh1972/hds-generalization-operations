"""Containment/monotonicity of the generalization lattice on synthetic patients (D16)."""
import ast
import pathlib

from semgen.lattice import enumerate_lattice
import pytest

from semgen.model import Edge, Interval, Node
from tests.conftest import ANTHRA
from tests.support.matcher import matches
from tests.support.patients import m1_patients, m2_patients

M1_GOLD = {"exact", "extra_condition"}           # written BEFORE running anything
_SRC = pathlib.Path(__file__).resolve().parent.parent / "src"


def _matched(motif, pats, ctx):
    return {pid for pid, p in pats.items() if matches(motif, p, ctx.hierarchy, ctx.config.relations)}


def test_m1_root_gold(ctx, fake_m1):
    got = {pid for pid, p in m1_patients(fake_m1).items() if matches(fake_m1, p, ctx.hierarchy, ctx.config.relations)}
    assert got == M1_GOLD


def test_matcher_is_one_to_one(ctx, fake_m1):
    two = fake_m1.model_copy(update={
        "nodes": fake_m1.nodes + (Node(id="n9", type="Substance", role="exposure", code=ANTHRA),),
        "edges": fake_m1.edges + (Edge(s="P", t="n9", rel="administered_drug", prov="asserted"),)})
    two = two.replace_node(two.node("n2").model_copy(update={"code": ANTHRA, "attrs": {}}))
    assert not matches(two, m1_patients(fake_m1)["exact"], ctx.hierarchy, ctx.config.relations)   # one DOX fact, two pattern drugs


def test_closed_world_descendant_of_absent(ctx, fake_m2):
    ps = m2_patients(fake_m2); assert not matches(fake_m2, ps["has_t1dm"], ctx.hierarchy, ctx.config.relations)


def test_monotone_along_every_lattice_edge(ctx, fake_m1, fake_m2):
    for root, pats in ((fake_m1, m1_patients(fake_m1)), (fake_m2, m2_patients(fake_m2))):
        lat = enumerate_lattice(root, ctx, 3)
        sets = {h: {pid for pid, p in pats.items() if matches(c.motif, p, ctx.hierarchy, ctx.config.relations)} for h, c in lat.candidates.items()}
        bad = [(e.parent, e.child) for e in lat.edges if not sets[e.parent] <= sets[e.child]]
        assert bad == []


def test_self_match(ctx, fake_m1, fake_m2):
    for root in (fake_m1, fake_m2):
        patient = root.without({n.id for n in root.nodes if n.polarity == "absent"}, {e.key for e in root.edges if e.t in {n.id for n in root.nodes if n.polarity == "absent"}})
        for c in enumerate_lattice(root, ctx, 3).candidates.values():
            assert matches(c.motif, patient, ctx.hierarchy, ctx.config.relations)


def test_matcher_not_imported_by_production():
    import pathlib; assert not any("tests.support" in p.read_text() for p in pathlib.Path("src").rglob("*.py"))


# --- extras ---------------------------------------------------------------------------------
def test_non_vacuous_m1(ctx, fake_m1):
    pats = m1_patients(fake_m1)
    lat = enumerate_lattice(fake_m1, ctx, 3)
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
    assert not matches(fake_m1, p, ctx.hierarchy, ctx.config.relations)


def test_provenance(ctx, fake_m1):
    p = m1_patients(fake_m1)["exact"]
    old = p.edge("n2", "n4")
    swapped = tuple(old.model_copy(update={"prov": "asserted"}) if e is old else e for e in p.edges)
    p = p.model_copy(update={"edges": swapped})
    assert not matches(fake_m1, p, ctx.hierarchy, ctx.config.relations)


def test_matcher_independence():
    text = (pathlib.Path(__file__).parent / "support" / "matcher.py").read_text()
    mods = set()
    for n in ast.walk(ast.parse(text)):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            assert n.level == 0
            mods.add(n.module)
    assert mods <= {"__future__", "semgen.config", "semgen.model", "semgen.snomed"}, mods
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
