"""Lattice policy guard (design §8): hard rules every candidate move must satisfy, checked from the parent/child diff.

Code changes are re-derived from the diff, never read from the operator's ChangeRecord, and every applied concept-lift
step is re-checked by the independent verifier (``semgen.lift_verify``). A violation raises; nothing is dropped.
"""
from __future__ import annotations

from semgen.bundle import MotifBundle
from semgen.interfaces import ChangeRecord, GenContext
from semgen.lift_verify import verify_transition
from semgen.model import PATIENT_ID, Motif
from semgen.operators.concept_lift import OP as LIFT_OP


class PolicyViolation(Exception):
    """A candidate move breaks a hard policy rule."""


class GeneralizationOrderError(Exception):
    """A candidate move is not provably more general than its parent."""


def _violation(rule: str, element: str, detail: str = "") -> PolicyViolation:
    return PolicyViolation(f"{rule}: {element}" + (f" ({detail})" if detail else ""))


def _verified_path(code: str, target: str, ctx: GenContext) -> bool:
    """Some chain of inferred-parent steps from ``code`` up to ``target``, each accepted by the independent
    verifier (``semgen.lift_verify``)."""
    h, cm, fp = ctx.hierarchy, ctx.floors.concept_model, ctx.floors.fingerprint
    seen, todo = {code}, [code]
    while todo:
        c = todo.pop()
        if c == target:
            return True
        for p in sorted(h.parents(c)):
            if p not in seen and target in h.ancestors_or_self(p) and not verify_transition(h, cm, c, p, None, fp, fp):
                seen.add(p)
                todo.append(p)
    return False


def _verify_group_summary(nid: str, node, ctx: GenContext, what: str) -> None:
    """A3: the grouping's summary concept is the unique minimal common ancestor of the member concepts and lies
    within the concept-lift boundary of every member (re-derived here, never read from the ChangeRecord)."""
    h, g = ctx.hierarchy, node.grouping
    codes = sorted({m.code for m in node.members if m.code is not None})
    if any(m.code is None for m in node.members) or len(codes) < 2:
        raise _violation("group_summary_unverified", nid, f"member concepts {codes}; {what}")
    if g.kind != "ontology" or g.version != f"{h.edition}/{h.release}":
        raise _violation("group_summary_unverified", nid, f"grouping {g.kind} {g.version}; {what}")
    if not h.is_active(g.code) or not all(h.is_active(c) for c in codes):
        raise _violation("group_summary_unverified", nid, f"inactive concept; {what}")
    common = set(h.ancestors_or_self(codes[0]))
    for c in codes[1:]:
        common &= h.ancestors_or_self(c)
    lowest = sorted(a for a in common if not any(a != b and a in h.ancestors(b) for b in common))
    if lowest != [g.code]:
        raise _violation("group_summary_not_unique_lca", nid, f"lowest={lowest} summary={g.code}; {what}")
    for c in codes:
        if not _verified_path(c, g.code, ctx):
            raise _violation("group_summary_outside_boundary", f"{c}->{g.code}", what)


def _absent_ids(m: Motif) -> set[str]:
    return {i for i in m.node_ids if m.node(i).polarity == "absent"}


def _absent_edges(m: Motif) -> dict:
    ab = _absent_ids(m)
    return {e.key: e for e in m.edges if e.s in ab or e.t in ab}


