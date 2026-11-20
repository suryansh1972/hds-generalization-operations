import importlib
from collections import Counter
from pathlib import Path

import pytest

import semgen.lattice as L
from semgen.config import load_config
from semgen.lattice import Budget, GeneralizationOrderError, enumerate_lattice
from semgen.lift import FloorDecision
from semgen.motif_io import parse_motif
from semgen.operators.base import GenContext
from semgen.operators.concept_lift import concept_lift, is_liftable
from semgen.order import check_order
from semgen.settings import default_config_path  # noqa: E402
from semgen.snomed import ROOT_ID, Hierarchy
from tests.support.hierarchy_graph import _ISA, AllowExcept, graph_hierarchy, one_disorder_motif
from tests.support.relevance import relaxed

CFG = default_config_path()


# Rev 4: deletion moves need a relaxable relevance decision; these tests are about what deletions do, so they
# run with every candidate relaxable (tests/support/relevance.py). The gate itself: tests/test_relevance.py.
def _ctx(blocked=()):
    return relaxed(GenContext(graph_hierarchy(), load_config(CFG), AllowExcept(set(blocked))))


def _lat(depth, blocked=()):
    return enumerate_lattice(one_disorder_motif("SPEC"), _ctx(blocked), Budget(max_depth=depth), climb=False)


def _codes(lat, depth=None):
    return {c.motif.node("n1").code for c in lat.candidates.values() if depth is None or c.depth == depth}


def _lifts(lat):
    return [(e, ch) for e in lat.edges for ch in e.changes if ch.op == "concept_lift"]


def test_first_step_is_direct_parents_never_children():
    assert _codes(_lat(1), 1) == {"P1", "P2"}


def test_each_transition_is_one_direct_parent_step():
    h = graph_hierarchy()
    lifts = _lifts(_lat(4))
    assert lifts
    assert all(ch.after in h.parents(ch.before) for _, ch in lifts)


def test_bfs_lifts_parents_of_generalized_concepts():
    assert {"G", "C1"} <= _codes(_lat(3))


def test_all_branches_explored():
    pairs = {(ch.before, ch.after) for _, ch in _lifts(_lat(2))}
    assert {("P1", "G"), ("P2", "G")} <= pairs


def test_converging_paths_dedupe_and_keep_histories():
    lat = _lat(2)
    g = [h for h, c in lat.candidates.items() if c.motif.node("n1").code == "G"]
    assert len(g) == 1
    inc = [e for e in lat.edges if e.child == g[0]]
    assert len(inc) >= 2
    befores = {ch.before for e in inc for ch in e.changes}
    assert {"P1", "P2"} <= befores
    assert all(len(e.changes) == 1 for e in inc)


def test_blocked_parent_not_bypassed():
    lat = _lat(6, {"BLOCKED"})
    assert "ABOVE_BLOCKED" not in _codes(lat)
    assert "BLOCKED" not in _codes(lat)
    assert any(b.reason == "defining_attribute_dropped" for _, b in lat.blocked)


def test_inactive_parent_blocked_not_lifted():
    lat = _lat(3)
    assert any(b.reason == "inactive_parent" and b.detail["parent"] == "INACTIVE" for _, b in lat.blocked)
    assert "INACTIVE" not in _codes(lat)


def test_lift_module_has_no_descendant_reads():
    for name in ("semgen.operators.concept_lift", "semgen.lattice"):
        mod = importlib.import_module(name)  # the package re-exports the function under the module's name
        assert "descendant" not in Path(mod.__file__).read_text()


def test_order_checker_rejects_child_direction():
    r = check_order(one_disorder_motif("SPEC"), one_disorder_motif("KID"), _ctx())
    assert not r.ok and r.reason == "concept_not_broader"


def _dep_hierarchy():
    isa = {**_ISA, "SUB": {"P1"}, "OBS": {"P1"}}
    ids = set(isa) | {p for ps in isa.values() for p in ps}
    return Hierarchy.from_maps(isa, {c: f"{c} (x)" for c in ids - {"INACTIVE"}}, ids - {"INACTIVE"})


