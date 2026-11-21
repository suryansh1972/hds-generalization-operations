from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from semgen.model import Interval
from semgen.order import check_order
from tests.conftest import *


def test_identity_both_ways(ctx, fake_m1):
    assert check_order(fake_m1, fake_m1, ctx).ok
def bad(ctx, s, g, reason): r = check_order(s, g, ctx); assert not r.ok and r.reason == reason
def test_sibling_drug(ctx, fake_m1):
    bad(ctx, fake_m1, fake_m1.replace_node(fake_m1.node("n2").model_copy(update={"code": DAUNO})), "concept_not_broader")
def test_narrowed_or_moved_lvef(ctx, fake_m1):
    wide = fake_m1.replace_node(fake_m1.node("n3").model_copy(update={"value": Interval(lo=0, hi=40, hi_closed=False, unit="%")}))
    bad(ctx, wide, wide.replace_node(wide.node("n3").model_copy(update={"value": Interval(lo=38, hi=39, unit="%")})), "value_not_contained")
    bad(ctx, fake_m1, fake_m1.replace_node(fake_m1.node("n3").model_copy(update={"value": Interval(lo=40, hi=50, hi_closed=False, unit="%")})), "value_not_contained")
def test_reversed_edge(ctx, fake_m1):
    base = fake_m1.without(set(), {("n2", "n3")})
    flipped = fake_m1.edge("n2", "n3").model_copy(update={"s": "n3", "t": "n2"})
    bad(ctx, fake_m1, base.model_copy(update={"edges": base.edges + (flipped,)}), "extra_edge")
def test_context_promoted_to_asserted(ctx, fake_m1):
    bad(ctx, fake_m1, fake_m1.replace_edge(fake_m1.edge("n2", "n4").model_copy(update={"prov": "asserted"})), "provenance_changed")
def test_absent_lifted(ctx, fake_m2):
    bad(ctx, fake_m2, fake_m2.replace_node(fake_m2.node("n2").model_copy(update={"code": DM})), "absent_not_narrower")
def test_value_added_fails_and_removed_passes(ctx, fake_m1):
    no_val = fake_m1.replace_node(fake_m1.node("n3").model_copy(update={"value": None}))
    assert check_order(fake_m1, no_val, ctx).ok
    bad(ctx, no_val, fake_m1, "value_added")
def test_every_single_operator_move_verifies(ctx, fake_m1, fake_m2):
    from semgen.operators import ALL_OPERATORS
    for m in (fake_m1, fake_m2):
        for op in ALL_OPERATORS:
            for mv in op(m, ctx).moves:
                r = check_order(m, mv.child, ctx); assert r.ok, (mv.change, r)


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None, max_examples=100)
@given(st.lists(st.integers(min_value=0, max_value=10_000), max_size=5))
def test_random_chains_stay_ordered(ctx, fake_m1, picks):
    from semgen.operators import ALL_OPERATORS
    cur, chain = fake_m1, [fake_m1]
    for idx in picks:
        moves = [mv for op in ALL_OPERATORS for mv in op(cur, ctx).moves]
        if not moves:
            break
        cur = moves[idx % len(moves)].child
        chain.append(cur)
    assert check_order(fake_m1, cur, ctx).ok
    for prev, nxt in zip(chain, chain[1:]):
        assert check_order(prev, nxt, ctx).ok


# --- focused extras ------------------------------------------------------------
def _with_val(m, iv):
    return m.replace_node(m.node("n3").model_copy(update={"value": iv}))


def test_endpoint_inclusivity(ctx, fake_m1):
    closed = _with_val(fake_m1, Interval(lo=0, hi=40, unit="%"))
    opened = _with_val(fake_m1, Interval(lo=0, hi=40, hi_closed=False, unit="%"))
    assert check_order(opened, closed, ctx).ok
    bad(ctx, closed, opened, "value_not_contained")


