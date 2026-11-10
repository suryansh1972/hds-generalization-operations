import time
from collections import Counter

import pytest

import semgen.lattice as L
from semgen.canonical import motif_hash
from semgen.lattice import GeneralizationOrderError, enumerate_lattice
from semgen.order import check_order


def test_depth_zero_is_root_only(ctx, fake_m1):
    lat = enumerate_lattice(fake_m1, ctx, 0, climb=False); assert list(lat.candidates) == [lat.root] and lat.edges == []


def test_depth1_matches_neighbors(ctx, fake_m1):
    from semgen.lattice import neighbors
    lat = enumerate_lattice(fake_m1, ctx, 1, climb=False); assert len(lat.candidates) == 1 + len(neighbors(fake_m1, ctx)[0])


def test_no_duplicates_and_min_depth(ctx, fake_m1):
    lat = enumerate_lattice(fake_m1, ctx, 3)
    for e in lat.edges: assert lat.candidates[e.child].depth <= lat.candidates[e.parent].depth + 1
    assert len({(e.parent, e.child) for e in lat.edges}) == len(lat.edges)


def test_root_to_every_candidate_is_ordered(ctx, fake_m1, fake_m2):
    for m in (fake_m1, fake_m2):
        lat = enumerate_lattice(m, ctx, 3)
        for c in lat.candidates.values(): assert check_order(m, c.motif, ctx).ok


def test_m2_absent_constraint_never_changes(ctx, fake_m2):
    lat = enumerate_lattice(fake_m2, ctx, 4)
    for c in lat.candidates.values(): assert c.motif.node("n2") == fake_m2.node("n2") and c.motif.edge("P", "n2") == fake_m2.edge("P", "n2")
    assert not any(ch.target in ("n2", "P->n2") for e in lat.edges for ch in e.changes)


def test_deterministic(ctx, fake_m1):
    a, b = enumerate_lattice(fake_m1, ctx, 3), enumerate_lattice(fake_m1, ctx, 3)
    assert list(a.candidates) == list(b.candidates) and a.edges == b.edges


# ---- extras ----

def test_edge_depths_are_minimal(ctx, fake_m1):
    lat = enumerate_lattice(fake_m1, ctx, 3)
    d = {h: c.depth for h, c in lat.candidates.items()}
    for e in lat.edges:
        assert d[e.child] <= d[e.parent] + 1 and d[e.child] >= 1
    for h, c in lat.candidates.items():
        if h != lat.root:
            assert any(e.child == h and d[e.parent] == c.depth - 1 for e in lat.edges)


def test_blocked_only_from_expanded(ctx, fake_m1, fake_m2):
    for m in (fake_m1, fake_m2):
        lat = enumerate_lattice(m, ctx, 2, climb=False)
        for h, _ in lat.blocked:
            assert h in lat.candidates and lat.candidates[h].depth < 2


@pytest.mark.parametrize("bad", [-1, "3", 1.5, True])
def test_bad_max_depth(ctx, fake_m1, bad):
    with pytest.raises(ValueError): enumerate_lattice(fake_m1, ctx, bad)


def test_root_proof_failure(ctx, fake_m1, monkeypatch):
    real, orig_neighbors, state = L.check_order, L.neighbors, {"bfs_done": False}
    def neighbors_then_flag(m, c):
        r = orig_neighbors(m, c); state["bfs_done"] = True; return r  # depth 1 expands only the root
    def late(s, g, c):  # delegates to the real check unless this is the post-BFS root proof
        if state["bfs_done"] and s == fake_m1 and g != fake_m1: return L.OrderResult(False, "forced", "n1")
        return real(s, g, c)
    monkeypatch.setattr(L, "neighbors", neighbors_then_flag)
    monkeypatch.setattr(L, "check_order", late)
    with pytest.raises(GeneralizationOrderError, match="root proof failed: forced at n1"):
        enumerate_lattice(fake_m1, ctx, 1, climb=False)


def test_candidate_count_matches_distinct_hashes(ctx, fake_m1, fake_m2):
    for m in (fake_m1, fake_m2):
        lat = enumerate_lattice(m, ctx, 3)
        assert len(lat.candidates) == len({motif_hash(c.motif) for c in lat.candidates.values()})
        assert all(h == motif_hash(c.motif) == c.hash for h, c in lat.candidates.items())