def _dep_motif():
    return parse_motif({
        "motif_id": "DEP", "anchor": "n1",
        "nodes": [{"id": "P", "type": "Patient", "role": "patient"},
                  {"id": "n1", "type": "Disorder", "code": "SPEC", "polarity": "present", "role": "anchor"},
                  {"id": "n2", "type": "Substance", "code": "SUB", "polarity": "present", "role": "exposure",
                   "attrs": {"cumulative_dose": {"interval": [360, 360], "unit": "mg/m2"}}},
                  {"id": "n3", "type": "Observable", "code": "OBS", "polarity": "present", "role": "outcome",
                   "value": {"interval": [38, 38], "unit": "%"}}],
        "edges": [{"s": "P", "t": "n1", "rel": "has_condition", "prov": "asserted"},
                  {"s": "P", "t": "n2", "rel": "administered_drug", "prov": "asserted"},
                  {"s": "P", "t": "n3", "rel": "has_measurement", "prov": "asserted"}]}, None)


def _dctx():
    h = _dep_hierarchy()
    return relaxed(GenContext(h, load_config(CFG), AllowExcept(set(), h)))


def _dlat(depth):
    return enumerate_lattice(_dep_motif(), _dctx(), Budget(max_depth=depth))


def test_value_bearing_observable_not_lifted():
    res = concept_lift(_dep_motif(), _dctx())
    assert any(b.target == "n3" and b.reason == "carries_value" for b in res.blocked)
    assert all(m.change.target != "n3" for m in res.moves)


def test_dependent_attr_substance_not_lifted():
    res = concept_lift(_dep_motif(), _dctx())
    assert any(b.target == "n2" and b.reason == "concept_dependent_attr" for b in res.blocked)
    assert all(m.change.target != "n2" for m in res.moves)


def test_prohibited_removal_never_enables_lift():
    lat = _dlat(4)
    assert all(ch.target != "n2" for _, ch in _lifts(lat))
    kept = [c.motif.node("n2") for c in lat.candidates.values() if "n2" in c.motif.node_ids]
    assert kept and all(n.code == "SUB" and "cumulative_dose" in n.attrs for n in kept)


def _value_removal_then_lift(lat):
    # Task 2: the value is removed by attribute_deletion (was attribute_removal, which it replaces).
    for e1 in lat.edges:
        if any(c.op == "attribute_deletion" and c.target == "n3" and c.field == "value" for c in e1.changes):
            for e2 in lat.edges:
                if e2.parent == e1.child and any(c.op == "concept_lift" and c.target == "n3" for c in e2.changes):
                    return e1, e2
    return None


def test_lift_after_permitted_value_removal():
    lat = _dlat(2)
    path = _value_removal_then_lift(lat)
    assert path is not None
    assert lat.candidates[path[1].child].motif.node("n3").value is None


def test_post_removal_transitions_are_recorded_and_proven():
    lat = _dlat(2)
    for e in _value_removal_then_lift(lat):
        assert e.changes
        assert check_order(lat.candidates[e.parent].motif, lat.candidates[e.child].motif, _dctx()).ok


# ---- per-node climb ----

def _clat(depth, code="SPEC", blocked=(), max_states=None, **kw):
    return enumerate_lattice(one_disorder_motif(code), _ctx(blocked), Budget(max_depth=depth, max_states=max_states), **kw)


def _cand(lat, code):
    return next(c for c in lat.candidates.values() if c.motif.node("n1").code == code)


def _fail_on(monkeypatch, name, code, when):
    """Patch <name> where the lattice resolves it (neighbors module; also the search module for the root proof) to
    fail on a child coded ``code`` when ``when(parent)`` holds; otherwise delegate."""
    import semgen.lattice.moves as N
    import semgen.lattice.search as S
    real = getattr(N, name)

    def patched(parent, child, *rest):
        if "n1" in child.node_ids and child.node("n1").code == code and when(parent):
            if name == "guard":
                raise L.PolicyViolation("forced")
            return L.OrderResult(False, "forced", "n1")
        return real(parent, child, *rest)
    monkeypatch.setattr(N, name, patched)
    if hasattr(S, name):
        monkeypatch.setattr(S, name, patched)


