"""Motif deletion (design §7.4): SNOMED-constrained query containment over bundle parts, AND/OR directions,
duplicates, and the order checker's part-removal branch (§8)."""
from __future__ import annotations

from hypothesis import HealthCheck, find, given, settings
from hypothesis import strategies as st

from semgen.bundle import MotifBundle, MotifPart
from semgen.canonical import canonical_json, structural_signature
from semgen.model import PATIENT_ID, Edge, Interval, Motif, Node
from semgen.operators.containment_search import find_containment, find_isomorphism
from semgen.operators.motif_deletion import motif_deletion
from semgen.order import check_bundle_order, verify_containment
from tests.support.fake_snomed import (
    ANTHRA,
    CKD,
    DAUNO,
    DISEASE,
    DM,
    DOX,
    FAKE_ISA,
    MET,
    RA,
    RA_OLD_PARENT,
    SUBST,
    T1DM,
    T2DM,
)
from tests.support.matcher import matches, matches_bundle

# --- builders ------------------------------------------------------------------------------------


def motif(mid: str, nodes: dict[str, dict], edges: list[tuple]) -> Motif:
    """A motif whose non-P node ids are namespaced ``<mid>.<local>`` (as the loader does in a bundle).

    ``edges`` holds ``(s, t, rel)`` or ``(s, t, rel, extra_kwargs)`` in local ids; the first node is the anchor.
    """
    def ns(x: str) -> str:
        return x if x == PATIENT_ID else f"{mid}.{x}"
    ns_nodes = (Node(id=PATIENT_ID, type="Patient", role="patient"),) + tuple(
        Node(id=ns(k), **({"role": "modifier"} | v)) for k, v in nodes.items())
    ns_edges = tuple(Edge(s=ns(e[0]), t=ns(e[1]), rel=e[2], **({"prov": "asserted"} | (e[3] if len(e) > 3 else {})))
                     for e in edges)
    return Motif(motif_id=mid, anchor=ns(next(iter(nodes))), nodes=ns_nodes, edges=ns_edges)


def dx(mid: str, code: str, **kw) -> Motif:
    """P -has_condition-> d (a Disorder anchor)."""
    return motif(mid, {"d": {"type": "Disorder", "code": code, "role": "anchor"} | kw}, [("P", "d", "has_condition")])


def drug(mid: str, code: str) -> Motif:
    return motif(mid, {"d": {"type": "Substance", "code": code, "role": "anchor"}},
                 [("P", "d", "administered_drug")])


def dx_drug(mid: str, code: str, d_kw=None, m_kw=None, edges=None) -> Motif:
    """P -> d (Disorder), P -> m (Substance MET), d -> m ``treated_with``: the base for the mismatch tests."""
    nodes = {"d": {"type": "Disorder", "code": code, "role": "anchor"} | (d_kw or {}),
             "m": {"type": "Substance", "code": MET, "role": "exposure"} | (m_kw or {})}
    return motif(mid, nodes, edges if edges is not None else
                 [("P", "d", "has_condition"), ("P", "m", "administered_drug"), ("d", "m", "treated_with")])


def bundle(semantics, *parts, anchor: str = "A") -> MotifBundle:
    ps = tuple(MotifPart(part_id=p.motif_id, motif=p) for p in parts)
    return MotifBundle(bundle_id="B", semantics=semantics, anchor_part=anchor, parts=ps)


A = drug("A", DOX)   # anchor part: a different type, so it never covers or is covered by a Disorder part
X = dx("X", T2DM)    # X ⊑ Y
Y = dx("Y", DM)


def deleted(res) -> list[str]:
    return [mv.change.evidence["deleted"] for mv in res.moves]


def reasons(res) -> dict[str, str]:
    return {b.target: b.reason for b in res.blocked}


def by_deleted(res, pid):
    (mv,) = [mv for mv in res.moves if mv.change.evidence["deleted"] == pid]
    return mv


