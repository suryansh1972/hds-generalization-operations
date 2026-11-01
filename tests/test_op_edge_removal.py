from semgen.canonical import canonical_json
from semgen.model import Edge, Motif, Node, PATIENT_ID
from semgen.operators import ALL_OPERATORS
from semgen.operators.edge_removal import edge_removal
from tests.conftest import SUBST, one_node_motif


def by_target(r): return {mv.change.target: mv for mv in r.moves}


def test_gene_pathway_edge_drops_pathway(ctx, fake_m1):
    mv = by_target(edge_removal(fake_m1, ctx))["n4->n5"]
    assert "n5" not in mv.child.node_ids and "n4" in mv.child.node_ids


def test_drug_gene_edge_drops_gene_and_pathway(ctx, fake_m1):
    mv = by_target(edge_removal(fake_m1, ctx))["n2->n4"]
    assert mv.change.evidence["removed_nodes"] == ["n4", "n5"]


def test_patient_drug_edge_cascades(ctx, fake_m1):
    c = by_target(edge_removal(fake_m1, ctx))["P->n2"].child
    assert {"n2", "n4", "n5"}.isdisjoint(c.node_ids) and "n3" in c.node_ids and c.edge("n2", "n3") is None


def test_followed_by_removal_keeps_both_nodes(ctx, fake_m1):
    c = by_target(edge_removal(fake_m1, ctx))["n2->n3"].child
    assert {"n2", "n3"} <= c.node_ids


def test_protected_edges(ctx, fake_m1, fake_m2):
    assert "P->n1" not in by_target(edge_removal(fake_m1, ctx))
    r2 = edge_removal(fake_m2, ctx)
    assert "P->n2" not in by_target(r2) and any(b.reason == "touches_absent" for b in r2.blocked)


def test_last_asserted_edge_kept(ctx, fake_m1):
    m = fake_m1
    while (mvs := [mv for mv in edge_removal(m, ctx).moves]): m = mvs[0].child
    assert any(e.prov == "asserted" for e in m.edges) and m.anchor in m.node_ids


# ---- extras ----

def test_all_operators_final_order():
    from semgen.operators.attribute_removal import attribute_removal
    from semgen.operators.concept_lift import concept_lift
    from semgen.operators.range_coarsening import range_coarsening
    from semgen.operators.relation_relaxation import relation_relaxation
    from semgen.operators.temporal_coarsening import temporal_coarsening
    expected = [concept_lift, attribute_removal, range_coarsening, temporal_coarsening,
                relation_relaxation, edge_removal]
    assert len(ALL_OPERATORS) == len(expected)
    assert all(a is b for a, b in zip(ALL_OPERATORS, expected))


def test_patient_drug_cascade_evidence(ctx, fake_m1):
    mv = by_target(edge_removal(fake_m1, ctx))["P->n2"]
    assert mv.change.evidence["removed_nodes"] == ["n2", "n4", "n5"]
    assert mv.change.evidence["removed_edges"] == ["P->n2", "n2->n3", "n2->n4", "n4->n5"]
    assert mv.change.op == "edge_removal" and mv.change.field == "edge" and mv.change.after is None
    assert {"n3"} <= mv.child.node_ids
    assert mv.child.edge("P", "n3") is not None and mv.child.edge("P", "n1") is not None


def test_before_record(ctx, fake_m1):
    mv = by_target(edge_removal(fake_m1, ctx))["n2->n3"]
    e = fake_m1.edge("n2", "n3")
    assert mv.change.before == {"s": "n2", "t": "n3", "rel": e.rel, "prov": e.prov,
                                "window": e.window.to_json(), "bpn_score": e.bpn_score}
    assert mv.change.before["window"] == fake_m1.edge("n2", "n3").window.to_json()
    assert by_target(edge_removal(fake_m1, ctx))["n2->n4"].change.before["window"] is None


def test_leaf_context_edge_removes_only_leaf(ctx, fake_m1):
    mv = by_target(edge_removal(fake_m1, ctx))["n4->n5"]
    assert mv.change.evidence["removed_nodes"] == ["n5"]
    assert mv.change.evidence["removed_edges"] == ["n4->n5"]


def test_patient_measurement_edge(ctx, fake_m1):
    mv = by_target(edge_removal(fake_m1, ctx))["P->n3"]
    assert mv.change.evidence["removed_nodes"] == ["n3"]
    assert mv.change.evidence["removed_edges"] == ["P->n3", "n2->n3"]
    assert {"n2", "n4", "n5"} <= mv.child.node_ids


def test_m1_move_targets(ctx, fake_m1):
    assert set(by_target(edge_removal(fake_m1, ctx))) == {"P->n2", "P->n3", "n2->n3", "n2->n4", "n4->n5"}