def test_unit_mismatch(ctx, fake_m1):
    bad(ctx, fake_m1, _with_val(fake_m1, Interval(lo=0, hi=100, unit="mmHg")), "value_not_contained")


def _with_attr(m, iv):
    n = m.node("n1")
    attrs = dict(n.attrs)
    if iv is None:
        attrs.pop("age_at_dx")
    else:
        attrs["age_at_dx"] = iv
    return m.replace_node(n.model_copy(update={"attrs": attrs}))


def test_attrs(ctx, fake_m1):
    removed = _with_attr(fake_m1, None)
    assert check_order(fake_m1, removed, ctx).ok
    bad(ctx, removed, fake_m1, "attr_added")
    wide = _with_attr(fake_m1, Interval(lo=60, hi=70, unit="a"))
    assert check_order(fake_m1, wide, ctx).ok
    bad(ctx, wide, fake_m1, "attr_not_contained")


def test_window(ctx, fake_m1):
    e = fake_m1.edge("n2", "n3")
    wide = fake_m1.replace_edge(e.model_copy(update={"window": Interval(lo=0, hi=30, unit="d")}))
    none = fake_m1.replace_edge(e.model_copy(update={"window": None}))
    assert check_order(fake_m1, wide, ctx).ok and check_order(fake_m1, none, ctx).ok
    bad(ctx, none, fake_m1, "window_added")
    bad(ctx, wide, fake_m1, "window_not_contained")


def test_type_role_polarity(ctx, fake_m1, fake_m2):
    bad(ctx, fake_m1, fake_m1.replace_node(fake_m1.node("n2").model_copy(update={"type": "Disorder"})), "type_changed")
    bad(ctx, fake_m1, fake_m1.replace_node(fake_m1.node("n2").model_copy(update={"role": "modifier"})), "role_changed")
    bad(ctx, fake_m2, fake_m2.replace_node(fake_m2.node("n2").model_copy(update={"polarity": "present"})), "polarity_changed")


def test_context_code_changed(ctx, fake_m1):
    bad(ctx, fake_m1, fake_m1.replace_node(fake_m1.node("n4").model_copy(update={"code": "OTHER"})), "context_code_changed")


def test_extra_node(ctx, fake_m1):
    small = fake_m1.without({"n5"}, set())
    r = check_order(small, fake_m1, ctx)
    assert (r.ok, r.reason, r.where) == (False, "extra_node", "n5")


def test_removing_edge_or_node_ok(ctx, fake_m1):
    assert check_order(fake_m1, fake_m1.without(set(), {("n2", "n3")}), ctx).ok
    assert check_order(fake_m1, fake_m1.without({"n5"}, set()), ctx).ok


def test_reverse_direction_fails(ctx, fake_m1):
    """Rewritten (Task 2): was a range_coarsening value move reversed -> value_not_contained; range_coarsening is
    gone, so a widened (bucket-like) value reversed is used for that reason, and attribute_deletion's value
    deletion reversed -> value_added."""
    from semgen.operators.attribute_deletion import attribute_deletion
    from semgen.operators.concept_lift import concept_lift
    (lift, *_) = concept_lift(fake_m1, ctx).moves
    r = check_order(lift.child, fake_m1, ctx)
    assert not r.ok and r.reason == "concept_not_broader"
    wide = fake_m1.replace_node(fake_m1.node("n3").model_copy(update={"value": Interval(lo=None, hi=40, unit="%")}))
    assert check_order(fake_m1, wide, ctx).ok
    r = check_order(wide, fake_m1, ctx)
    assert not r.ok and r.reason == "value_not_contained"
    from tests.support.relevance import relaxed
    dele = next(mv for mv in attribute_deletion(fake_m1, relaxed(ctx)).moves if mv.change.field == "value")
    r = check_order(dele.child, fake_m1, ctx)
    assert not r.ok and r.reason == "value_added"


# --- fix round 1: pin the allowed side of each code direction -------------------
def _n2(m, code):
    return m.replace_node(m.node("n2").model_copy(update={"code": code}))