# --- scope A -------------------------------------------------------------------------------------


def test_all_deletes_broader(ctx):
    res = motif_deletion(bundle("all", A, X, Y), ctx)
    assert deleted(res) == ["Y"]
    mv = res.moves[0]
    ev = mv.change.evidence
    assert ev["subsumed_by"] == "X" and ev["direction"] == "deleted_is_broader" and ev["scope"] == "bundle_part"
    assert (mv.change.op, mv.change.target, mv.change.meaning, mv.change.rule_id) == \
        ("motif_deletion", "Y", "kept", "motif.delete.query_contained")
    assert [p.part_id for p in mv.child.parts] == ["A", "X"]
    assert reasons(res) == {"A": "anchor_part_protected", "X": "not_contained"}


def test_any_deletes_narrower(ctx):
    res = motif_deletion(bundle("any", A, X, Y), ctx)
    assert deleted(res) == ["X"]
    ev = res.moves[0].change.evidence
    assert ev["subsumed_by"] == "Y" and ev["direction"] == "deleted_is_narrower"
    assert reasons(res) == {"A": "anchor_part_protected", "Y": "not_contained"}


def test_exact_duplicate_deletes_larger_id(ctx):
    for sem in ("all", "any"):
        res = motif_deletion(bundle(sem, A, dx("M3", T2DM), dx("M4", T2DM)), ctx)
        assert deleted(res) == ["M4"], sem
        ch = res.moves[0].change
        assert ch.rule_id == "motif.delete.exact_duplicate" and ch.evidence["subsumed_by"] == "M3"
        if sem == "all":   # the deleted copy is the broad side G
            assert ch.evidence["mapping"] == {"P": "P", "M4.d": "M3.d"}
        else:              # the deleted copy is the narrow side S
            assert ch.evidence["mapping"] == {"P": "P", "M3.d": "M4.d"}
        assert "M3" not in reasons(res)   # the retained duplicate is not a blocked deletion


def test_exact_duplicate_anchor_is_larger_id_deletes_other(ctx):
    """Review Focus 4: the larger part id is the anchor, so the other duplicate goes; exactly one move."""
    for sem in ("all", "any"):
        res = motif_deletion(bundle(sem, dx("M1", T2DM), dx("M2", T2DM), anchor="M2"), ctx)
        assert deleted(res) == ["M1"], sem
        assert res.moves[0].change.rule_id == "motif.delete.exact_duplicate"
        assert res.moves[0].change.evidence["subsumed_by"] == "M2"
        assert [p.part_id for p in res.moves[0].child.parts] == ["M2"]
        assert reasons(res) == {"M2": "anchor_part_protected"}


def test_unknown_semantics_blocks(ctx):
    res = motif_deletion(bundle(None, A, X, Y), ctx)
    assert res.moves == []
    assert reasons(res) == {"A": "unknown_bundle_semantics", "X": "unknown_bundle_semantics",
                            "Y": "unknown_bundle_semantics"}


def test_anchor_part_protected(ctx):
    res = motif_deletion(bundle("all", X, Y, anchor="Y"), ctx)   # Y is broader, but it is the anchor
    assert res.moves == []
    assert reasons(res) == {"Y": "anchor_part_protected", "X": "not_contained"}


def test_last_part(ctx):
    res = motif_deletion(MotifBundle.of(X), ctx)
    assert res.moves == []
    assert [(b.target, b.reason) for b in res.blocked] == [("X", "last_part")]


def test_has_absent_node_blocks_deletion_but_can_be_retained(ctx):
    s = motif("S", {"d": {"type": "Disorder", "code": T2DM, "role": "anchor"},
                    "x": {"type": "Disorder", "code": T1DM, "polarity": "absent"}},
              [("P", "d", "has_condition"), ("P", "x", "has_condition")])
    res = motif_deletion(bundle("all", A, s, Y), ctx)
    assert deleted(res) == ["Y"]
    assert res.moves[0].change.evidence["subsumed_by"] == "S"
    assert reasons(res) == {"A": "anchor_part_protected", "S": "has_absent_node"}
    res = motif_deletion(bundle("any", A, s, Y), ctx)          # S is narrower, but it has an absent node
    assert res.moves == [] and reasons(res)["S"] == "has_absent_node"


