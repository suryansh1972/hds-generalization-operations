import copy
import json
from pathlib import Path

import pytest
from hypothesis import HealthCheck, event, given, settings, strategies as st

from semgen.floors import FloorDecision, PhecodeFloorPolicy
from semgen.icd10map import Icd10Map
from semgen.phecodex import PhecodeX, truncate
from semgen.snomed import Hierarchy
from semgen.sources import SourceError
from tests.conftest import (BRCA, CKD, DISEASE, DM, FAKE_ICD, FAKE_PX, FAKE_ROLLUP, MAL_THORAX, NEO_BREAST, RA,
                            ROOT, T1DM, T2DM)


def make(h, icd, px=FAKE_PX, rollup=FAKE_ROLLUP, level="first_decimal"):
    return PhecodeFloorPolicy(h, Icd10Map.from_maps(icd), PhecodeX.from_maps(px, rollup), level)


# --- PhecodeX ----------------------------------------------------------------
def test_prefix_fallback():
    px = PhecodeX.from_maps({"M06.9": {"MS_705.1"}}, {})
    assert px.phecodes_for_icd("M06.99") == ({"MS_705.1"}, "M06.9")


def test_no_ancestor_code_gives_nothing():
    assert PhecodeX.from_maps({}, {}).phecodes_for_icd("J95.89") == (frozenset(), None)


def test_prefix_fallback_strips_trailing_dot_and_stops_at_three():
    px = PhecodeX.from_maps({"E11": {"EM_202"}}, {})
    assert px.phecodes_for_icd("E11.9") == ({"EM_202"}, "E11")
    assert px.phecodes_for_icd("E1") == (frozenset(), None)


def test_truncate_levels():
    assert truncate("GU_582.21", "first_decimal") == "GU_582.2" and truncate("GU_582.21", "integer") == "GU_582"
    assert truncate("GU_582", "first_decimal") == "GU_582" and truncate("GU_582.2", "first_decimal") == "GU_582.2"
    with pytest.raises(ValueError):
        truncate("GU_582", "bogus")


def test_rolls_up_reflexive_and_directed():
    px = PhecodeX.from_maps({}, {"A_1.1": {"A_1"}})
    assert px.rolls_up("A_1", "A_1") and px.rolls_up("A_1.1", "A_1") and not px.rolls_up("A_1", "A_1.1")


def test_load_fixture_tables():
    px = PhecodeX.load(Path(__file__).parent / "fixtures" / "phecodex")
    assert px.phecodes_for_icd("E11.9") == ({"EM_202", "EM_202.2"}, "E11.9")
    assert px.phecodes_for_icd("M06.99")[1] == "M06.9"
    assert px.rolls_up("EM_202.2", "EM_202") and not px.rolls_up("EM_202", "EM_202.2")
    assert px.label("EM_202") == "Type 2 diabetes" and px.label("ZZ_9") is None


def test_from_config_missing_files_raises(tmp_path, fake_h):
    from semgen.config import load_config
    src = load_config(Path(__file__).parent.parent / "config" / "generalization.yaml").floor_source
    with pytest.raises(SourceError):
        PhecodeFloorPolicy.from_config(fake_h, "tests/fixtures/icd10map/Terminology", src, tmp_path)


# --- policy ------------------------------------------------------------------
def test_anchors_most_specific(fake_floors):
    assert fake_floors.anchors(T2DM) == {"EM_202.2"} and fake_floors.anchors(BRCA) == {"CA_105", "CA_130"}


def test_breast_cancer_thorax_allowed_neoplasm_blocked(fake_floors):
    ok = fake_floors.check_lift(BRCA, MAL_THORAX)
    assert ok.ok and ok.reason is None
    assert ok.detail == {"anchors": ["CA_105", "CA_130"], "phecode_level": "first_decimal",
                         "checked_descendants": 2}
    bad = fake_floors.check_lift(BRCA, NEO_BREAST)
    assert not bad.ok and bad.reason == "outside_floor"
    assert bad.detail["blocking_descendant"] == NEO_BREAST and bad.detail["parent"] == NEO_BREAST
    assert bad.detail["anchor"] == "CA_105" and bad.detail["blocking_fsn"] is None


