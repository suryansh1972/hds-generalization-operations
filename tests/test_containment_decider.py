"""The exact decision ``∧ S ⇒ ∨ T`` (spec §3) and the production matcher, against the independent oracle.

Every verdict is checked three ways: an INVALID counterexample must be confirmed by the oracle (it matches every
source and no target); a VALID verdict must survive an exhaustive search of a small patient universe built from the
cases' own alphabet; and a counterexample found by that search forces INVALID. The universe check is evidence, not a
proof (the proof is spec §3.3); it is what shows the finite instances cover the cases below.

Synthetic hierarchy (codes are opaque strings, no clinical content)::

    root ─ a ─ b ─ e ─ d        e, f: children of both b and c (two maximal common descendants of b and c)
    │      │   ├─ f             g: child of b only
    │      │   ├─ g             y: child of b and of x (a present branch overlapping the absent branch x)
    │      │   └─ y             z: child of a, inactive
    │      ├─ c ─ e, f
    │      └─ z (inactive)
    └─ x ─ y
"""
from __future__ import annotations

import itertools

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from semgen.containment import decide, fresh_type, meet, representatives
from semgen.matching import matches as production_matches
from semgen.model import PATIENT_ID, Edge, Grouping, Interval, Motif, Node, Observation
from semgen.snomed import Hierarchy
from tests.support.matcher import matches as oracle

PARENTS = {"a": {"root"}, "b": {"a"}, "c": {"a"}, "e": {"b", "c"}, "f": {"b", "c"}, "d": {"e"}, "g": {"b"},
           "x": {"root"}, "y": {"x", "b"}, "z": {"a"}}
CONCEPTS = sorted({"root", *PARENTS})
H = Hierarchy.from_maps(PARENTS, {c: c for c in CONCEPTS}, set(CONCEPTS) - {"z"})
ACTIVE = [c for c in CONCEPTS if c != "z"]
P = Node(id=PATIENT_ID, type="Patient", role="patient")
U = "u"
SETTINGS = settings(suppress_health_check=[HealthCheck.too_slow], deadline=None, max_examples=120, derandomize=True)


# --- builders ------------------------------------------------------------------------------------------------------


def n(i: str, code: str | None = None, *, role: str = "x", type: str = "T", value: Interval | None = None,
      absent: bool = False, **kw) -> Node:
    return Node(id=i, type=type, role=role, code=code, value=value, polarity="absent" if absent else "present", **kw)


def pat(mid: str, *nodes: Node, edges: tuple[Edge, ...] | None = None) -> Motif:
    """``P`` plus ``nodes`` (the first one is the anchor), each present node joined to ``P`` by ``r``."""
    if edges is None:
        edges = tuple(Edge(s=PATIENT_ID, t=x.id, rel="r", prov="asserted") for x in nodes if x.polarity == "present")
    return Motif(motif_id=mid, anchor=nodes[0].id if nodes else PATIENT_ID, nodes=(P, *nodes), edges=edges)


def iv(lo, hi, lo_closed=True, hi_closed=True) -> Interval:
    return Interval(lo=lo, hi=hi, lo_closed=lo_closed, hi_closed=hi_closed, unit=U)


def patient(*facts: tuple[str, str | None, float | None]) -> Motif:
    """``P`` plus one fact per ``(type, code, point)``, each joined to ``P`` by ``r``."""
    nodes = [P] + [Node(id=f"q{i}", type=t, role="x", code=c, value=None if v is None else Interval.point(v, U))
                   for i, (t, c, v) in enumerate(facts)]
    return Motif(motif_id="U", anchor=PATIENT_ID, nodes=tuple(nodes),
                 edges=tuple(Edge(s=PATIENT_ID, t=x.id, rel="r", prov="asserted") for x in nodes[1:]))


def universe(codes=(None, *ACTIVE), points=(None,), types=("T",), max_facts=2) -> list[Motif]:
    specs = [(t, c, v) for t in types for c in codes for v in points]
    return [patient(*combo) for k in range(max_facts + 1) for combo in itertools.combinations_with_replacement(specs, k)]