def guard(parent: Motif, child: Motif, change: ChangeRecord | None, ctx: GenContext) -> None:
    for nid in (PATIENT_ID, parent.anchor):
        if nid not in child.node_ids:
            raise _violation("protected_node_removed", nid)
    p_abs, c_abs = _absent_ids(parent), _absent_ids(child)
    for nid in sorted(p_abs):
        if nid not in child.node_ids or child.node(nid) != parent.node(nid):
            raise _violation("absent_node_changed", nid)
    for nid in sorted(c_abs - p_abs):
        raise _violation("absent_node_changed", nid, "absent node not in parent")
    p_edges, c_edges = _absent_edges(parent), _absent_edges(child)
    for key, e in sorted(p_edges.items()):
        ce = child.edge(*key)
        if ce is None or ce != e:
            raise _violation("absent_edge_changed", f"{key[0]}->{key[1]}")
    for key in sorted(set(c_edges) - set(p_edges)):
        raise _violation("absent_edge_changed", f"{key[0]}->{key[1]}", "absent edge not in parent")
    for e in sorted(child.edges, key=lambda x: x.key):
        if e.prov != "context":
            continue
        pe = parent.edge(e.s, e.t)
        if pe is not None and pe != e:
            raise _violation("context_edge_changed", f"{e.s}->{e.t}")
    # A NEW context edge (no parent counterpart) is allowed here on purpose: check_order
    # rejects it as ``extra_edge``, so it can never reach the lattice.
    for nid in sorted(parent.node_ids & child.node_ids):
        cn = child.node(nid)
        kept_attrs = next((m.attrs for m in cn.members if m.id == nid), cn.attrs)   # A3 moves attrs into members
        lost = sorted(a for a in set(parent.node(nid).attrs) - set(kept_attrs)
                      if ctx.config.attr_is_concept_dependent(a))
        if lost:
            raise _violation("dependent_attr_removed", nid, f"attrs={lost}")
    # A1 units (independent of the operator): every observation of a new or changed A1 aggregate must carry a
    # valid UCUM unit of the pinned essence; without an essence nothing can be accepted.
    for nid in sorted(child.node_ids):
        cn = child.node(nid)
        if not cn.observations or (nid in parent.node_ids and parent.node(nid).observations == cn.observations):
            continue
        units = sorted({o.value.unit for o in cn.observations})
        if ctx.ucum is None:
            raise _violation("a1_unit_unverified", nid, f"units={units}; no UCUM essence loaded")
        bad = [u for u in units if not ctx.ucum.is_valid(u)]
        if bad:
            raise _violation("a1_unit_invalid", nid, f"units={bad}; UCUM {ctx.ucum.version}")
    # Code changes are derived from the parent/child diff, never from the operator's ChangeRecord.
    h = ctx.hierarchy
    for nid in sorted(parent.node_ids & child.node_ids):
        pn, cn = parent.node(nid), child.node(nid)
        if cn.members and not pn.members:   # A3 grouping: the summary here, exactness by check_group_merge
            _verify_group_summary(nid, cn, ctx, f"node {nid}" + (f" via {change.op}" if change is not None else ""))
            continue
        if pn.code == cn.code:
            continue
        what = f"node {nid}" + (f" via {change.op}" if change is not None else "")
        if pn.role == "context":
            raise _violation("context_code_changed", nid, what)
        if pn.polarity != "present":
            continue  # absent nodes are covered by absent_node_changed
        if pn.value is not None or pn.observations:   # A1 observations carry values too (design §7.3)
            raise _violation("lift_on_valued_node", nid, what)
        dependent = sorted(a for a in pn.attrs if ctx.config.attr_is_concept_dependent(a))
        if dependent:
            raise _violation("lift_on_dependent_attr", nid, f"attrs={dependent}; {what}")
        if pn.code is None or cn.code is None or cn.code not in h.parents(pn.code):
            raise _violation("not_direct_parent", f"{pn.code}->{cn.code}", what)
        if not h.is_active(cn.code):
            raise _violation("inactive_target", str(cn.code), what)
        d = ctx.floors.check_lift(pn.code, cn.code, role=pn.role, node_id=nid, cohort=ctx.cohort)
        if not d.ok:
            raise _violation("floor_violation", f"{pn.code}->{cn.code}", f"reason={d.reason}; {what}")
        _verify_lift(pn.code, cn.code, nid, change, ctx, what)


def _verify_lift(child: str, parent: str, nid: str, change: ChangeRecord | None, ctx: GenContext, what: str) -> None:
    """The independent verifier (``semgen.lift_verify``) must accept every applied step; a concept-lift record must
    describe exactly this step and carry the fingerprint of the release in force."""
    record, used = None, ctx.floors.fingerprint
    if change is not None and change.op == LIFT_OP:
        if (change.target, change.field, change.before, change.after) != (nid, "code", child, parent) \
                or change.evidence.get("isa") != [child, parent]:
            raise _violation("change_record_mismatch", f"{child}->{parent}",
                             f"record={change.target}:{change.before}->{change.after}; {what}")
        record, used = change.evidence.get("transition"), change.evidence.get("fingerprint")
    problems = verify_transition(ctx.hierarchy, ctx.floors.concept_model, child, parent, record, used,
                                 ctx.floors.fingerprint)
    if problems:
        raise _violation("lift_verification_failed", f"{child}->{parent}", f"{problems}; {what}")


def bundle_guard(parent: MotifBundle, child: MotifBundle) -> None:
    """Bundle-level policy (design §8): the anchor part stays, and every motif keeps the parent's ``P`` node."""
    if child.anchor_part != parent.anchor_part or child.anchor_part not in {p.part_id for p in child.parts}:
        raise _violation("anchor_part_changed", child.anchor_part)
    patient = parent.parts[0].motif.node(PATIENT_ID)
    for m in (p.motif for p in child.parts):
        if PATIENT_ID not in m.node_ids or m.node(PATIENT_ID) != patient:
            raise _violation("patient_node_changed", m.motif_id)