def _mismatch(ctx, s: Motif, g: Motif) -> None:
    """``s`` has the narrower code but differs from ``g`` in one structural way: no containment either way."""
    assert find_containment(s, g, ctx) is None
    res = motif_deletion(bundle("all", A, s, g), ctx)
    assert res.moves == [] and reasons(res) == {"A": "anchor_part_protected", "S": "not_contained",
                                                "G": "not_contained"}


def test_mismatch_control(ctx):
    """Without the mismatch, ``S ⊑ G`` and the broader G is deleted (so each mismatch test is not vacuous)."""
    s, g = dx_drug("S", T2DM), dx_drug("G", DM)
    assert find_containment(s, g, ctx) == {"P": "P", "G.d": "S.d", "G.m": "S.m"}
    assert deleted(motif_deletion(bundle("all", A, s, g), ctx)) == ["G"]


def test_extra_unique_edge_not_contained(ctx):
    s = dx_drug("S", T2DM, edges=[("P", "d", "has_condition"), ("P", "m", "administered_drug")])
    _mismatch(ctx, s, dx_drug("G", DM))


def test_extra_unique_attr_not_contained(ctx):
    _mismatch(ctx, dx_drug("S", T2DM), dx_drug("G", DM, d_kw={"attrs": {"age_at_dx": Interval.closed(60, 70, "a")}}))


def test_role_mismatch(ctx):
    _mismatch(ctx, dx_drug("S", T2DM, m_kw={"role": "modifier"}), dx_drug("G", DM))


def test_type_mismatch(ctx):
    _mismatch(ctx, dx_drug("S", T2DM, m_kw={"type": "Finding"}), dx_drug("G", DM))


def test_polarity_mismatch(ctx):
    s = dx_drug("S", T2DM, m_kw={"polarity": "absent"})
    assert find_containment(s, dx_drug("G", DM), ctx) is None
    res = motif_deletion(bundle("all", A, s, dx_drug("G", DM)), ctx)
    assert res.moves == [] and reasons(res) == {"A": "anchor_part_protected", "S": "has_absent_node",
                                                "G": "not_contained"}


def test_edge_direction_mismatch(ctx):
    s = dx_drug("S", T2DM, edges=[("P", "d", "has_condition"), ("P", "m", "administered_drug"),
                                  ("m", "d", "treated_with")])
    _mismatch(ctx, s, dx_drug("G", DM))


def test_rel_mismatch(ctx):
    s = dx_drug("S", T2DM, edges=[("P", "d", "has_finding"), ("P", "m", "administered_drug"),
                                  ("d", "m", "treated_with")])
    _mismatch(ctx, s, dx_drug("G", DM))


def test_inactive_code_blocks(ctx):
    s, g = dx("S", RA), dx("G", RA_OLD_PARENT)   # RA IS-A RA_OLD_PARENT, but that parent is inactive
    assert find_containment(s, g, ctx) is None
    res = motif_deletion(bundle("all", A, s, g), ctx)
    assert res.moves == []
    r = {b.target: b for b in res.blocked}
    assert r["G"].reason == "snomed_mapping_missing" and r["S"].reason == "snomed_mapping_missing"
    assert r["G"].detail == {"inactive_codes": [RA_OLD_PARENT]}