def test_absent_narrowing_allowed(ctx, fake_m2):
    assert check_order(_n2(fake_m2, DM), _n2(fake_m2, T2DM), ctx).ok


def test_absent_sibling_rejected(ctx, fake_m2):
    bad(ctx, _n2(fake_m2, T1DM), _n2(fake_m2, T2DM), "absent_not_narrower")


def test_absent_none_mismatch_rejected(ctx, fake_m2):
    bad(ctx, fake_m2, _n2(fake_m2, None), "absent_not_narrower")
    bad(ctx, _n2(fake_m2, None), fake_m2, "absent_not_narrower")


def test_present_none_handling(ctx, fake_m1):
    assert check_order(fake_m1, _n2(fake_m1, None), ctx).ok
    bad(ctx, _n2(fake_m1, None), fake_m1, "concept_not_broader")


def _n2v(m, value):
    return m.replace_node(m.node("n2").model_copy(update={"value": value}))


def test_absent_value_widened_rejected(ctx, fake_m2):
    narrow, wide = Interval(lo=1, hi=2, unit="%"), Interval(lo=0, hi=5, unit="%")
    bad(ctx, _n2v(fake_m2, narrow), _n2v(fake_m2, wide), "absent_constraint_changed")


def test_absent_value_removed_rejected(ctx, fake_m2):
    bad(ctx, _n2v(fake_m2, Interval(lo=1, hi=2, unit="%")), _n2v(fake_m2, None), "absent_constraint_changed")


def test_absent_equal_value_passes(ctx, fake_m2):
    v = Interval(lo=1, hi=2, unit="%")
    assert check_order(_n2v(fake_m2, v), _n2v(fake_m2, v), ctx).ok


# --- Task 1: relations by equality, dates, containment certificates, bundle order ---
from semgen.bundle import MotifBundle, MotifPart, Subject  # noqa: E402
from semgen.model import Edge  # noqa: E402
from semgen.order import check_bundle_order, verify_containment  # noqa: E402


def test_relation_change_rejected(ctx, fake_m1):
    other = fake_m1.replace_edge(fake_m1.edge("P", "n2").model_copy(update={"rel": "exposed_to_drug"}))
    bad(ctx, fake_m1, other, "relation_changed")
    bad(ctx, other, fake_m1, "relation_changed")


def _dated(m, node_dates=None, edge_dates=None):
    if node_dates is not None:
        m = m.replace_node(m.node("n1").model_copy(update={"dates": node_dates}))
    if edge_dates is not None:
        m = m.replace_edge(m.edge("P", "n1").model_copy(update={"dates": edge_dates}))
    return m


def test_date_removed_ok_date_changed_or_added_rejected(ctx, fake_m1):
    for kw in ("node_dates", "edge_dates"):
        dated = _dated(fake_m1, **{kw: {"onset": "2026-01-02"}})
        moved = _dated(fake_m1, **{kw: {"onset": "2026-01-03"}})
        assert check_order(dated, fake_m1, ctx).ok
        bad(ctx, dated, moved, "date_changed")
        bad(ctx, fake_m1, dated, "date_added")


ID1 = {"P": "P", "n1": "n1", "n2": "n2", "n3": "n3", "n4": "n4", "n5": "n5"}


def _vbad(ctx, narrow, broad, mapping, reason):
    r = verify_containment(narrow, broad, mapping, ctx)
    assert not r.ok and r.reason == reason, r


def _renamed(m, ren):
    """The same motif with node ids renamed by ``ren`` (a structurally identical copy)."""
    nodes = tuple(n.model_copy(update={"id": ren.get(n.id, n.id)}) for n in m.nodes)
    edges = tuple(e.model_copy(update={"s": ren.get(e.s, e.s), "t": ren.get(e.t, e.t)}) for e in m.edges)
    return m.model_copy(update={"nodes": nodes, "edges": edges, "anchor": ren.get(m.anchor, m.anchor)})