def test_climb_reaches_past_max_depth():
    """Rewritten (Task 1): was lat.status == "depth_limited"; now budget_limited by max_depth, same budget value."""
    lat = _clat(2)
    c5 = _cand(lat, "C5")
    assert c5.origin == "axis" and c5.depth == 7 and lat.status == "budget_limited" and lat.budget_hit == ("max_depth",)


def test_climb_is_one_step_edges():
    h, lat = graph_hierarchy(), _clat(2)
    pairs = []
    for e in lat.edges:
        p, c = lat.candidates[e.parent].motif.node("n1").code, lat.candidates[e.child].motif.node("n1").code
        assert [(ch.op, ch.target, ch.before, ch.after) for ch in e.changes] == [("concept_lift", "n1", p, c)]
        assert c in h.parents(p)
        pairs.append((p, c))
    chain = ["G", "C1", "C2", "C3", "C4", "C5"]
    assert all(pairs.count(step) == 1 for step in zip(chain, chain[1:]))


def test_climb_explores_all_branches():
    lat = _clat(1)
    assert {"P1", "P2", "G"} <= set(lat.axes["n1"].reached)
    gh = _cand(lat, "G").hash
    assert {lat.candidates[e.parent].motif.node("n1").code for e in lat.edges if e.child == gh} == {"P1", "P2"}


def test_climb_does_not_bypass_blocked():
    lat = _clat(1, blocked={"BLOCKED"})
    ax = lat.axes["n1"]
    assert "ABOVE_BLOCKED" not in ax.reached and "BLOCKED" not in ax.reached
    assert "ABOVE_BLOCKED" not in _codes(lat) and "defining_attribute_dropped" in ax.stopped_by


def test_climb_stops_at_floor_status():
    ax = _clat(1, code="G", blocked={"C3"}).axes["n1"]  # G has one route up; from SPEC, BLOCKED reaches the root
    assert ax.status == "reached_floor" and "C4" not in ax.reached
    assert ax.reached == ("C1", "C2") and ax.stopped_by == ("defining_attribute_dropped",)


def test_climb_stops_below_top_level_not_at_root():
    """Rewritten (SNOMED-only lift): the climb used to reach ROOT; now it stops at C5, because its parent TOP is a
    top-level concept that names the MRCM domain (derived from the graph, not supplied)."""
    ax = _clat(1).axes["n1"]
    assert ax.status == "reached_floor" and "C5" in ax.reached
    assert ROOT_ID not in ax.reached and "TOP" not in ax.reached
    assert ax.stopped_by == ("inactive_parent", "top_level_concept")


def test_value_node_is_policy_restricted():
    lat = _dlat(2)
    assert _value_removal_then_lift(lat) is not None  # the lattice still lifts n3 after removal; the climb must not
    ax = lat.axes["n3"]
    assert ax.status == "policy_restricted" and ax.reached == () and ax.stopped_by == ("carries_value",)


def test_dependent_attr_node_is_policy_restricted():
    ax = _dlat(1).axes["n2"]
    assert ax.status == "policy_restricted" and ax.reached == () and ax.stopped_by == ("concept_dependent_attr",)


def test_restriction_outranks_top_and_boundary():
    class Unmapped(AllowExcept):
        def check_lift(self, child, parent, **_context):
            return FloorDecision(False, "unmapped", {}) if child == "G" else super().check_lift(child, parent)
    ctx = relaxed(GenContext(graph_hierarchy(), load_config(CFG), Unmapped({"C1"})))
    ax = enumerate_lattice(one_disorder_motif("SPEC"), ctx, Budget(max_depth=1)).axes["n1"]
    assert {"unmapped", "inactive_parent"} <= set(ax.stopped_by)
    assert ax.status == "policy_restricted"