def test_inactive_code_elsewhere_is_not_attributed(ctx):
    """``snomed_mapping_missing`` needs a tried node pair of equal type/role/polarity failing on an inactive code;
    an inactive code in the anchor part, or in a node no comparison reaches, leaves the failure ``not_contained``."""
    inactive_anchor = dx("A", RA_OLD_PARENT)                  # Disorder, inactive: compared with Substance parts only
    s = drug("S", DOX)
    g = motif("G", {"d": {"type": "Disorder", "code": DM, "role": "anchor"}}, [("P", "d", "administered_drug")])
    res = motif_deletion(bundle("all", inactive_anchor, s, g), ctx)
    assert res.moves == []
    r = {b.target: b for b in res.blocked}
    assert r["A"].reason == "anchor_part_protected"
    # S vs G and S vs A fail on type (Substance vs Disorder); G vs A: G.d -> A.d is Disorder/anchor/present, so that
    # pair is tried and A's inactive code obstructs it.
    assert (r["S"].reason, r["S"].detail) == ("not_contained", {})
    assert (r["G"].reason, r["G"].detail) == ("snomed_mapping_missing", {"inactive_codes": [RA_OLD_PARENT]})
    other_role = dx("A", RA_OLD_PARENT, role="modifier")      # roles differ: the inactive node is never compared
    res = motif_deletion(bundle("all", other_role, s, g), ctx)
    assert {b.target: b.reason for b in res.blocked} == {"A": "anchor_part_protected", "S": "not_contained",
                                                         "G": "not_contained"}


def test_signature_collision_not_trusted(ctx, monkeypatch):
    parts = (A, dx("M3", T2DM), dx("M4", T2DM), dx("M5", T1DM),
             motif("M6", {"d": {"type": "Disorder", "code": T2DM, "role": "anchor"}}, [("P", "d", "has_finding")]))
    honest = motif_deletion(bundle("all", *parts), ctx)
    import semgen.operators.motif_deletion as md
    monkeypatch.setattr(md, "structural_signature", lambda m: "same")
    forced = motif_deletion(bundle("all", *parts), ctx)
    for res in (honest, forced):
        assert [(mv.change.evidence["deleted"], mv.change.rule_id) for mv in res.moves] == \
            [("M4", "motif.delete.exact_duplicate")]
        assert reasons(res) == {"A": "anchor_part_protected", "M5": "not_contained", "M6": "not_contained"}


def test_structural_signature_is_id_free():
    assert structural_signature(dx("M3", T2DM)) == structural_signature(dx("M4", T2DM))
    assert structural_signature(dx("M3", T2DM)) != structural_signature(dx("M4", DM))
    assert structural_signature(dx_drug("S", T2DM)) != structural_signature(dx_drug("S", T2DM, edges=[
        ("P", "d", "has_condition"), ("P", "m", "administered_drug"), ("m", "d", "treated_with")]))


def test_find_isomorphism(ctx):
    assert find_isomorphism(dx("M3", T2DM), dx("M4", T2DM)) == {"P": "P", "M3.d": "M4.d"}
    assert find_isomorphism(dx("M3", T2DM), dx("M4", DM)) is None
    assert find_isomorphism(dx("M3", T2DM, label="x"), dx("M4", T2DM, dates={"onset": "2026-01-01"})) is None
    assert find_isomorphism(dx_drug("S", T2DM), dx_drug("G", T2DM, edges=[
        ("P", "d", "has_condition"), ("P", "m", "administered_drug"), ("m", "d", "treated_with")])) is None


def test_evidence_lineage(ctx):
    for sem, gone, kept_, narrow, broad in (("all", "Y", "X", X, Y), ("any", "X", "Y", X, Y)):
        (mv,) = motif_deletion(bundle(sem, A, X, Y), ctx).moves
        ev = mv.change.evidence
        assert ev["deleted"] == gone and ev["subsumed_by"] == kept_
        assert ev["deleted_canonical"] == canonical_json(Y if gone == "Y" else X)
        assert mv.certificate == ev["mapping"] == {"P": "P", "Y.d": "X.d"}
        assert verify_containment(narrow, broad, ev["mapping"], ctx).ok
        assert mv.change.before == gone and mv.change.after is None