GRID = tuple(x / 2 for x in range(-2, 23))   # -1.0 .. 11.0 in steps of 0.5: every cell of the endpoints 0, 5, 10
SMALL = universe(max_facts=3)


def counterexample_of(v) -> Motif:
    return Motif.model_validate(v.evidence["counterexample"])


def brute(sources, targets, patients) -> Motif | None:
    return next((p for p in patients if all(oracle(s, p, H) for s in sources)
                 and not any(oracle(t, p, H) for t in targets)), None)


def check(sources, targets, patients=SMALL, limit=None):
    """The decision, cross-checked against the oracle (see the module docstring); returns the verdict."""
    v = decide(sources, targets, H, limit)
    assert v.status in {"VALID", "INVALID", "UNKNOWN"}
    if v.status == "INVALID":
        cx = counterexample_of(v)
        assert all(oracle(s, cx, H) for s in sources) and not any(oracle(t, cx, H) for t in targets), v
    found = brute(sources, targets, patients)
    if v.status == "VALID":
        assert found is None, (v, found)
    if found is not None:
        assert v.status in {"INVALID", "UNKNOWN"}, (v, found)
    return v


# --- the production matcher is the oracle's semantics --------------------------------------------------------------

GROUP = Grouping(kind="ontology", system="s", code="b", version="v", source="t")


@st.composite
def patterns(draw, mid: str = "M") -> Motif:
    nodes = []
    for i in range(draw(st.integers(0, 2))):
        kind = draw(st.sampled_from(["plain", "plain", "obs", "group"]))
        role = draw(st.sampled_from(["x", "context"]))
        code = draw(st.sampled_from([None, "a", "b", "c", "e", "y"]))
        if kind == "obs":
            obs = tuple(Observation(value=draw(st.sampled_from([iv(0, 5), iv(5, 10), iv(0, 10)])), source_node=f"o{j}")
                        for j in range(draw(st.integers(1, 2))))
            nodes.append(n(f"n{i}", code, role=role, observations=obs))
        elif kind == "group":
            members = tuple(n(m, draw(st.sampled_from(["b", "c", "e"])), role=role) for m in sorted({f"n{i}", "m9"}))
            nodes.append(n(f"n{i}", role=role, members=members, grouping=GROUP))
        else:
            nodes.append(n(f"n{i}", code, role=role, value=draw(st.sampled_from([None, iv(0, 5), iv(5, 10, False)]))))
    if draw(st.booleans()):
        nodes.append(n("z0", draw(st.sampled_from(["b", "e", "x"])), absent=True))
    edges = [Edge(s=PATIENT_ID, t=x.id, rel=draw(st.sampled_from(["r", "q"])), prov="asserted")
             for x in nodes if x.polarity == "present"]
    present = [x.id for x in nodes if x.polarity == "present"]
    if len(present) == 2 and draw(st.booleans()):
        edges.append(Edge(s=present[0], t=present[1], rel="r", prov="asserted"))
    return Motif(motif_id=mid, anchor=nodes[0].id if nodes else PATIENT_ID, nodes=(P, *nodes), edges=tuple(edges))


@st.composite
def patients(draw) -> Motif:
    facts = [Node(id=f"q{i}", type="T", role=draw(st.sampled_from(["x", "context"])),
                  code=draw(st.sampled_from([None, *ACTIVE])),
                  value=draw(st.sampled_from([None, *(Interval.point(x, U) for x in (0, 2.5, 5, 7.5, 10))])))
             for i in range(draw(st.integers(0, 3)))]
    edges = [Edge(s=PATIENT_ID, t=f.id, rel=draw(st.sampled_from(["r", "q"])), prov="asserted") for f in facts]
    if len(facts) >= 2 and draw(st.booleans()):
        edges.append(Edge(s=facts[0].id, t=facts[1].id, rel="r", prov="asserted"))
    return Motif(motif_id="U", anchor=PATIENT_ID, nodes=(P, *facts), edges=tuple(edges))


