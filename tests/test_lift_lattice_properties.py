"""Concept lifting is multi-branch candidate generation (design §7.0, §9): the lattice holds every accepted one-step
generalization from every state, deduplicated, with derivation provenance on its edges; nothing is ranked or selected,
and the export holds the same candidates and edges."""
from __future__ import annotations

import tempfile
from collections import Counter, deque
from pathlib import Path

import pytest

from semgen.canonical import canonical_json, motif_hash
from semgen.config import load_config
from semgen.export import write_lattice
from semgen.lattice import Budget, enumerate_lattice
from semgen.motif_io import parse_motif
from semgen.operators.base import GenContext
from semgen.operators.concept_lift import concept_lift
from tests.support.fake_snomed import (
    BRCA,
    CONFIG_PATH,
    DOX,
    FAKE_M1,
    FAKE_M2,
    MAL_THORAX,
    NEO_BREAST,
    T2DM,
    fake_boundary_policy,
    fake_hierarchy,
)
from tests.support.ops import with_ops

RAW = {"motif_id": "F", "anchor": "n1", "nodes": [{"id": "P", "type": "Patient", "role": "patient"},
       {"id": "n1", "type": "Disorder", "code": T2DM, "polarity": "present", "role": "anchor"},
       {"id": "n2", "type": "Disorder", "code": BRCA, "polarity": "present", "role": "modifier"},
       {"id": "n3", "type": "Substance", "code": DOX, "polarity": "present", "role": "exposure"}],
       "edges": [{"s": "P", "t": "n1", "rel": "has_condition", "prov": "asserted"},
                 {"s": "P", "t": "n2", "rel": "has_condition", "prov": "asserted"},
                 {"s": "P", "t": "n3", "rel": "administered_drug", "prov": "asserted"}]}


def _cases():
    cfg = load_config(CONFIG_PATH)
    fh = fake_hierarchy()
    ctx = with_ops(GenContext(fh, cfg, fake_boundary_policy(fh)), concept_lift)   # concept lift only
    return [("polyhierarchy", parse_motif(RAW, None), ctx),
            ("M1", parse_motif(FAKE_M1, None), ctx), ("M2", parse_motif(FAKE_M2, None), ctx)]




@pytest.mark.parametrize("name,root,ctx", _cases(), ids=lambda x: x if isinstance(x, str) else "")
def test_lift_lattice_is_complete_deduplicated_and_provenanced(name, root, ctx):
    lat = enumerate_lattice(root, ctx, Budget())
    h, C, E = ctx.hierarchy, lat.candidates, lat.edges
    assert lat.status == "exhausted"
    edges = {(e.parent, e.child) for e in E}
    # every accepted lift from every state is in the lattice (no branch dropped, none selected)
    for hh, c in C.items():
        for mv in concept_lift(c.bundle.single_motif, ctx).moves:
            assert (hh, motif_hash(mv.child)) in edges, (name, mv.change)
    # one candidate per distinct motif
    canon = [canonical_json(c.bundle.single_motif) for c in C.values()]
    assert len(canon) == len(set(canon))
    # provenance: each edge is one IS-A step on one node, matching the parent/child diff
    for e in E:
        (ch,) = e.changes
        pm, cm = C[e.parent].bundle.single_motif, C[e.child].bundle.single_motif
        assert [n.id for n in pm.nodes if pm.node(n.id).code != cm.node(n.id).code] == [ch.target]
        assert (pm.node(ch.target).code, cm.node(ch.target).code) == (ch.before, ch.after)
        assert ch.after in h.parents(ch.before)
    # every candidate is derivable from the root, and replaying its change records rebuilds it
    prev, q = {lat.root: None}, deque([lat.root])
    adj: dict = {}
    for e in E:
        adj.setdefault(e.parent, []).append(e)
    while q:
        x = q.popleft()
        for e in adj.get(x, []):
            if e.child not in prev:
                prev[e.child] = e
                q.append(e.child)
    assert set(prev) == set(C)
    for hh in C:
        m, path, x = root, [], hh
        while prev[x] is not None:
            path.append(prev[x])
            x = prev[x].parent
        for e in reversed(path):
            (ch,) = e.changes
            m = m.replace_node(m.node(ch.target).model_copy(update={"code": ch.after, "label": h.fsn(ch.after)}))
        assert motif_hash(m) == hh
    # the export holds the same candidates and edges
    with tempfile.TemporaryDirectory() as t:
        p = write_lattice(lat, "X", Path(t), {})
        assert len(p["candidates"].read_text().splitlines()) == len(C)
        assert len(p["edges"].read_text().splitlines()) == len(E)


def test_polyhierarchy_branches_and_merging_derivations():
    _, root, ctx = _cases()[0]
    lat = enumerate_lattice(root, ctx, Budget())
    first = {e.child for e in lat.edges if e.parent == lat.root and e.changes[0].target == "n2"}
    assert {lat.candidates[c].bundle.single_motif.node("n2").code for c in first} == {MAL_THORAX, NEO_BREAST}   # both parents
    indeg = Counter(e.child for e in lat.edges)
    assert any(v >= 2 for v in indeg.values())     # the same motif reached by different lift orders: kept once,
                                                    # with every derivation as its own edge
