import pytest
from hypothesis import given, settings, strategies as st

from semgen.config import ConfigError, ExcludedRoot, SnomedBoundaryConfig
from semgen.snomed import FsnError, Hierarchy
from semgen.snomed_floor import SnomedBoundaryPolicy

STRUCT = "S0"
STRUCT_FSN = "Substance categorized by structure (substance)"


def cfg(ceiling=2500, roots=((STRUCT_FSN, "structural"),), ctype="inferred"):
    return SnomedBoundaryConfig(max_descendants=ceiling, characteristic_type=ctype,
                                excluded_ancestor_roots=tuple(ExcludedRoot(fsn=f, reason=r) for f, r in roots))


def build(parents, fsn, active=None, **kw):
    h = Hierarchy.from_maps({c: set(p) for c, p in parents.items()}, fsn,
                            set(fsn) if active is None else active, "REL", "ED")
    return h, SnomedBoundaryPolicy(h, cfg(**kw))


def star(n):
    parents = {f"k{i}": {"P"} for i in range(n)}
    parents["C"] = {"P"}
    fsn = {c: f"{c} (disorder)" for c in [*parents, "P"]}
    return build(parents, fsn, roots=())


def test_1296_descendants_accepted():
    _, p = star(1295)  # 1295 + C
    d = p.check_lift("C", "P")
    assert d.ok and d.reason is None and d.detail == {"descendant_count": 1296, "ceiling": 2500, "semantic_tag": "disorder"}


def test_exact_ceiling_accepted():
    h, _ = star(2499)
    p = SnomedBoundaryPolicy(h, cfg(ceiling=2500, roots=()))
    assert h.descendant_count("P") == 2500 and p.check_lift("C", "P").ok


def test_over_ceiling_blocked():
    _, p = star(2500)
    d = p.check_lift("C", "P")
    assert not d.ok and d.reason == "above_descendant_ceiling"
    assert d.detail == {"parent": "P", "descendant_count": 2501, "ceiling": 2500}


def test_polyhierarchy_counted_once():
    parents = {"A": {"P"}, "B": {"P"}, "D": {"A", "B"}, "C": {"P"}}
    fsn = {c: f"{c} (disorder)" for c in [*parents, "P"]}
    h, p = build(parents, fsn, ceiling=4, roots=())
    assert h.descendant_count("P") == 4 and p.check_lift("C", "P").ok
    h, p = build(parents, fsn, ceiling=3, roots=())
    assert p.check_lift("C", "P").reason == "above_descendant_ceiling"


SUB = {"S0": STRUCT_FSN, "S1": "Struct child (substance)", "M": "Mechanism grouper (substance)",
       "R": "Root (substance)", "X": "Drug X (substance)"}


def sub_world():
    parents = {"S0": {"R"}, "S1": {"S0"}, "M": {"R"}, "X": {"S1", "M"}}
    return build(parents, SUB)


def test_structural_root_and_subtree_blocked():
    _, p = sub_world()
    for par in ("S0", "S1"):
        d = p.check_lift("X", par)
        assert not d.ok and d.reason == "excluded_ancestor_root"
        assert d.detail == {"parent": par, "excluded_root": "S0", "excluded_fsn": STRUCT_FSN, "reason": "structural"}


def test_unrelated_substance_branch_allowed():
    assert sub_world()[1].check_lift("X", "M").ok


def test_multi_parent_substance_keeps_allowed_branch():
    _, p = sub_world()
    assert [p.check_lift("X", q).ok for q in ("S1", "M")] == [False, True]


def test_two_excluded_roots_reports_first_sorted():
    parents = {"A": {"R"}, "B": {"R"}, "P": {"A", "B"}, "X": {"P"}}
    fsn = {"A": "A (substance)", "B": "B (substance)", "R": "R (substance)", "P": "P (substance)", "X": "X (substance)"}
    _, p = build(parents, fsn, roots=(("B (substance)", "b"), ("A (substance)", "a")))
    assert p.check_lift("X", "P").detail["excluded_root"] == "A"


def test_unresolved_root_fails_closed():
    with pytest.raises(FsnError):
        build({}, {"A": "A (disorder)"}, roots=(("Nope (substance)", "x"),))


def test_ambiguous_root_fails_closed():
    with pytest.raises(FsnError):
        build({}, {"A": "Dup (substance)", "B": "Dup (substance)"}, roots=(("Dup (substance)", "x"),))


def test_retired_root_fails_closed():
    with pytest.raises(FsnError):
        build({}, {"A": "Old (substance)"}, active=set(), roots=(("Old (substance)", "x"),))