@SETTINGS
@given(patterns(), st.lists(patients(), min_size=1, max_size=8))
def test_production_matcher_agrees_with_the_oracle(pattern, pats):
    for p in pats:
        assert production_matches(pattern, p, H) == oracle(pattern, p, H), (pattern, p)


def test_production_matcher_agrees_exhaustively_on_a_small_universe():
    cases = [pat("M"), pat("M", n("a1", "b")), pat("M", n("a1", "b", role="context")), pat("M", n("a1", "b"), n("a2")),
             pat("M", n("a1", "e"), n("x1", "x", absent=True)), pat("M", n("a1", None, role="context"))]
    for m in cases:
        for p in SMALL:
            assert production_matches(m, p, H) == oracle(m, p, H), (m, p)


# --- A: unsatisfiable sources --------------------------------------------------------------------------------------


def test_unsatisfiable_source_is_vacuously_valid_without_a_counterexample():
    """b is present and everything at or below a is forbidden: no patient matches, whatever the target."""
    n_ = pat("N", n("p1", "b"), n("x1", "a", absent=True))
    for target in (pat("T", n("t1", "g")), pat("T", n("t1", "c"), n("w", "root", absent=True)), pat("T", n("t1", "x"))):
        v = check([n_], [target])
        assert (v.status, v.reason, v.evidence) == ("VALID", "sources_unsatisfiable", {"instances": 0})
        assert "counterexample" not in v.evidence


def test_observation_dates_that_disagree_make_the_source_unsatisfiable():
    obs = (Observation(value=iv(0, 5), dates={"seen": "2020-01-01"}, source_node="o"),)
    n_ = pat("N", n("p1", "b", dates={"seen": "2020-01-02"}, observations=obs))
    v = check([n_], [pat("T", n("t1", "x"))])
    assert (v.status, v.reason) == ("VALID", "sources_unsatisfiable")


def test_sources_contradicting_each_other_are_vacuous_together_only():
    s1, s2 = pat("S1", n("p1", "e")), pat("S2", n("x1", "b", absent=True))   # e lies below b
    t = pat("T", n("t1", "g"))
    assert check([s1, s2], [t]).reason == "sources_unsatisfiable"
    assert check([s1], [t]).status == "INVALID" and check([s2], [t]).status == "INVALID"


def test_satisfiable_source_against_unsatisfiable_target_is_invalid():
    t = pat("T", n("t1", "b"), n("x1", "a", absent=True))
    v = check([pat("N", n("p1", "e"))], [t])
    assert v.status == "INVALID"


def test_patient_only_motif():
    """A motif of ``P`` alone matches every patient (with a patient fact)."""
    empty, some = pat("E"), pat("N", n("p1", "b"))
    assert check([some], [empty]).reason == "contained"
    assert check([empty], [some]).status == "INVALID"
    assert check([empty], [empty]).ok


# --- B: overlapping present/absent hierarchies ---------------------------------------------------------------------

PRESENT = [None, "b", "c"]
ABSENT = [None, "x", "y"]


@pytest.mark.parametrize("src_present,src_absent,tgt_present,tgt_absent",
                         list(itertools.product(PRESENT, ABSENT, [None, "a", "b"], ABSENT)))
def test_present_and_absent_overlap(src_present, src_absent, tgt_present, tgt_absent):
    """y lies below both b (present branch) and x (absent branch); every combination is decided exactly."""
    def build(mid, present, absent):
        nodes = [n(f"{mid}p", present)] + ([n(f"{mid}x", absent, absent=True)] if absent else [])
        return pat(mid, *nodes)
    check([build("N", src_present, src_absent)], [build("B", tgt_present, tgt_absent)])