# --- checker (§8) --------------------------------------------------------------------------------


def test_checker_accepts_valid_scope_a(ctx):
    for sem in ("all", "any"):
        for b in (bundle(sem, A, X, Y), bundle(sem, A, dx("M3", T2DM), dx("M4", T2DM))):
            res = motif_deletion(b, ctx)
            assert res.moves
            for mv in res.moves:
                assert check_bundle_order(b, mv.child, ctx, mv.certificate).ok, mv.change


def test_checker_rejects_wrong_direction_for_semantics(ctx):
    cert = {"P": "P", "Y.d": "X.d"}   # X ⊑ Y
    for sem, removed in (("all", "X"), ("any", "Y")):   # "all" may drop only the broader, "any" only the narrower
        b = bundle(sem, A, X, Y)
        child = b.model_copy(update={"parts": tuple(p for p in b.parts if p.part_id != removed)})
        r = check_bundle_order(b, child, ctx, cert)
        assert (r.ok, r.reason) == (False, "not_contained"), (sem, r)
    b = bundle("all", A, X, Y)
    child = b.model_copy(update={"parts": tuple(p for p in b.parts if p.part_id != "Y")})
    assert check_bundle_order(b, child, ctx, cert).ok


def test_checker_rejects_forged_certificate(ctx):
    b = bundle("all", A, X, Y)
    (mv,) = motif_deletion(b, ctx).moves
    for forged, reason in (({"P": "P", "Y.d": "P"}, "not_contained"),
                           ({"P": "P"}, "not_contained"),
                           ({"P": "P", "Y.d": "A.d"}, "not_contained")):
        r = check_bundle_order(b, mv.child, ctx, forged)
        assert (r.ok, r.reason) == (False, reason), (forged, r)
    r = check_bundle_order(b, mv.child, ctx, None)
    assert (r.ok, r.reason) == (False, "certificate_missing")
    # a forged child: the retained part changed as well
    lifted = mv.child.model_copy(update={"parts": (mv.child.parts[0], MotifPart(part_id="X", motif=dx("X", DM)))})
    r = check_bundle_order(b, lifted, ctx, mv.certificate)
    assert (r.ok, r.reason) == (False, "unsupported_transition")


def test_checker_scope_a_guards(ctx):
    s = motif("S", {"d": {"type": "Disorder", "code": T2DM, "role": "anchor"},
                    "x": {"type": "Disorder", "code": T1DM, "polarity": "absent"}},
              [("P", "d", "has_condition"), ("P", "x", "has_condition")])
    cases = [
        (bundle("any", A, s, Y), "S", {"P": "P", "Y.d": "S.d"}, "has_absent_node"),
        (bundle(None, A, X, Y), "Y", {"P": "P", "Y.d": "X.d"}, "unknown_bundle_semantics"),
    ]
    for b, removed, cert, reason in cases:
        child = b.model_copy(update={"parts": tuple(p for p in b.parts if p.part_id != removed)})
        r = check_bundle_order(b, child, ctx, cert)
        assert (r.ok, r.reason, r.where) == (False, reason, removed), r
    # a certificate in the wrong direction for "all" (the narrower part removed) never verifies
    b = bundle("all", A, X, Y)
    child = b.model_copy(update={"parts": tuple(p for p in b.parts if p.part_id != "X")})
    r = check_bundle_order(b, child, ctx, {"P": "P", "X.d": "Y.d"})
    assert (r.ok, r.reason) == (False, "not_contained")