def test_unknown_concept_is_policy_restricted():
    ax = _clat(1, code="NOT_IN_GRAPH").axes["n1"]
    assert ax.status == "policy_restricted" and ax.reached == () and ax.stopped_by == ("unknown_concept",)


def test_climb_skips_absent_and_context_nodes(ctx, fake_m2):
    lat = enumerate_lattice(fake_m2, ctx, Budget(max_depth=0))
    assert fake_m2.node("n2").polarity == "absent" and fake_m2.node("n6").role == "context"
    assert list(lat.axes) == ["n1", "n3", "n4", "n5"]


def test_climb_moves_only_its_own_node():
    lat = _dlat(0)
    root = _dep_motif()
    for c in lat.candidates.values():
        if c.origin == "axis":
            assert [n for n in root.node_ids if c.motif.node(n) != root.node(n)] == ["n1"]
    assert all(c in graph_hierarchy().ancestors("SPEC") for c in lat.axes["n1"].reached)
    assert lat.axes["n2"].reached == () and "SPEC" not in lat.axes["n1"].reached


def test_axis_candidates_pass_root_proof(monkeypatch):
    root = one_disorder_motif("SPEC")
    _fail_on(monkeypatch, "check_order", "C5", lambda parent: parent == root)
    with pytest.raises(GeneralizationOrderError, match="root proof failed: forced at n1"):
        enumerate_lattice(root, _ctx(), Budget(max_depth=2))


def test_climb_step_order_failure_raises(monkeypatch):
    _fail_on(monkeypatch, "check_order", "C5", lambda parent: parent.node("n1").code == "C4")
    with pytest.raises(GeneralizationOrderError, match="forced at n1"):
        _clat(2)


def test_climb_guard_failure_raises(monkeypatch):
    _fail_on(monkeypatch, "guard", "C5", lambda parent: True)
    with pytest.raises(L.PolicyViolation, match="forced"):
        _clat(2)


def test_climb_deterministic():
    a, b = _clat(2), _clat(2)
    assert list(a.candidates) == list(b.candidates) and a.candidates == b.candidates
    assert a.edges == b.edges and a.blocked == b.blocked and a.axes == b.axes


def test_climb_records_blocks_on_climbed_motifs():
    lat = _clat(1, blocked={"C3"})
    c2 = _cand(lat, "C2")
    assert c2.origin == "axis"
    assert [b.reason for h, b in lat.blocked if h == c2.hash] == ["defining_attribute_dropped"]
    assert [b.reason for h, b in _clat(1, blocked={"C3"}, climb=False).blocked if h == c2.hash] == []


def test_climb_blocks_not_duplicated_for_bfs_expanded_motifs():
    for depth in (0, 1, 2, 30):
        lat = _clat(depth, blocked={"C3"})
        keys = Counter((h, b.op, b.target, b.reason, repr(b.detail)) for h, b in lat.blocked)
        assert max(keys.values()) == 1
        assert sum(b.reason == "inactive_parent" for _, b in lat.blocked) == 1


def test_climb_blocks_filtered_to_each_nodes_target():
    lat = _dlat(0)  # depth 0: only the climb expands the root, once per node
    assert {(b.target, b.reason) for h, b in lat.blocked if h == lat.root} == {
        ("n1", "inactive_parent"), ("n2", "concept_dependent_attr"), ("n3", "carries_value")}


@pytest.mark.parametrize("depth,budget", [(0, 2000), (2, 2000), (30, 2000), (30, 3), (30, 1)])
def test_climb_keeps_status_and_lattice_candidates(depth, budget):
    on = _clat(depth, max_states=budget)
    off = _clat(depth, max_states=budget, climb=False)
    assert (on.status, on.unexpanded) == (off.status, off.unexpanded) and on.root == off.root
    assert off.axes == {} and all(c.origin == "lattice" for c in off.candidates.values())
    assert all(on.candidates[h] == c for h, c in off.candidates.items())  # depth and origin are kept
    assert {e.parent + e.child for e in off.edges} <= {e.parent + e.child for e in on.edges}
    assert "C5" in on.axes["n1"].reached