def test_covered_and_uncovered_target_absent_codes():
    n_ = pat("N", n("p1", "b"), n("x1", "x", absent=True))
    assert check([n_], [pat("T", n("t1", "b"), n("w", "y", absent=True))]).ok        # y at or below x: covered
    v = check([pat("N", n("p1", "b"), n("x1", "y", absent=True))], [pat("T", n("t1", "b"), n("w", "x", absent=True))])
    assert v.status == "INVALID"   # x is not covered by y: the counterexample adds a fact coded x
    assert "x" in {f["code"] for f in v.evidence["counterexample"]["nodes"]}


# --- multiple slots of the same type -------------------------------------------------------------------------------

POINTS = universe(codes=(None,), points=(None, *GRID), max_facts=2)


def test_same_type_slots_valid_with_no_single_map():
    """a:[0,10], b:[5,5] against g1:[0,5], g2:[5,10]: every patient is covered, by one map or the other."""
    n_ = pat("N", n("a1", value=iv(0, 10)), n("a2", value=iv(5, 5)))
    b_ = pat("B", n("g1", value=iv(0, 5)), n("g2", value=iv(5, 10)))
    assert check([n_], [b_], POINTS).reason == "contained"
    v = check([n_], [pat("B", n("g1", value=iv(0, 5)), n("g2", value=iv(6, 10)))], POINTS)
    assert v.status == "INVALID"
    points = [f["value"]["lo"] for f in v.evidence["counterexample"]["nodes"] if f["value"]]
    assert 5.0 in points and not any(6 <= x <= 10 for x in points)


def test_three_same_type_slots_need_injective_assignment():
    n_ = pat("N", n("a1", "e"), n("a2", "e"), n("a3", "b"))
    assert check([n_], [pat("B", n("g1", "b"), n("g2", "b"), n("g3", "b"))]).ok
    assert check([n_], [pat("B", n("g1", "e"), n("g2", "e"), n("g3", "e"))]).status == "INVALID"
    assert check([pat("N", n("a1", "e"), n("a2", "b"))], [pat("B", n("g1", "a"), n("g2", "a"), n("g3", "a"))]).status \
        == "INVALID"


# --- multiple maximal common descendants (facts shared between AND sources) ----------------------------------------


def test_merged_fact_has_one_code_per_minimal_profile():
    """b AND c may be one fact coded e, f or d. Two any-coded facts fail on that patient; e alone covers it only when
    the fact is e or d, so the counterexample uses f; adding f as an alternative covers every case."""
    s1, s2 = pat("S1", n("p1", "b")), pat("S2", n("p2", "c"))
    two, te, tf = pat("T2", n("t1"), n("t2")), pat("TE", n("t1", "e")), pat("TF", n("t1", "f"))
    v = check([s1, s2], [two, te])
    assert v.status == "INVALID"
    assert [f["code"] for f in v.evidence["counterexample"]["nodes"] if f["type"] == "T"] == ["f"]
    assert check([s1, s2], [two, te, tf]).reason == "contained"
    assert check([s1, s2], [two]).status == "INVALID"


# --- shared patient identity --------------------------------------------------------------------------------------


def two_patients() -> Motif:
    """A graph with a second Patient fact Q carrying the c fact: not a valid patient graph."""
    q = Node(id="Q", type="Patient", role="patient")
    facts = (Node(id="q0", type="T", role="x", code="b"), Node(id="q1", type="T", role="x", code="c"))
    return Motif(motif_id="U", anchor=PATIENT_ID, nodes=(P, q, *facts),
                 edges=(Edge(s=PATIENT_ID, t="q0", rel="r", prov="asserted"), Edge(s="Q", t="q1", rel="r", prov="asserted")))


