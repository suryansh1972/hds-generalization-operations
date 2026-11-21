"""Patient matching for the containment checker (spec §1): the semantics of the reference oracle, for production.

A pattern's present nodes contribute slots (a plain node one, an A1 node one per observation, an A3 node one per
member, under the node's own id); slots map one-to-one onto patient facts. A patient graph has exactly one
Patient fact, its node ``P``: a pattern's ``P`` node maps to it and nothing else does (shared patient identity:
every part of a bundle is matched at the same Patient fact). Only ``semgen.containment`` uses it, to
evaluate a pattern on a ground instance; the tests cross-check it against the independent oracle.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from semgen.model import PATIENT_ID, Interval, Motif, Node
from semgen.snomed import Hierarchy


@dataclass(frozen=True)
class Slot:
    """One requirement on one patient fact. ``dates`` is None when the node's and observation's dates disagree."""

    node: str
    type: str
    role: str
    code: str | None
    value: Interval | None
    attrs: Mapping[str, Interval]
    dates: Mapping[str, str] | None


def merge_dates(a: Mapping[str, str], b: Mapping[str, str]) -> dict[str, str] | None:
    out = dict(a)
    for k, v in b.items():
        if out.setdefault(k, v) != v:
            return None
    return out


def slots(m: Motif) -> list[Slot]:
    """The slots of ``m``'s present nodes, ``P`` first, then by node id."""
    def of(n: Node, nid: str) -> list[Slot]:
        if n.members:
            return [s for x in n.members for s in of(x, nid)]
        if n.observations:
            return [Slot(nid, n.type, n.role, n.code, o.value, n.attrs, merge_dates(n.dates, o.dates))
                    for o in n.observations]
        return [Slot(nid, n.type, n.role, n.code, n.value, n.attrs, dict(n.dates))]

    present = sorted((n for n in m.nodes if n.polarity == "present"), key=lambda n: (n.id != PATIENT_ID, n.id))
    return [s for n in present for s in of(n, n.id)]


def holds(iv: Interval, point: Interval | None) -> bool:
    """``iv`` holds the point ``point`` (same unit)."""
    return point is not None and point.unit == iv.unit and point.lo is not None and iv.contains_point(point.lo)


def _dates_hold(pattern: Mapping[str, str], fact: Mapping[str, str]) -> bool:
    return all(fact.get(k) == v for k, v in pattern.items())


def slot_accepts(s: Slot, fact: Node, h: Hierarchy) -> bool:
    if s.dates is None or s.type != fact.type:
        return False
    if s.role == "context":
        if s.code != fact.code:
            return False
    elif s.code is not None and (fact.code is None or not h.is_descendant_or_self(fact.code, s.code)):
        return False
    if s.value is not None and not holds(s.value, fact.value):
        return False
    if any(not holds(iv, fact.attrs.get(k)) for k, iv in s.attrs.items()):
        return False
    return _dates_hold(s.dates, fact.dates)


def violates_absent(pattern: Motif, patient: Motif, h: Hierarchy) -> bool:
    """Some patient fact lies at or below one of ``pattern``'s absent codes (closed world)."""
    absent = [n.code for n in pattern.nodes if n.polarity == "absent"]
    return any(f.code is not None and h.is_descendant_or_self(f.code, x) for x in absent for f in patient.nodes)


def check_patient(patient: Motif) -> None:
    """A patient graph has exactly one Patient fact: its node ``P``, whose type no other node has."""
    ps = [n for n in patient.nodes if n.id == PATIENT_ID]
    if len(ps) != 1 or any(n.type == ps[0].type for n in patient.nodes if n.id != PATIENT_ID):
        raise ValueError(f"patient graph {patient.motif_id} does not have exactly one Patient fact")


def matches(pattern: Motif, patient: Motif, h: Hierarchy) -> bool:
    check_patient(patient)
    if violates_absent(pattern, patient, h):
        return False
    ss = slots(pattern)
    facts = sorted(patient.nodes, key=lambda n: n.id)
    present = {n.id for n in pattern.nodes if n.polarity == "present"}
    edges = [e for e in pattern.edges if e.s in present and e.t in present]
    by_key: dict[tuple[str, str], list] = {}
    for fe in patient.edges:
        by_key.setdefault((fe.s, fe.t), []).append(fe)

    def edge_ok(pe, fs: str, ft: str) -> bool:
        return any(fe.rel == pe.rel and fe.prov == pe.prov and _dates_hold(pe.dates, fe.dates)
                   and (pe.window is None or holds(pe.window, fe.window)) for fe in by_key.get((fs, ft), ()))

    img: dict[str, list[str]] = {}

    def consistent(nid: str, fid: str) -> bool:
        """Every pattern edge at ``nid`` holds between the new image ``fid`` and every image placed so far."""
        for pe in edges:
            if pe.s == nid and not all(edge_ok(pe, fid, t) for t in img.get(pe.t, ())):
                return False
            if pe.t == nid and not all(edge_ok(pe, s, fid) for s in img.get(pe.s, ())):
                return False
            if pe.s == nid == pe.t and not edge_ok(pe, fid, fid):
                return False
        return True

    def search(i: int, used: set[str]) -> bool:
        if i == len(ss):
            return True
        s = ss[i]
        for f in facts:
            if (f.id == PATIENT_ID) != (s.node == PATIENT_ID):   # P maps to the Patient fact, nothing else does
                continue
            if f.id in used or not slot_accepts(s, f, h) or not consistent(s.node, f.id):
                continue
            img.setdefault(s.node, []).append(f.id)
            if search(i + 1, used | {f.id}):
                return True
            img[s.node].pop()
        return False

    return search(0, set())