def test_characteristic_type_mismatch_raises():
    h = Hierarchy.from_maps({}, {}, set())
    with pytest.raises(ConfigError):
        SnomedBoundaryPolicy(h, SnomedBoundaryConfig.model_construct(
            max_descendants=1, characteristic_type="stated", excluded_ancestor_roots=()))


def test_semantic_tag_change_blocked():
    _, p = build({"C": {"P"}}, {"C": "C (disorder)", "P": "P (finding)"}, roots=())
    d = p.check_lift("C", "P")
    assert d.reason == "semantic_tag_changed" and d.detail == {"parent": "P", "child_tag": "disorder", "parent_tag": "finding"}


def test_missing_tag_fails_closed():
    _, p = build({"C": {"P"}}, {"C": "C (disorder)", "P": "P no tag"}, roots=())
    d = p.check_lift("C", "P")
    assert not d.ok and d.reason == "no_semantic_tag" and d.detail["parent_tag"] is None
    _, p = build({"C": {"P"}}, {"C": "C no tag", "P": "P (disorder)"}, roots=())
    assert p.check_lift("C", "P").reason == "no_semantic_tag"


def test_inactive_parent_blocked():
    _, p = build({"C": {"P"}}, {"C": "C (disorder)", "P": "P (disorder)"}, active={"C"}, roots=())
    d = p.check_lift("C", "P")
    assert d.reason == "inactive_parent" and d.detail == {"parent": "P"}


def test_fresh_decision_each_call():
    _, p = star(3)
    a, b = p.check_lift("C", "P"), p.check_lift("C", "P")
    assert a == b and a is not b and a.detail is not b.detail


def test_anchors_empty():
    assert star(1)[1].anchors("C") == frozenset()


def test_provenance_is_draft_and_complete():
    _, p = sub_world()
    pv = p.provenance
    assert pv["status"].startswith("DRAFT") and pv["mode"] == "snomed_boundary"
    assert pv["max_descendants"] == 2500 and pv["characteristic_type"] == "inferred"
    assert pv["snomed_release"] == "REL" and pv["snomed_edition"] == "ED"
    assert pv["semantic_tag_rule"] == "parent must keep the child's FSN semantic tag"
    assert pv["excluded_ancestor_roots"] == [{"concept_id": "S0", "fsn": STRUCT_FSN, "reason": "structural"}]


@st.composite
def _dags(draw):
    n = draw(st.integers(4, 14))
    parents = {"n0": set()}
    for i in range(1, n):
        parents[f"n{i}"] = {f"n{j}" for j in draw(st.sets(st.integers(0, i - 1), min_size=1, max_size=3))}
    return parents, draw(st.integers(1, n))


@settings(max_examples=100, deadline=None)
@given(_dags())
def test_blocked_set_is_upward_closed(world):
    parents, ceiling = world
    h, p = build(parents, {c: f"{c} (disorder)" for c in parents}, ceiling=ceiling, roots=())
    for c in parents:
        for par in h.ancestors(c):
            if p.check_lift(c, par).reason == "above_descendant_ceiling":
                for a in h.ancestors(par):
                    assert p.check_lift(c, a).reason == "above_descendant_ceiling"


def test_every_reason_through_concept_lift():
    from semgen.config import load_config
    from semgen.operators.base import GenContext
    from semgen.operators.concept_lift import concept_lift
    from tests.conftest import _CONFIG_PATH, one_node_motif
    parents = {"S0": {"R"}, "B": {"R"}, "T": {"R"}, "Y1": {"B"}, "Y2": {"B"}, "X": {"S0", "B", "T"}}
    fsn = {"R": "R (substance)", "S0": STRUCT_FSN, "B": "B (substance)", "T": "T (finding)",
           "Y1": "Y1 (substance)", "Y2": "Y2 (substance)", "X": "X (substance)"}
    h, p = build(parents, fsn, ceiling=2)
    r = concept_lift(one_node_motif("X"), GenContext(h, load_config(_CONFIG_PATH), p))
    got = {b.detail["parent"]: b for b in r.blocked}
    assert {k: v.reason for k, v in got.items()} == {
        "S0": "excluded_ancestor_root", "B": "above_descendant_ceiling", "T": "semantic_tag_changed"}
    assert got["S0"].detail["reason"] == "structural" and got["S0"].detail["excluded_root"] == "S0"
    assert got["B"].detail["descendant_count"] == 3 and got["T"].detail["parent_tag"] == "finding"
    assert not r.moves