def test_t2dm_to_dm_blocked_by_t1dm(fake_floors):
    d = fake_floors.check_lift(T2DM, DM)
    assert d.reason == "outside_floor"
    assert d.detail["blocking_descendant"] == T1DM and d.detail["anchor"] == "EM_202.2"
    assert d.detail["parent"] == DM


def test_unmapped_concept(fake_floors):
    d = fake_floors.check_lift(RA, DISEASE)
    assert d.reason == "unmapped" and not d.ok and d.detail == {"code": RA}
    assert fake_floors.check_lift(DISEASE, ROOT).reason == "unmapped"


def test_every_anchor_required(fake_h):
    icd = {**FAKE_ICD, MAL_THORAX: {"X1"}}
    p = make(fake_h, icd, {**FAKE_PX, "X1": {"CA_105"}})
    d = p.check_lift(BRCA, MAL_THORAX)
    assert d.reason == "outside_floor" and d.detail["blocking_descendant"] == MAL_THORAX
    assert d.detail["anchor"] == "CA_130"


def test_coarser_parent_blocked(fake_h):
    icd = {BRCA: {"Q1"}, MAL_THORAX: {"Q2"}}
    p = make(fake_h, icd, {"Q1": {"CA_105.1"}, "Q2": {"CA_105"}})
    assert p.anchors(BRCA) == {"CA_105.1"}
    d = p.check_lift(BRCA, MAL_THORAX)
    assert d.reason == "outside_floor" and d.detail["blocking_descendant"] == MAL_THORAX
    assert d.detail["anchor"] == "CA_105.1"


def test_ifa_only_descendant_blocks(fake_h):
    icd = {k: v for k, v in FAKE_ICD.items() if k != MAL_THORAX}   # IFA-only rows leave no usable targets
    d = make(fake_h, icd).check_lift(BRCA, MAL_THORAX)
    assert d.reason == "outside_floor" and d.detail["blocking_descendant"] == MAL_THORAX


def test_multi_mapped_descendant_counts(fake_h):
    icd = {**FAKE_ICD, MAL_THORAX: {"Y1"}}
    p = make(fake_h, icd, {**FAKE_PX, "Y1": {"CA_105", "GU_582.2"}, "C50.9": {"CA_105"}})
    assert p.anchors(BRCA) == {"CA_105"} and p.check_lift(BRCA, MAL_THORAX).ok


def test_blocker_is_deterministic(fake_floors):
    got = [fake_floors.check_lift(BRCA, DISEASE) for _ in range(3)]
    assert got[0] == got[1] == got[2]
    assert got[0].detail["blocking_descendant"] == NEO_BREAST   # smallest failing id; DISEASE itself is larger


def test_inactive_descendant_ignored(fake_h):
    parents = {k: set(v) for k, v in fake_h._parents.items()}
    parents["999"] = {MAL_THORAX}   # unmapped but inactive
    active = set(fake_h._active)
    ph = Hierarchy.from_maps(parents, {}, active)
    assert make(ph, FAKE_ICD).check_lift(BRCA, MAL_THORAX).ok
    ph2 = Hierarchy.from_maps(parents, {}, active | {"999"})
    d = make(ph2, FAKE_ICD).check_lift(BRCA, MAL_THORAX)
    assert d.reason == "outside_floor" and d.detail["blocking_descendant"] == "999"


def test_integer_level_changes_anchor(fake_h):
    icd = {**FAKE_ICD, CKD: {"Z1"}}
    px = {**FAKE_PX, "Z1": {"GU_582.21"}}
    assert make(fake_h, icd, px, level="first_decimal").anchors(CKD) == {"GU_582.2"}
    assert make(fake_h, icd, px, level="integer").anchors(CKD) == {"GU_582"}


def test_bad_level_rejected(fake_h):
    with pytest.raises(ValueError):
        make(fake_h, FAKE_ICD, level="decimal")