def test_child_from_two_parents_once(ctx, fake_m1):
    lat = enumerate_lattice(fake_m1, ctx, 3)
    inc = Counter(e.child for e in lat.edges)
    multi = [h for h, n in inc.items() if n >= 2]
    assert multi, "no cross-edge child in M1 depth-3 lattice"
    assert all(len([e for e in lat.edges if e.child == h]) == inc[h] for h in multi)
    assert sum(1 for h in lat.candidates if h == multi[0]) == 1


def test_timing_and_counts(ctx, fake_m1, fake_m2):
    t = time.perf_counter()
    for name, m in (("M1", fake_m1), ("M2", fake_m2)):
        lat = enumerate_lattice(m, ctx, 3)
        cd = Counter(c.depth for c in lat.candidates.values())
        ed = Counter(lat.candidates[e.child].depth for e in lat.edges)
        print(name, "candidates/depth", sorted(cd.items()), "edges/child-depth", sorted(ed.items()))
    el = time.perf_counter() - t
    print("elapsed", el)
    assert el < 10


# ---- termination reporting ----

def _gctx(blocked=()):
    from tests.test_recursive_lift import _ctx
    return _ctx(blocked)


def _gm(code="SPEC"):
    from tests.support.hierarchy_graph import one_disorder_motif
    return one_disorder_motif(code)


def test_depth_cap_with_moves_is_depth_limited():
    lat = enumerate_lattice(_gm(), _gctx(), max_depth=2)
    assert lat.status == "depth_limited" and lat.unexpanded >= 1


def test_cap_on_dead_end_is_exhausted():
    lat = enumerate_lattice(_gm("C4"), _gctx({_root_id()}), max_depth=1)
    assert lat.status == "exhausted" and lat.unexpanded == 0


def _root_id():
    from semgen.snomed import ROOT_ID
    return ROOT_ID


def test_depth_zero_with_moves_is_depth_limited():
    lat = enumerate_lattice(_gm(), _gctx(), max_depth=0)
    assert lat.status == "depth_limited" and lat.unexpanded == 1


def test_full_exploration_is_exhausted():
    lat = enumerate_lattice(_gm(), _gctx(), max_depth=30)
    assert lat.status == "exhausted" and lat.unexpanded == 0


def test_hand_built_lattice_is_unknown():
    assert L.Lattice("r", {}, [], []).status == "unknown"


def test_candidate_budget_is_reported():
    lat = enumerate_lattice(_gm(), _gctx(), max_depth=30, max_candidates=3, climb=False)
    assert lat.status == "candidate_limited" and len(lat.candidates) <= 3 and lat.unexpanded >= 1
    assert all(e.child in lat.candidates and e.parent in lat.candidates for e in lat.edges)


def test_budget_run_is_deterministic():
    a, b = (enumerate_lattice(_gm(), _gctx(), max_depth=30, max_candidates=3) for _ in range(2))
    assert list(a.candidates) == list(b.candidates) and a.edges == b.edges and a.status == b.status


def test_budget_of_one_keeps_only_root():
    lat = enumerate_lattice(_gm(), _gctx(), max_depth=30, max_candidates=1, climb=False)
    assert list(lat.candidates) == [lat.root] and lat.edges == [] and lat.status == "candidate_limited"


@pytest.mark.parametrize("bad", [0, -1, True, 2.5, "3"])
def test_bad_max_candidates(bad):
    with pytest.raises(ValueError):
        enumerate_lattice(_gm(), _gctx(), max_depth=1, max_candidates=bad)


def test_any_frontier_motif_counts_not_just_first():
    lat = enumerate_lattice(_gm(), _gctx({"G"}), 1)  # frontier P1 (no moves), P2 (one move)
    assert lat.status == "depth_limited" and lat.unexpanded == 2


def test_budget_hit_keeps_later_edge_to_existing_candidate():
    lat = enumerate_lattice(_gm(), _gctx(), max_depth=30, max_candidates=4, climb=False)  # P2: BLOCKED dropped, then G exists
    codes = {h: c.motif.node("n1").code for h, c in lat.candidates.items()}
    assert lat.status == "candidate_limited" and "BLOCKED" not in codes.values()
    assert any(codes[e.parent] == "P2" and codes[e.child] == "G" for e in lat.edges)


def test_budget_hit_stops_search_after_current_motif(monkeypatch):
    calls = []
    real = L.neighbors
    monkeypatch.setattr(L, "neighbors", lambda m, c: (calls.append(m.node("n1").code), real(m, c))[1])
    lat = enumerate_lattice(_gm(), _gctx(), max_depth=30, max_candidates=4)
    assert calls == ["SPEC", "P1", "P2"] and lat.unexpanded == 1  # G was added but never expanded