def test_a_patient_graph_has_exactly_one_patient_fact():
    from tests.support.matcher import InvalidPatient, matches_bundle
    for bad in (two_patients(), patient().model_copy(update={"nodes": (n("q0", "b"),), "anchor": "q0", "edges": ()})):
        with pytest.raises(InvalidPatient):
            oracle(pat("S", n("p1", "b")), bad, H)
        with pytest.raises(ValueError):
            production_matches(pat("S", n("p1", "b")), bad, H)
    from semgen.bundle import MotifBundle, MotifPart
    b = MotifBundle(bundle_id="B", semantics="all", anchor_part="S1",
                    parts=tuple(MotifPart(part_id=m.motif_id, motif=m) for m in (pat("S1", n("p1", "b")),
                                                                                  pat("S2", n("p2", "c")))))
    with pytest.raises(InvalidPatient):
        matches_bundle(b, two_patients(), H)


def test_all_bundle_parts_are_matched_at_the_same_patient_fact():
    """S1 (P -> b) AND S2 (P -> c) is not satisfied by a b fact on P and a c fact on some other node: every part's
    P is the one Patient fact. So the conjunction implies a target joining both facts to P."""
    from semgen.bundle import MotifBundle, MotifPart
    s1, s2 = pat("S1", n("p1", "b")), pat("S2", n("p2", "c"))
    b = MotifBundle(bundle_id="B", semantics="all", anchor_part="S1",
                    parts=tuple(MotifPart(part_id=m.motif_id, motif=m) for m in (s1, s2)))
    elsewhere = patient(("T", "b", None)).model_copy(update={"nodes": patient(("T", "b", None)).nodes + (
        Node(id="o", type="Other", role="x"), Node(id="q9", type="T", role="x", code="c")), "edges": patient(
        ("T", "b", None)).edges + (Edge(s="o", t="q9", rel="r", prov="asserted"),)})
    from tests.support.matcher import matches_bundle
    assert oracle(s1, elsewhere, H) and not oracle(s2, elsewhere, H) and not matches_bundle(b, elsewhere, H)
    assert matches_bundle(b, patient(("T", "b", None), ("T", "c", None)), H)
    # One fact coded e (or f) satisfies both parts, so two facts are not implied when both parts have one type ...
    assert check([s1, s2], [pat("T", n("t1"), n("t2"))]).status == "INVALID"
    # ... but facts of different types cannot be one fact: both hang off the one Patient fact, which is implied.
    u1, u2 = pat("U1", n("p1", "b")), pat("U2", n("p2", "c", type="V"))
    both = pat("T", n("t1", "b"), n("t2", "c", type="V"))
    assert check([u1, u2], [both], universe(types=("T", "V"))).ok
    assert check([u1, u2], [pat("T", n("t1", "e"))]).status == "INVALID"


def test_single_motif_patient_node_maps_only_to_the_patient_fact():
    """A pattern's P maps to the Patient fact; no other pattern node maps to it, even an uncoded one."""
    p_coded = patient().model_copy(update={"nodes": (P.model_copy(update={"code": "b"}),)})
    for match in (oracle, production_matches):
        assert match(pat("S"), patient(), H)
        assert not match(pat("S", n("p1", type="Patient")), patient(), H)   # needs a second Patient fact
        assert not match(pat("S", n("p1", "b", type="Patient")), p_coded, H)
    v = check([pat("N", n("p1", type="Patient"))], [pat("T", n("t1", "x"))])
    assert v.reason == "sources_unsatisfiable"


def test_or_bundle_alternatives_share_the_patient_fact():
    """Under OR each alternative is matched at the one Patient fact; ``b`` OR ``c`` covers a node at or below a only
    together with the remaining case, and the Patient fact never stands in for a fact."""
    assert check([pat("N", n("p1", "e"))], [pat("T1", n("t1", "b")), pat("T2", n("t2", "c"))]).ok
    assert check([pat("N", n("p1", "a"))], [pat("T1", n("t1", "b")), pat("T2", n("t2", "c"))]).status == "INVALID"
    assert check([pat("N", n("p1", "a"))], [pat("T1", n("t1", "b")), pat("T2", n("t2", "a"))]).ok