def test_m2_absent_and_anchor_protection(ctx, fake_m2):
    r = edge_removal(fake_m2, ctx)
    assert "P->n2" not in by_target(r) and "P->n1" not in by_target(r)
    assert all("n2" in mv.child.node_ids and mv.child.edge("P", "n2") is not None for mv in r.moves)
    bl = {(b.target, b.reason): b for b in r.blocked}
    assert ("P->n2", "touches_absent") in bl and ("P->n1", "protected_anchor_edge") in bl
    assert bl[("P->n1", "protected_anchor_edge")].detail["rel"] == "has_condition"
    assert "prov" in bl[("P->n2", "touches_absent")].detail


def test_no_asserted_left(ctx):
    m = one_node_motif(SUBST)
    m = m.replace_edge(m.edge("P", "n1").model_copy(update={"prov": "derived"}))
    m = m.model_copy(update={
        "nodes": m.nodes + (Node(id="n2", type="Substance", role="exposure", code=SUBST),),
        "edges": m.edges + (Edge(s="P", t="n2", rel="administered_drug", prov="asserted"),)})
    r = edge_removal(m, ctx)
    assert "P->n2" not in by_target(r)
    assert any(b.target == "P->n2" and b.reason == "no_asserted_left" for b in r.blocked)


def test_would_drop_protected(ctx):
    m = Motif(motif_id="H", anchor="n1",
              nodes=(Node(id="P", type="Patient", role="patient"),
                     Node(id="n1", type="Disorder", role="anchor", code=SUBST),
                     Node(id="n2", type="Substance", role="exposure", code=SUBST)),
              edges=(Edge(s="P", t="n2", rel="administered_drug", prov="asserted"),
                     Edge(s="n2", t="n1", rel="treats", prov="asserted")))
    r = edge_removal(m, ctx)
    (b,) = [b for b in r.blocked if b.target == "P->n2"]
    assert b.reason == "would_drop_protected" and b.detail["dropped"] == ["n1"]


def test_children_invariants_and_purity(ctx, fake_m1, fake_m2):
    for m in (fake_m1, fake_m2):
        before = canonical_json(m)
        for mv in edge_removal(m, ctx).moves:
            assert m.anchor in mv.child.node_ids and PATIENT_ID in mv.child.node_ids
            assert any(e.prov == "asserted" for e in mv.child.edges)
        assert canonical_json(m) == before


def _undirected_motif():
    def n(i, role="context"): return Node(id=i, type="Substance", role=role, code=SUBST)
    def e(s, t): return Edge(s=s, t=t, rel="associated_with", prov="asserted")
    return Motif(motif_id="U", anchor="n1",
                 nodes=(Node(id="P", type="Patient", role="patient"), n("n1", "anchor"), n("a"), n("b"), n("c")),
                 edges=(e("P", "n1"), e("P", "a"), e("b", "a"), e("b", "c")))


def test_bfs_ignores_direction(ctx):
    r = by_target(edge_removal(_undirected_motif(), ctx))
    ev = r["P->a"].change.evidence
    assert ev["removed_nodes"] == ["a", "b", "c"]
    assert ev["removed_edges"] == ["P->a", "b->a", "b->c"]
    ev = r["b->c"].change.evidence
    assert ev["removed_nodes"] == ["c"] and ev["removed_edges"] == ["b->c"]
    assert "b" in r["b->c"].child.node_ids
    ev = r["b->a"].change.evidence
    assert ev["removed_nodes"] == ["b", "c"] and ev["removed_edges"] == ["b->a", "b->c"]
    assert "a" in r["b->a"].child.node_ids


def test_would_drop_absent_node(ctx):
    m = Motif(motif_id="A", anchor="n1",
              nodes=(Node(id="P", type="Patient", role="patient"),
                     Node(id="n1", type="Disorder", role="anchor", code=SUBST),
                     Node(id="n2", type="Substance", role="exposure", code=SUBST),
                     Node(id="x", type="Disorder", role="modifier", code=SUBST, polarity="absent")),
              edges=(Edge(s="P", t="n1", rel="has_condition", prov="asserted"),
                     Edge(s="P", t="n2", rel="administered_drug", prov="asserted"),
                     Edge(s="n2", t="x", rel="associated_with", prov="asserted")))
    r = edge_removal(m, ctx)
    assert any(b.target == "n2->x" and b.reason == "touches_absent" for b in r.blocked)
    (b,) = [b for b in r.blocked if b.target == "P->n2"]
    assert b.reason == "would_drop_protected" and b.detail["dropped"] == ["x"]