def test_provenance_and_json_safe(fake_floors):
    assert fake_floors.provenance == {"floor_source": "phecodex", "phecode_level": "first_decimal",
                                      "icd10_map_refset": "447562003", "icd10_map_release": "TEST"}
    for d in (fake_floors.check_lift(BRCA, MAL_THORAX), fake_floors.check_lift(BRCA, NEO_BREAST),
              fake_floors.check_lift(RA, DISEASE)):
        json.dumps(d.detail)
    assert isinstance(fake_floors.phecodes(BRCA), frozenset)


def test_pure_and_deterministic(fake_h):
    icd = Icd10Map.from_maps(FAKE_ICD)
    px = PhecodeX.from_maps(FAKE_PX, FAKE_ROLLUP)
    pol = PhecodeFloorPolicy(fake_h, icd, px, "first_decimal")
    snap = copy.deepcopy((fake_h._parents, fake_h._active, icd._targets, px._icd, px._rollup))
    results = []
    for _ in range(3):
        results.append([pol.check_lift(c, p) for c in (BRCA, T2DM, RA, CKD) for p in (MAL_THORAX, NEO_BREAST, DM, DISEASE)])
    assert results[0] == results[1] == results[2]
    assert snap == (fake_h._parents, fake_h._active, icd._targets, px._icd, px._rollup)
    # mutating a returned decision must not leak into the memo
    r = pol.check_lift(BRCA, MAL_THORAX)
    r.detail["anchors"].append("JUNK")
    assert pol.check_lift(BRCA, MAL_THORAX).detail["anchors"] == ["CA_105", "CA_130"]
    with pytest.raises(Exception):
        r.ok = False  # frozen


# --- S6: no drift ------------------------------------------------------------
_PHE = ["A_1", "A_1.1", "A_1.2", "A_1.11", "B_2", "B_2.1"]
_ROLL = {"A_1": {"A_1"}, "A_1.1": {"A_1.1", "A_1"}, "A_1.2": {"A_1.2", "A_1"},
         "A_1.11": {"A_1.11", "A_1"}, "B_2": {"B_2"}, "B_2.1": {"B_2.1", "B_2"}}
_ICD = [f"I{i}" for i in range(6)]
_N = 7


def _closure(ps):
    return set().union(*(_ROLL[p] for p in ps)) if ps else set()


def _build_parents(draw):
    parents = {"n0": set(), "n1": {"n0"}, "n2": {"n1"}}   # explicit spine n0 <- n1 <- n2
    for i in range(3, _N):
        parents[f"n{i}"] = {f"n{j}" for j in draw(st.sets(st.integers(0, i - 1), min_size=1, max_size=3))}
    return parents


@st.composite
def _worlds(draw):
    parents = _build_parents(draw)
    icd_px = {c: _closure(draw(st.sets(st.sampled_from(_PHE), min_size=1, max_size=3))) for c in _ICD}
    targets = {n: set(draw(st.sets(st.sampled_from(_ICD), min_size=1, max_size=4))) for n in parents}
    return parents, icd_px, targets, draw(st.sampled_from(["first_decimal", "integer"]))


def _policy(world):
    parents, icd_px, targets, level = world
    h = Hierarchy.from_maps(parents, {}, set(parents))
    return h, PhecodeFloorPolicy(h, Icd10Map.from_maps(targets), PhecodeX.from_maps(icd_px, _ROLL), level)