def test_climb_ignores_candidate_budget():
    """Rewritten (Task 1): was lat.status == "candidate_limited"; now budget_limited by max_states, same budget."""
    lat = _clat(30, max_states=1)
    assert lat.status == "budget_limited" and lat.budget_hit == ("max_states",)
    assert "C5" in _codes(lat) and len(lat.candidates) > 1


def test_climb_edges_unique_and_depths_minimal():
    for depth in (0, 2, 4):
        lat = _clat(depth)
        d = {h: c.depth for h, c in lat.candidates.items()}
        assert len({(e.parent, e.child) for e in lat.edges}) == len(lat.edges)
        assert all(d[e.child] <= d[e.parent] + 1 for e in lat.edges)


def test_is_liftable_matches_operator_skip():
    m = _dep_motif()
    assert [n.id for n in m.nodes if is_liftable(n)] == ["n1", "n2", "n3"]
    assert {b.target for b in concept_lift(m, _dctx()).blocked} <= {n.id for n in m.nodes if is_liftable(n)}
    n = m.node("n1")
    assert not is_liftable(n.model_copy(update={"polarity": "absent"}))
    assert not is_liftable(n.model_copy(update={"role": "context"}))
    assert not is_liftable(n.model_copy(update={"code": None}))
    assert is_liftable(n.model_copy(update={"type": "Gene"}))   # the motif type is not ontology evidence


def _top_motif(kind):
    node = {"id": "n1", "type": "Disorder", "code": "SPEC", "polarity": "present", "role": "anchor"}
    top = {"value": {"interval": [38, 38], "unit": "%"}, "type": "Observable"} if kind == "value" else \
          {"attrs": {"cumulative_dose": {"interval": [360, 360], "unit": "mg/m2"}}, "type": "Substance"}
    return parse_motif({
        "motif_id": "TOP", "anchor": "n1",
        "nodes": [{"id": "P", "type": "Patient", "role": "patient"}, node,
                  {"id": "n2", "code": ROOT_ID, "polarity": "present", "role": "outcome", **top}],
        "edges": [{"s": "P", "t": "n1", "rel": "has_condition", "prov": "asserted"},
                  {"s": "P", "t": "n2", "rel": "has_measurement" if kind == "value" else "administered_drug",
                   "prov": "asserted"}]}, None)


@pytest.mark.parametrize("kind,reason", [("value", "carries_value"), ("attr", "concept_dependent_attr")])
def test_parentless_restricted_node_is_policy_restricted(kind, reason):
    ax = enumerate_lattice(_top_motif(kind), _ctx(), Budget(max_depth=0)).axes["n2"]
    assert ax.status == "policy_restricted" and ax.reached == () and reason in ax.stopped_by


def test_parentless_plain_node_reaches_hierarchy_top():
    ax = _clat(0, code=ROOT_ID).axes["n1"]
    assert ax.status == "reached_hierarchy_top" and ax.stopped_by == ("no_parent",)


def test_climb_hash_collision_detected(monkeypatch):
    root = one_disorder_motif("SPEC")
    import semgen.lattice.moves as N
    real = N.motif_hash
    monkeypatch.setattr(N, "motif_hash", lambda m: real(m) if m is root or m.node("n1").code in {"SPEC", "P1", "P2"} else "c" * 16)
    with pytest.raises(GeneralizationOrderError, match="hash collision"):
        enumerate_lattice(root, _ctx(), Budget(max_depth=0))