def test_verify_containment_accepts_valid_and_rejects_each_violation(ctx, fake_m1, fake_m2):
    assert verify_containment(fake_m1, fake_m1, ID1, ctx).ok
    # A renamed, generalized copy: lifted anchor, no value, no age, window widened, n5 dropped.
    ren = {"n1": "a", "n2": "b", "n3": "c", "n4": "d"}
    g = _renamed(fake_m1, ren).without({"n5"}, set())
    g = g.replace_node(g.node("a").model_copy(update={"code": MAL_THORAX, "attrs": {}}))
    g = g.replace_node(g.node("c").model_copy(update={"value": None}))
    g = g.replace_edge(g.edge("b", "c").model_copy(update={"window": Interval(lo=0, hi=30, unit="d")}))
    gmap = {"P": "P", "a": "n1", "b": "n2", "c": "n3", "d": "n4"}
    assert verify_containment(fake_m1, g, gmap, ctx).ok
    _vbad(ctx, fake_m1, g, {**gmap, "d": "n2"}, "mapping_not_injective")
    _vbad(ctx, fake_m1, g, {k: v for k, v in gmap.items() if k != "d"}, "mapping_incomplete")
    _vbad(ctx, fake_m1, g, {**gmap, "d": "zz"}, "mapping_invalid")
    _vbad(ctx, fake_m1, g, {**gmap, "P": "n4", "d": "P"}, "patient_not_fixed")
    _vbad(ctx, fake_m1, g.replace_node(g.node("b").model_copy(update={"type": "Disorder"})), gmap, "type_changed")
    # Role is not compared (the matcher reads it only for context slots): a non-context role change still verifies,
    # but a broad context node needs a narrow context node with the same code.
    assert verify_containment(fake_m1, g.replace_node(g.node("b").model_copy(update={"role": "modifier"})), gmap,
                              ctx).ok
    _vbad(ctx, fake_m1, g.replace_node(g.node("b").model_copy(update={"role": "context", "code": fake_m1.node("n2").code})),
          gmap, "context_code_changed")
    _vbad(ctx, fake_m1, g.replace_node(g.node("b").model_copy(update={"code": DAUNO})), gmap, "concept_not_broader")
    _vbad(ctx, fake_m1, g.replace_node(g.node("a").model_copy(update={"code": RA_OLD_PARENT})), gmap,
          "snomed_mapping_missing")
    _vbad(ctx, fake_m1, g.replace_node(g.node("c").model_copy(update={"value": Interval(lo=40, hi=50, unit="%")})),
          gmap, "value_not_contained")
    _vbad(ctx, fake_m1, g.replace_node(g.node("a").model_copy(update={"attrs": {"age_at_dx": Interval.point(70, "a")}})),
          gmap, "attr_not_contained")
    _vbad(ctx, fake_m1, g.replace_node(g.node("a").model_copy(update={"dates": {"onset": "2026-01-01"}})), gmap,
          "date_added")
    _vbad(ctx, fake_m1, g.model_copy(update={"edges": g.edges + (Edge(s="a", t="c", rel="r", prov="asserted"),)}),
          gmap, "missing_edge")
    _vbad(ctx, fake_m1, g.replace_edge(g.edge("P", "b").model_copy(update={"rel": "exposed_to_drug"})), gmap,
          "relation_changed")
    _vbad(ctx, fake_m1, g.replace_edge(g.edge("b", "d").model_copy(update={"prov": "asserted"})), gmap,
          "provenance_changed")
    _vbad(ctx, fake_m1, g.replace_edge(g.edge("b", "c").model_copy(update={"window": Interval(lo=30, hi=60, unit="d")})),
          gmap, "window_not_contained")
    _vbad(ctx, fake_m1, g.replace_node(g.node("d").model_copy(update={"code": "OTHER"})), gmap, "context_code_changed")
    # Absent nodes: polarity must agree, and G must forbid no more than S does.
    id2 = {"P": "P", "n1": "n1", "n2": "n2", "n3": "n3", "n4": "n4", "n5": "n5", "n6": "n6"}
    assert verify_containment(fake_m2, fake_m2, id2, ctx).ok
    weak = fake_m2.replace_node(fake_m2.node("n2").model_copy(update={"code": DM}))   # G forbids all DM: stronger
    _vbad(ctx, fake_m2, weak, id2, "absent_not_narrower")
    narrower_s = fake_m2.replace_node(fake_m2.node("n2").model_copy(update={"code": DM}))
    assert verify_containment(narrower_s, fake_m2, id2, ctx).ok                     # S forbids DM, G only T1DM
    flip = fake_m2.replace_node(fake_m2.node("n4").model_copy(update={"polarity": "absent"}))
    _vbad(ctx, fake_m2, flip, id2, "polarity_changed")
    _vbad(ctx, fake_m2, fake_m2.replace_node(fake_m2.node("n2").model_copy(update={"code": RA_OLD_PARENT})), id2,
          "snomed_mapping_missing")