def _oracle(world, c, p):
    """Independent brute-force S3-S5 (no floors.py / phecodex.py internals): (anchors of c, c->p allowed)."""
    parents, icd_px, targets, level = world

    def rolls(a, b):
        return a == b or b in _ROLL[a]

    def trunc(x):
        pre, num = x.split("_")
        whole, _, frac = num.partition(".")
        return f"{pre}_{whole}" if level == "integer" or not frac else f"{pre}_{whole}.{frac[0]}"

    def phe(n):
        return {x for t in targets[n] for x in icd_px[t]}

    def anchors(n):
        a = {trunc(x) for x in phe(n)}
        return {q for q in a if not any(r != q and rolls(r, q) for r in a)}

    kids = {}
    for n, ps in parents.items():
        for q in ps:
            kids.setdefault(q, set()).add(n)
    below, todo = {p}, [p]
    while todo:
        for k in kids.get(todo.pop(), ()):
            if k not in below:
                below.add(k)
                todo.append(k)
    anc = anchors(c)
    if not anc:
        return anc, False
    return anc, all(any(rolls(x, q) or rolls(trunc(x), q) for x in phe(d)) for d in below for q in anc)


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(_worlds())
def test_no_drift_along_allowed_chains(world):
    parents, _, _, _ = world
    h, pol = _policy(world)
    chains = 0
    for c in parents:
        for p in h.parents(c):
            ok = pol.check_lift(c, p).ok
            assert ok == _oracle(world, c, p)[1], (c, p)       # oracle agreement
            assert pol.anchors(c) == _oracle(world, c, p)[0], c
            if not ok:
                continue
            for q in pol.anchors(c):                              # S6 lemma
                assert any(pol._px.rolls_up(r, q) for r in pol.anchors(p)), (c, p, q)
            for g in h.parents(p):
                if pol.check_lift(p, g).ok:
                    chains += 1
                    _, fresh = _policy(world)                     # no shared memo
                    assert fresh.check_lift(c, g).ok, (c, p, g)
    event(f"chains>0={chains > 0}")


def test_chain_coverage_deterministic():
    """A fixed world with an allowed 2-step chain n3 -> n2 -> n1, checked on a fresh policy."""
    parents = {"n0": set(), "n1": {"n0"}, "n2": {"n1"}, "n3": {"n2"}}
    icd_px = {"I0": _closure({"A_1.11"}), "I1": _closure({"A_1.1"}), "I2": _closure({"A_1.2"}), "I3": set()}
    targets = {"n0": {"I1"}, "n1": {"I0"}, "n2": {"I1"}, "n3": {"I0", "I1"}}
    world = (parents, icd_px, targets, "first_decimal")
    h, pol = _policy(world)
    assert pol.check_lift("n3", "n2").ok and pol.check_lift("n2", "n1").ok
    assert _policy(world)[1].check_lift("n3", "n1").ok
    assert all(pol.check_lift(c, p).ok == _oracle(world, c, p)[1] for c in parents for p in h.parents(c))


# --- real data ---------------------------------------------------------------
# (code, anchors, {parent: (blocking_descendant | None, anchor reported by the prototype run)})
_REAL = [
    ("254837009", {"CA_105", "CA_130"},
     {"126926005": ("1080431000119107", "CA_105"), "188361007": ("105041000119109", "CA_105")}),
    ("44054006", {"EM_202.2"}, {"73211009": ("105401000119101", "EM_202.2")}),
    ("703228009", {"CA_102.1", "CA_130"}, {"254637007": (None, None)}),
    ("254637007", {"CA_102.1", "CA_130"}, {"448993007": ("105041000119109", "CA_102.1")}),
    ("69896004", {"BI_181", "MS_705.1"},
     {"3723001": ("10193001", "BI_181"), "85828009": ("10743271000119103", "BI_181")}),
    ("709044004", {"GU_582.2"},
     {"128290005": ("10194007", "GU_582.2"), "236423003": ("10697004", "GU_582.2")}),
]


@pytest.mark.snomed
@pytest.mark.phecodex
@pytest.mark.parametrize("code,anchors,decisions", _REAL)
def test_real_prototype_table(real_floors, real_h, code, anchors, decisions):
    assert real_floors.anchors(code) == anchors
    assert set(decisions) == set(real_h.parents(code))
    for parent, (blocker, anchor) in decisions.items():
        d = real_floors.check_lift(code, parent)
        if blocker is None:
            assert d.ok is True, d
            assert len(real_h.descendants_or_self(parent)) == 36
        else:
            assert d.ok is False and d.reason == "outside_floor", d
            assert d.detail["blocking_descendant"] == blocker and d.detail["anchor"] == anchor, d
