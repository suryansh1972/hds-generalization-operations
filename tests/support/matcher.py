"""Independent reference patient matcher (D16, design §6): one-to-one, backtracking, closed world.

Imports only the data model, the bundle model and the hierarchy; it must not use the production
order/operator/lattice logic. Relations compare by equality; dates are parsed and compared as dates.
A node with observations needs one distinct patient fact per observation; a grouped (A3) node one per member,
its summary concept never consulted.
"""
from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Literal

from semgen.bundle import MotifBundle, MotifPart
from semgen.model import PATIENT_ID, Interval, Motif, Node
from semgen.snomed import Hierarchy


class UnknownBundleSemantics(Exception):
    """The bundle's Boolean meaning is unknown (semantics None) and no ``assume=`` was given."""


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


def _dates_hold(pattern: Mapping[str, str], fact: Mapping[str, str]) -> bool:
    """Every pattern date must equal the fact's date of the same name (compared as parsed dates)."""
    for name, d in pattern.items():
        if name not in fact or datetime.date.fromisoformat(fact[name]) != datetime.date.fromisoformat(d):
            return False
    return True


# A slot is one pattern requirement on one patient fact: (node, value or None, extra dates).
# A plain node is one slot; a node with observations is one slot per observation; a grouped node one per member.
Slot = tuple[Node, Interval | None, Mapping[str, str]]


def _slots(n: Node) -> list[Slot]:
    if n.members:   # A3: one slot per original member, under the grouped node's id (its edges); grouping unused
        return [s for m in n.members for s in _slots(m.model_copy(update={"id": n.id}))]
    if n.observations:
        return [(n, o.value, o.dates) for o in n.observations]
    return [(n, n.value, {})]


def _slot_ok(slot: Slot, fact: Node, h: Hierarchy) -> bool:
    pat, value, extra_dates = slot
    if pat.type != fact.type:
        return False
    if pat.role == "context":
        if pat.code != fact.code:
            return False
    elif pat.code is not None:
        if fact.code is None or not h.is_descendant_or_self(fact.code, pat.code):
            return False
    if value is not None:
        if fact.value is None or not _interval_holds_point(value, fact.value):
            return False
    for name, iv in pat.attrs.items():
        if name not in fact.attrs or not _interval_holds_point(iv, fact.attrs[name]):
            return False
    return _dates_hold(pat.dates, fact.dates) and _dates_hold(extra_dates, fact.dates)


def _edges_ok(pattern: Motif, patient: Motif, img: dict[str, list[str]]) -> bool:
    for pe in pattern.edges:
        if pe.s not in img or pe.t not in img:
            continue   # touches an absent node: handled by the closed-world check
        for fs in img[pe.s]:
            for ft in img[pe.t]:
                if not any(fe.s == fs and fe.t == ft and fe.rel == pe.rel and fe.prov == pe.prov
                           and (pe.window is None or (fe.window is not None
                                                      and _interval_holds_point(pe.window, fe.window)))
                           and _dates_hold(pe.dates, fe.dates)
                           for fe in patient.edges):
                    return False
    return True


def matches(pattern: Motif, patient: Motif, h: Hierarchy) -> bool:
    absent = [n for n in pattern.nodes if n.polarity == "absent"]
    for x in absent:
        if any(n.code is not None and h.is_descendant_or_self(n.code, x.code) for n in patient.nodes):
            return False
    present = sorted((n for n in pattern.nodes if n.polarity == "present"),
                     key=lambda n: (n.id != PATIENT_ID, n.id))
    slots = [s for n in present for s in _slots(n)]
    facts = sorted(patient.nodes, key=lambda n: n.id)

    def search(i: int, img: dict[str, list[str]], used: set[str]) -> bool:
        if i == len(slots):
            return _edges_ok(pattern, patient, img)
        slot = slots[i]
        nid = slot[0].id
        for f in facts:
            if f.id in used or not _slot_ok(slot, f, h):
                continue
            img.setdefault(nid, []).append(f.id)
            if search(i + 1, img, used | {f.id}):
                return True
            img[nid].pop()
            if not img[nid]:
                del img[nid]
        return False

    return search(0, {}, set())


def matches_part(part: MotifPart, patient: Motif, h: Hierarchy) -> bool:
    return matches(part.motif, patient, h)


def matches_bundle(bundle: MotifBundle, patient: Motif, h: Hierarchy,
                   assume: Literal["all", "any"] | None = None) -> bool:
    """Each part is matched independently (parts share only P). ``assume`` overrides the declared semantics;
    it exists for tests that must check a transition under both readings of an unknown-semantics bundle."""
    semantics = assume if assume is not None else bundle.semantics
    if semantics is None:
        raise UnknownBundleSemantics(f"bundle {bundle.bundle_id} has unknown semantics")
    results = (matches_part(p, patient, h) for p in bundle.parts)
    return all(results) if semantics == "all" else any(results)