def test_verify_containment_observations(ctx, fake_m1):
    """Rewritten (Task 2) for check_order only: was check_order accepting the crossed assignment (o0 <- 41,
    o1 <- 38) and rejecting as ``observations_not_contained``; check_order now maps observations by
    ``source_node`` (A1 rule, §7.3), so the crossed child is ``observation_not_contained``. verify_containment
    keeps the one-to-one containment rule of §6."""
    from semgen.model import Observation
    def obs(*vals):
        return tuple(Observation(value=Interval(lo=lo, hi=hi, unit="%"), source_node=f"o{i}")
                     for i, (lo, hi) in enumerate(vals))
    def with_obs(m, o):
        return m.replace_node(m.node("n3").model_copy(update={"value": None, "observations": o}))
    s = with_obs(fake_m1, obs((38, 38), (41, 41)))
    assert verify_containment(s, with_obs(fake_m1, obs((40, 45), (30, 39))), ID1, ctx).ok
    assert verify_containment(s, with_obs(fake_m1, obs((40, 45))), ID1, ctx).ok
    _vbad(ctx, s, with_obs(fake_m1, obs((30, 45), (30, 39), (0, 99))), ID1, "observations_not_contained")
    _vbad(ctx, s, with_obs(fake_m1, obs((30, 39), (30, 39))), ID1, "observations_not_contained")
    assert check_order(s, with_obs(fake_m1, obs((30, 39), (40, 45))), ctx).ok
    bad(ctx, s, with_obs(fake_m1, obs((40, 45), (30, 39))), "observation_not_contained")
    bad(ctx, s, with_obs(fake_m1, obs((30, 39), (30, 39))), "observation_not_contained")


def _bundle(m1, m2, **kw):
    m2 = m2.model_copy(update={"motif_id": "M2"})
    return MotifBundle(**({"bundle_id": "B", "semantics": "all", "anchor_part": "M1",
                           "parts": (MotifPart(part_id="M1", motif=m1), MotifPart(part_id="M2", motif=m2))} | kw))


def test_bundle_order_rejects_subject_or_semantics_change(ctx, fake_m1, fake_m2):
    b = _bundle(fake_m1, fake_m2)
    assert check_bundle_order(b, b, ctx).ok
    r = check_bundle_order(b, b.model_copy(update={"subject": Subject(sex="F")}), ctx)
    assert (r.ok, r.reason) == (False, "subject_changed")
    for sem in ("any", None):
        r = check_bundle_order(b, b.model_copy(update={"semantics": sem}), ctx)
        assert (r.ok, r.reason) == (False, "semantics_changed")


