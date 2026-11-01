"""Independent reference patient matcher (D16): one-to-one, backtracking, closed world.

Imports only the data model; it must not use the production order/operator/lattice logic.
"""
from __future__ import annotations

from semgen.config import RelationHierarchy
from semgen.model import PATIENT_ID, Interval, Motif, Node
from semgen.snomed import Hierarchy


def _interval_holds_point(pattern_iv: Interval, fact_iv: Interval) -> bool:
    """Independent point-in-interval test (does not use the engine's Interval containment)."""
    assert fact_iv.lo == fact_iv.hi and fact_iv.lo is not None, f"patient value is not a point: {fact_iv}"
    if pattern_iv.unit != fact_iv.unit:
        return False
    x = fact_iv.lo
    if pattern_iv.lo is not None and (x < pattern_iv.lo or (x == pattern_iv.lo and not pattern_iv.lo_closed)):
        return False
    if pattern_iv.hi is not None and (x > pattern_iv.hi or (x == pattern_iv.hi and not pattern_iv.hi_closed)):
        return False
    return True


def _node_ok(pat: Node, fact: Node, h: Hierarchy) -> bool:
    if pat.type != fact.type:
        return False
    if pat.role == "context":
        if pat.code != fact.code:
            return False
    elif pat.code is not None:
        if fact.code is None or not h.is_descendant_or_self(fact.code, pat.code):
            return False
    if pat.value is not None:
        if fact.value is None or not _interval_holds_point(pat.value, fact.value):
            return False
    for name, iv in pat.attrs.items():
        if name not in fact.attrs or not _interval_holds_point(iv, fact.attrs[name]):
            return False
    return True


def _edges_ok(pattern: Motif, patient: Motif, img: dict[str, str], rel: RelationHierarchy) -> bool:
    for pe in pattern.edges:
        if pe.s not in img or pe.t not in img:
            continue   # touches an absent node: handled by the closed-world check
        ok = False
        for fe in patient.edges:
            if fe.s != img[pe.s] or fe.t != img[pe.t]:
                continue
            if not rel.leq(fe.rel, pe.rel) or fe.prov != pe.prov:
                continue
            if pe.window is not None and (fe.window is None or not _interval_holds_point(pe.window, fe.window)):
                continue
            ok = True
            break
        if not ok:
            return False
    return True


def matches(pattern: Motif, patient: Motif, h: Hierarchy, rel: RelationHierarchy) -> bool:
    absent = [n for n in pattern.nodes if n.polarity == "absent"]
    for x in absent:
        if any(n.code is not None and h.is_descendant_or_self(n.code, x.code) for n in patient.nodes):
            return False
    present = sorted((n for n in pattern.nodes if n.polarity == "present"),
                     key=lambda n: (n.id != PATIENT_ID, n.id))
    facts = sorted(patient.nodes, key=lambda n: n.id)

    def search(i: int, img: dict[str, str]) -> bool:
        if i == len(present):
            return _edges_ok(pattern, patient, img, rel)
        pn = present[i]
        used = set(img.values())
        for f in facts:
            if f.id in used or not _node_ok(pn, f, h):
                continue
            img[pn.id] = f.id
            if search(i + 1, img):
                return True
            del img[pn.id]
        return False

    return search(0, {})