def test_single_source_implication_decides_a_conjunction():
    v = decide([pat("S1", n("p1", "e")), pat("S2", n("p2", "c"))], [pat("T", n("t1", "b"))], H)
    assert v.ok and v.evidence["covered_by"] == "S1"


# --- coded and uncoded slots, context slots ------------------------------------------------------------------------


@pytest.mark.parametrize("s_role,s_code,t_role,t_code",
                         list(itertools.product(["x", "context"], [None, "b", "d"], ["x", "context"], [None, "b", "d"])))
def test_coded_uncoded_and_context_combinations(s_role, s_code, t_role, t_code):
    """d is a leaf: a non-context d slot admits only d, so a context d slot covers it; b has descendants. An uncoded
    non-context source slot against an uncoded context target slot is the one pairing left UNKNOWN."""
    v = check([pat("N", n("p1", s_code, role=s_role))], [pat("B", n("t1", t_code, role=t_role))])
    undecided = s_code is None and s_role != "context" and t_code is None and t_role == "context"
    assert (v.status == "UNKNOWN") == undecided, v
    if undecided:
        assert v.reason == "uncoded_context_target"
        assert brute([pat("N", n("p1", s_code, role=s_role))], [pat("B", n("t1", t_code, role=t_role))], SMALL)


def test_context_target_against_non_context_source():
    v = check([pat("N", n("p1", "b"))], [pat("B", n("t1", "b", role="context"))])
    assert v.status == "INVALID"
    (code,) = [f["code"] for f in v.evidence["counterexample"]["nodes"] if f["type"] == "T"]
    assert code in H.descendants("b")
    assert check([pat("N", n("p1", "d"))], [pat("B", n("t1", "d", role="context"))]).ok   # d has no descendant


# --- interval boundaries and representative points -----------------------------------------------------------------


def test_representatives_one_point_per_cell():
    cut = [0, 5, 10]
    assert representatives(iv(0, 10), cut) == [0, 2.5, 5, 7.5, 10]
    assert representatives(iv(0, 5, True, False), cut) == [0, 2.5]
    assert representatives(iv(0, 5, False, True), cut) == [2.5, 5]
    assert representatives(Interval(lo=None, hi=0, unit=U), cut) == [-1, 0]
    assert representatives(Interval(lo=10, hi=None, lo_closed=False, unit=U), cut) == [11]
    assert representatives(Interval(lo=None, hi=None, unit=U), []) == [0.0]
    assert representatives(iv(5, 5), cut) == [5]


def test_meet_respects_closedness_and_units():
    from semgen.containment import _EMPTY
    assert meet(iv(0, 5), iv(5, 10)) == iv(5, 5)
    assert meet(iv(0, 10, False, False), iv(0, 10)) == iv(0, 10, False, False)
    assert meet(iv(0, 5, True, False), iv(5, 10)) is _EMPTY
    assert meet(iv(0, 5), Interval.closed(0, 5, "v")) is _EMPTY
    assert meet(None, iv(1, 2)) == iv(1, 2)


INTERVALS = [iv(0, 5), iv(0, 5, True, False), iv(0, 5, False, True), iv(5, 10), iv(5, 10, False), iv(0, 10),
             Interval(lo=None, hi=5, unit=U), Interval(lo=5, hi=None, lo_closed=False, unit=U), iv(5, 5)]


@pytest.mark.parametrize("s_iv,t_iv", list(itertools.product(INTERVALS, INTERVALS)))
def test_interval_boundaries(s_iv, t_iv):
    v = check([pat("N", n("p1", value=s_iv))], [pat("B", n("t1", value=t_iv))], POINTS)
    assert v.ok == t_iv.contains(s_iv)


def test_units_must_agree():
    v = check([pat("N", n("p1", value=iv(0, 5)))], [pat("B", n("t1", value=Interval.closed(0, 5, "v")))])
    assert v.status == "INVALID"