def test_stage4_graph_through_rf2(tmp_path):
    """Rewritten (Task 1): was lat.status == "depth_limited"; now budget_limited by max_depth, same budget value."""
    from semgen.snomed import FSN_TYPE, INFERRED, IS_A, load_rf2
    stated, other = "900000000000010007", "363698007"
    chain = ["G", "C1", "C2", "C3", "C4"]
    ids = ["SPEC", "P1", "P2", "BLK", "ABOVE_BLK", "KID", "X_INACT", "X_NONISA", "X_STATED", *chain, "TOP", ROOT_ID]
    rows = [("SPEC", "P1", IS_A, INFERRED, 1), ("SPEC", "P2", IS_A, INFERRED, 1), ("P1", "G", IS_A, INFERRED, 1),
            ("P2", "G", IS_A, INFERRED, 1), ("P2", "BLK", IS_A, INFERRED, 1), ("BLK", "ABOVE_BLK", IS_A, INFERRED, 1),
            ("ABOVE_BLK", "TOP", IS_A, INFERRED, 1), ("TOP", ROOT_ID, IS_A, INFERRED, 1), ("KID", "SPEC", IS_A, INFERRED, 1),
            ("SPEC", "X_INACT", IS_A, INFERRED, 0), ("SPEC", "X_NONISA", other, INFERRED, 1),
            ("SPEC", "X_STATED", IS_A, stated, 1), ("C4", "TOP", IS_A, INFERRED, 1),
            *[(a, b, IS_A, INFERRED, 1) for a, b in zip(chain, chain[1:])]]
    t = "\t".join
    (tmp_path / "sct2_Concept_Snapshot_INT_20990101.txt").write_text("\n".join(
        [t(["id", "effectiveTime", "active", "moduleId", "definitionStatusId"])]
        + [t([c, "20990101", "1", "900000000000207008", "900000000000074008"]) for c in ids]) + "\n")
    (tmp_path / "sct2_Description_Snapshot-en_INT_20990101.txt").write_text("\n".join(
        [t(["id", "effectiveTime", "active", "moduleId", "conceptId", "languageCode", "typeId", "term", "caseSignificanceId"])]
        + [t([str(i), "20990101", "1", "900000000000207008", c, "en", FSN_TYPE, f"{c} (disorder)", "900000000000448009"])
           for i, c in enumerate(ids, 1)]) + "\n")
    (tmp_path / "sct2_Relationship_Snapshot_INT_20990101.txt").write_text("\n".join(
        [t(["id", "effectiveTime", "active", "moduleId", "sourceId", "destinationId", "relationshipGroup", "typeId",
            "characteristicTypeId", "modifierId"])]
        + [t([str(i), "20990101", str(a), "900000000000207008", s, d, "0", ty, ch, "900000000000451002"])
           for i, (s, d, ty, ch, a) in enumerate(rows, 1)]) + "\n")
    h = load_rf2(tmp_path, cache_dir=tmp_path / "cache")
    ctx = GenContext(h, load_config(CFG), AllowExcept({"BLK"}, h))
    lat = enumerate_lattice(one_disorder_motif("SPEC"), ctx, Budget(max_depth=2))
    lifts = _lifts(lat)
    assert lifts and all(ch.after in h.parents(ch.before) for _, ch in lifts)  # parents only, one step each
    codes = _codes(lat)
    assert codes.isdisjoint({"KID", "X_INACT", "X_NONISA", "X_STATED", "BLK", "ABOVE_BLK"})
    assert {"P1", "P2", "G"} <= codes
    g = next(hh for hh, c in lat.candidates.items() if c.motif.node("n1").code == "G")
    inc = [e for e in lat.edges if e.child == g]
    assert {ch.before for e in inc for ch in e.changes} == {"P1", "P2"} and all(len(e.changes) == 1 for e in inc)
    assert any(b.reason == "defining_attribute_dropped" and b.detail["parent"] == "BLK" for _, b in lat.blocked)
    assert lat.status == "budget_limited" and lat.budget_hit == ("max_depth",)
    ax = lat.axes["n1"]
    assert ROOT_ID not in ax.reached and set(chain) <= set(ax.reached) and "ABOVE_BLK" not in ax.reached
    assert ax.status == "reached_floor" and "top_level_concept" in ax.stopped_by
    assert max(c.depth for c in lat.candidates.values()) > 2