def test_bundle_order_single_part_change_delegates_to_check_order(ctx, fake_m1, fake_m2):
    from semgen.operators.concept_lift import concept_lift
    lift = next(mv.child for mv in concept_lift(fake_m1, ctx).moves if mv.change.target == "n1")
    b = _bundle(fake_m1, fake_m2)
    up = b.model_copy(update={"parts": (MotifPart(part_id="M1", motif=lift), b.parts[1])})
    assert check_bundle_order(b, up, ctx).ok
    r = check_bundle_order(up, b, ctx)
    assert (r.ok, r.reason, r.where) == (False, "concept_not_broader", "M1:n1")
    single = MotifBundle.of(fake_m1)
    assert check_bundle_order(single, MotifBundle.of(lift), ctx).ok
    rel = fake_m1.replace_edge(fake_m1.edge("P", "n2").model_copy(update={"rel": "exposed_to_drug"}))
    r = check_bundle_order(single, MotifBundle.of(rel), ctx)
    assert (r.ok, r.reason) == (False, "relation_changed")


def test_bundle_order_part_change_delegates_to_check_order(ctx, fake_m1):
    from semgen.operators.concept_lift import concept_lift
    m2 = fake_m1.model_copy(update={"motif_id": "M2"})
    lift = next(mv.child for mv in concept_lift(m2, ctx).moves if mv.change.target == "n1")
    m0 = fake_m1.model_copy(update={"motif_id": "M0"})

    def bundle(x):
        return MotifBundle(bundle_id="B", semantics="all", anchor_part="M0",
                           parts=(MotifPart(part_id="M0", motif=m0), MotifPart(part_id="M2", motif=x)))
    old, new = bundle(m2), bundle(lift)
    assert check_bundle_order(old, new, ctx).ok
    r = check_bundle_order(new, old, ctx)
    assert (r.ok, r.reason, r.where) == (False, "concept_not_broader", "M2:n1")


def test_bundle_order_checks_merging_parts_as_an_aggregation(ctx, fake_m1):
    """Two parts replaced by one new part is the motif aggregation transition: it must carry the aggregate id derived
    from the consumed parts (and then pass the aggregation proof, see test_op_motif_aggregation)."""
    m0, m2 = (fake_m1.model_copy(update={"motif_id": i}) for i in ("M0", "M2"))
    m3 = fake_m1.model_copy(update={"motif_id": "M3"})
    b = MotifBundle(bundle_id="B", semantics="all", anchor_part="M0",
                    parts=tuple(MotifPart(part_id=m.motif_id, motif=m) for m in (m0, m2, m3)))
    merged = b.model_copy(update={"parts": (b.parts[0], MotifPart(part_id="M9", motif=fake_m1.model_copy(
        update={"motif_id": "M9"})))})
    r = check_bundle_order(b, merged, ctx, {"P": "P"})
    assert (r.ok, r.reason, r.where) == (False, "aggregate_id_mismatch", "M9")


def test_bundle_order_unsupported_shape(ctx, fake_m1, fake_m2):
    """Removing part M2 is the deletion shape (§8): it is decided exactly (M2 has an absent node; M1 does not imply
    it, so ``not_contained``); a part both added and changed, or an anchor change, is ``unsupported_transition``."""
    from semgen.operators.concept_lift import concept_lift
    b = _bundle(fake_m1, fake_m2)
    lift1 = next(mv.child for mv in concept_lift(fake_m1, ctx).moves if mv.change.target == "n1")
    lift2 = next(mv.child for mv in concept_lift(b.parts[1].motif, ctx).moves if mv.change.target == "n1")
    two = b.model_copy(update={"parts": (MotifPart(part_id="M1", motif=lift1), MotifPart(part_id="M2", motif=lift2))})
    removed = b.model_copy(update={"parts": b.parts[:1]})
    anchor = b.model_copy(update={"anchor_part": "M2"})
    for child in (two, anchor):
        r = check_bundle_order(b, child, ctx)
        assert (r.ok, r.reason) == (False, "unsupported_transition"), child
    r = check_bundle_order(b, removed, ctx)
    assert (r.ok, r.reason, r.where) == (False, "not_contained", "M2")