def test_edge_dates_are_never_merged_into_one_edge():
    """Two source edges each with one date never have to share a patient edge that carries both."""
    two = (Edge(s=PATIENT_ID, t="p1", rel="r", prov="asserted", dates={"k1": "2020-01-01"}),
           Edge(s=PATIENT_ID, t="p1", rel="r", prov="asserted", dates={"k2": "2020-01-02"}))
    both = (Edge(s=PATIENT_ID, t="t1", rel="r", prov="asserted", dates={"k1": "2020-01-01", "k2": "2020-01-02"}),)
    split, joined = pat("N", n("p1", "b"), edges=two), pat("B", n("t1", "b"), edges=both)
    v = check([split], [joined])
    assert v.status == "INVALID"
    assert check([joined], [pat("B", n("t1", "b"), edges=tuple(e.model_copy(update={"t": "t1"}) for e in two))]).ok


# --- fresh counterexample types ------------------------------------------------------------------------------------


@given(st.lists(st.text(alphabet="_ab", min_size=1, max_size=6), min_size=1, max_size=5))
def test_fresh_type_never_collides(types):
    ms = [pat("M", *(n(f"n{i}", type=t) for i, t in enumerate(types)))]
    assert fresh_type(ms) not in {x.type for m in ms for x in m.nodes}


def test_counterexample_fact_type_is_unused_by_every_pattern():
    """The uncovered absent code is added with a type no pattern uses, so it cannot serve any present slot."""
    long_type = "_" * 7
    n_ = pat("N", n("p1", "b", type=long_type))
    t = pat("T", n("t1", "b", type=long_type), n("w", "c", absent=True))
    v = check([n_], [t], universe(types=(long_type,)))
    assert v.status == "INVALID"
    used = {x.type for m in (n_, t) for x in m.nodes}
    extra = [f for f in v.evidence["counterexample"]["nodes"] if f["type"] not in used]
    assert len(extra) == 1 and extra[0]["code"] == "c" and len(extra[0]["type"]) > len(long_type)


# --- UNKNOWN is never accepted -------------------------------------------------------------------------------------


def test_unknown_outcomes():
    assert decide([pat("N", n("p1", "z"))], [pat("B", n("t1", "a"))], H).reason == "snomed_mapping_missing"
    v = decide([pat("N", n("p1", "b"))], [pat("B", n("t1", "b"), n("w", None, absent=True))], H)
    assert (v.status, v.reason) == ("UNKNOWN", "absent_code_missing")
    v = decide([pat("N", n("a1", value=iv(0, 10)), n("a2", value=iv(5, 5)))],
               [pat("B", n("g1", value=iv(0, 5)), n("g2", value=iv(5, 10)))], H, limit=1)
    assert (v.status, v.reason, v.ok) == ("UNKNOWN", "search_incomplete", False)
    assert decide([pat("N", n("p1", "z", role="context"))], [pat("B", n("t1", "z", role="context"))], H).ok


# --- property: exactness on random cases ---------------------------------------------------------------------------


@st.composite
def coded(draw, mid: str) -> Motif:
    nodes = [n(f"{mid}{i}", draw(st.sampled_from([None, "a", "b", "c", "e", "f", "g", "y"])),
               role=draw(st.sampled_from(["x", "x", "context"]))) for i in range(draw(st.integers(0, 2)))]
    if draw(st.integers(0, 2)) == 0:
        nodes.append(n(f"{mid}w", draw(st.sampled_from(["b", "c", "e", "x", "y"])), absent=True))
    return pat(mid, *nodes)


@SETTINGS
@given(st.lists(coded("S"), min_size=1, max_size=2, unique_by=lambda m: len(m.nodes)),
       st.lists(coded("T"), min_size=1, max_size=2))
def test_decision_is_exact_on_random_cases(sources, targets):
    sources = [m.model_copy(update={"motif_id": f"S{i}"}) for i, m in enumerate(sources)]
    targets = [m.model_copy(update={"motif_id": f"T{i}"}) for i, m in enumerate(targets)]
    assert check(sources, targets).status in {"VALID", "INVALID"}