def test_checker_does_not_import_the_search():
    import ast
    import pathlib

    import semgen.order
    tree = ast.parse(pathlib.Path(semgen.order.__file__).read_text())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
        {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any("containment_search" in m or "motif_deletion" in m for m in mods if m)


def test_duplicate_tie_break_is_independent_of_part_order(ctx):
    for sem in ("all", "any"):
        b = bundle(sem, A, dx("M2", T2DM), dx("M1", T2DM))
        r1 = motif_deletion(b, ctx)
        r2 = motif_deletion(b.model_copy(update={"parts": tuple(reversed(b.parts))}), ctx)
        assert deleted(r1) == deleted(r2) == ["M2"]
        (mv,) = r1.moves
        assert mv.change.rule_id == "motif.delete.exact_duplicate" and mv.change.evidence["subsumed_by"] == "M1"
        assert mv.change.evidence["deleted_canonical"] == canonical_json(dx("M2", T2DM))   # traceable


def test_remaining_parts_are_unchanged(ctx):
    for sem, gone in (("all", "Y"), ("any", "X")):
        b = bundle(sem, A, X, Y)
        (mv,) = motif_deletion(b, ctx).moves
        assert deleted(motif_deletion(b, ctx)) == [gone]
        assert {p.part_id: p for p in mv.child.parts} == {p.part_id: p for p in b.parts if p.part_id != gone}
        assert (mv.child.semantics, mv.child.anchor_part) == (b.semantics, b.anchor_part)   # Boolean structure kept


def _grouped(mid: str, *codes: str) -> Motif:
    """A part whose two disorders are already an A3 group (members verbatim, summary DM)."""
    from semgen.operators.attribute_aggregation import attribute_aggregation
    m = motif(mid, {"a": {"type": "Substance", "code": MET, "role": "anchor"},
                    **{f"x{i}": {"type": "Disorder", "code": c} for i, c in enumerate(codes)}},
              [("P", "a", "administered_drug")] + [("P", f"x{i}", "has_condition") for i in range(len(codes))])
    (mv,) = [mv for mv in attribute_aggregation(m, ctx_global()).moves if mv.change.rule_id == "attr.aggregate.ontology"]
    return mv.child


def ctx_global():
    from semgen.config import load_config
    from semgen.operators.base import GenContext
    from tests.conftest import _CONFIG_PATH
    from tests.support.fake_snomed import fake_boundary_policy, fake_hierarchy
    h = fake_hierarchy()
    return GenContext(h, load_config(_CONFIG_PATH), fake_boundary_policy(h))


def test_grouped_parts_compare_only_as_identical_groups(ctx):
    """Grouped (A3) membership is never reinterpreted: an identical grouped part is a duplicate; a part that names
    one member concept alone is not proven to cover the group."""
    g1, g2 = _grouped("G1", T1DM, T2DM), _grouped("G2", T1DM, T2DM)
    res = motif_deletion(bundle("all", A, g1, g2), ctx)
    assert deleted(res) == ["G2"] and res.moves[0].change.rule_id == "motif.delete.exact_duplicate"
    h = ctx.hierarchy
    b = bundle("all", A, g1, g2)
    pats = [motif("PAT", {"a": {"type": "Substance", "code": MET, "role": "anchor"},
                          **{f"x{i}": {"type": "Disorder", "code": c} for i, c in enumerate(cs)}},
                  [("P", "a", "administered_drug")] + [("P", f"x{i}", "has_condition") for i in range(len(cs))])
            for cs in ((T1DM, T2DM), (T1DM,), (DM, DM), ())]
    pats.append(drug("PAT", DOX).model_copy(update={"nodes": pats[0].nodes + drug("Q", DOX).nodes[1:],
                                                    "edges": pats[0].edges + drug("Q", DOX).edges}))
    assert [matches_bundle(b, p, h) for p in pats] == [matches_bundle(res.moves[0].child, p, h) for p in pats]
    single = motif("S", {"a": {"type": "Substance", "code": MET, "role": "anchor"}, "x": {"type": "Disorder",
                                                                                         "code": T1DM}},
                   [("P", "a", "administered_drug"), ("P", "x", "has_condition")])
    res = motif_deletion(bundle("any", A, g1, single), ctx)
    assert deleted(res) == []


# --- property tests (hypothesis) -----------------------------------------------------------------

CODES = {"Disorder": [DISEASE, DM, T1DM, T2DM, CKD], "Substance": [SUBST, ANTHRA, DOX, DAUNO, MET]}
RELS = ["r1", "r2"]
PROVS = ["asserted", "derived"]
PROPERTY = settings(suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
                    deadline=None, max_examples=150, derandomize=True)


@st.composite
def node_specs(draw, min_size=1, max_size=3) -> tuple[dict, list]:
    k = draw(st.integers(min_size, max_size))
    nodes: dict[str, dict] = {}
    for i in range(k):
        typ = draw(st.sampled_from(sorted(CODES)))
        pol = draw(st.sampled_from(["present", "present", "present", "absent"])) if i else "present"
        attrs = {}
        if pol == "present" and draw(st.booleans()):
            lo = draw(st.integers(0, 3))
            attrs = {"age_at_dx": Interval.closed(lo, draw(st.integers(lo, 4)), "a")}
        nodes[f"x{i}"] = {"type": typ, "code": draw(st.sampled_from(CODES[typ])), "polarity": pol,
                          "role": draw(st.sampled_from(["anchor", "modifier"])) if i else "anchor", "attrs": attrs}
    edges = [("P", n, draw(st.sampled_from(RELS)), {"prov": draw(st.sampled_from(PROVS))}) for n in nodes]
    for a in nodes:
        for b in nodes:
            if a != b and draw(st.integers(0, 3)) == 0:
                edges.append((a, b, draw(st.sampled_from(RELS)), {"prov": "asserted"}))
    return nodes, edges


@st.composite
def mutated(draw, spec: tuple[dict, list]) -> tuple[dict, list]:
    """An arbitrary edit of ``spec`` (generalizing or not): drop/recode nodes, edit attrs, drop/relabel edges."""
    nodes = {k: dict(v) for k, v in spec[0].items()}
    edges = list(spec[1])
    for _ in range(draw(st.integers(0, 3))):
        op = draw(st.sampled_from(["drop_node", "lift", "recode", "attr", "drop_edge", "rel", "polarity"]))
        k = draw(st.sampled_from(sorted(nodes)))
        n = nodes[k]
        if op == "drop_node" and len(nodes) > 1 and k != "x0":
            del nodes[k]
            edges = [e for e in edges if k not in (e[0], e[1])]
        elif op == "lift" and FAKE_ISA.get(n["code"]):
            n["code"] = sorted(FAKE_ISA[n["code"]])[0]
        elif op == "recode":
            n["code"] = draw(st.sampled_from(CODES[n["type"]]))
        elif op == "attr" and n["polarity"] == "present":
            lo = draw(st.integers(0, 3))
            n["attrs"] = draw(st.sampled_from([{}, {"age_at_dx": Interval.closed(lo, draw(st.integers(lo, 4)), "a")}]))
        elif op == "drop_edge" and edges:
            edges.pop(draw(st.integers(0, len(edges) - 1)))
        elif op == "rel" and edges:
            i = draw(st.integers(0, len(edges) - 1))
            edges[i] = (edges[i][0], edges[i][1], draw(st.sampled_from(RELS)), edges[i][3])
        elif op == "polarity" and k != "x0":
            n["polarity"] = "absent" if n["polarity"] == "present" else "present"
            n["attrs"] = {}
    return nodes, edges


def as_patient_nodes(m: Motif) -> tuple[list[Node], list[Edge]]:
    """The present facts of ``m`` (attrs pinned to their lower bound), and their edges."""
    absent = {n.id for n in m.nodes if n.polarity == "absent"}
    nodes = [n.model_copy(update={"attrs": {k: Interval.point(v.lo, v.unit) for k, v in n.attrs.items()}})
             for n in m.nodes if n.id not in absent]
    return nodes, [e for e in m.edges if e.s not in absent and e.t not in absent]


def patient_of(*motifs: Motif) -> Motif:
    nodes: dict[str, Node] = {}
    edges: dict[tuple, Edge] = {}
    for m in motifs:
        ns, es = as_patient_nodes(m)
        nodes |= {n.id: n for n in ns}
        edges |= {e.key: e for e in es}
    return Motif(motif_id="PAT", anchor=PATIENT_ID, nodes=tuple(nodes.values()), edges=tuple(edges.values()))


@st.composite
def random_patients(draw) -> list[Motif]:
    out = []
    for j in range(draw(st.integers(0, 4))):
        spec = draw(node_specs(1, 4))
        nodes = {k: v | {"polarity": "present"} for k, v in spec[0].items()}
        out.append(patient_of(motif(f"R{j}", nodes, spec[1])))
    return out


@st.composite
def related_motifs(draw, mid: str, base: tuple[dict, list] | None) -> tuple[Motif, tuple[dict, list]]:
    spec = draw(node_specs()) if base is None or draw(st.integers(0, 3)) == 0 else draw(mutated(base))
    return motif(mid, *spec), spec


@st.composite
def containment_cases(draw) -> tuple[Motif, Motif, list[Motif]]:
    """A narrow motif, a (usually related) broad one, and patients: both as patients plus random ones."""
    n, spec = draw(related_motifs("N", None))
    b, _ = draw(related_motifs("G", spec))
    return n, b, [patient_of(n), patient_of(b)] + draw(random_patients())


@st.composite
def deletion_cases(draw) -> tuple[MotifBundle, list[Motif]]:
    """A bundle of an anchor part and 1-3 parts derived from it or each other, and patients built from the parts."""
    anchor, spec = draw(related_motifs("A", None))
    others, base = [], spec
    for mid in ("M1", "M2", "M3")[:draw(st.integers(1, 3))]:
        m, s = draw(related_motifs(mid, base))
        others.append(m)
        base = draw(st.sampled_from([base, s]))
    b = bundle(draw(st.sampled_from(["all", "any"])), anchor, *others)
    parts = [anchor, *others]
    patients = [patient_of(*parts), *(patient_of(m) for m in parts)] + draw(random_patients())
    patients += [patient_of(*[m for m in parts if m.motif_id != drop]) for drop in [m.motif_id for m in parts]]
    return b, patients


@PROPERTY
@given(containment_cases())
def test_certificate_implies_matcher_containment(ctx, case):
    n, b, patients = case
    cert = find_containment(n, b, ctx)
    if cert is None:
        return
    assert verify_containment(n, b, cert, ctx).ok
    for p in patients:
        if matches(n, p, ctx.hierarchy):
            assert matches(b, p, ctx.hierarchy), (cert, p)


@PROPERTY
@given(deletion_cases())
def test_deletion_preserves_bundle_match_set(ctx, case):
    b, patients = case
    for mv in motif_deletion(b, ctx).moves:
        assert check_bundle_order(b, mv.child, ctx, mv.certificate).ok, mv.change
        for p in patients:
            assert matches_bundle(b, p, ctx.hierarchy) == matches_bundle(mv.child, p, ctx.hierarchy), mv.change


NON_VACUITY = settings(PROPERTY, max_examples=500, database=None)


def test_property_generators_are_not_vacuous(ctx):
    """Guard against a generator regression silently emptying the properties above (deterministic: derandomized
    ``find``): the same strategies must yield a certificate over a patient that matches the narrow motif, and
    bundles with a containment move under "all" and under "any"."""
    h = ctx.hierarchy
    find(containment_cases(), lambda c: find_containment(c[0], c[1], ctx) is not None
         and any(matches(c[0], p, h) for p in c[2]), settings=NON_VACUITY)
    for sem in ("all", "any"):
        find(deletion_cases(), lambda c, sem=sem: c[0].semantics == sem and any(
            mv.change.rule_id == "motif.delete.query_contained" for mv in motif_deletion(c[0], ctx).moves),
             settings=NON_VACUITY)
