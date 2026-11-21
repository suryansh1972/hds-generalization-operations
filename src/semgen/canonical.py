"""Deterministic canonical JSON and short hash for motifs."""
from __future__ import annotations

import hashlib
import json
import math

from .model import Edge, Interval, Motif, Node, Observation, ReferenceRange, TestIdentity


def _num(x: float | int | None) -> float | None:
    """Single numeric path: float, -0.0 -> 0.0, reject NaN/inf (unbounded is None)."""
    if x is None:
        return None
    f = float(x)
    if not math.isfinite(f):
        raise ValueError(f"non-finite number not allowed in canonical form: {x!r}")
    return 0.0 if f == 0.0 else f


def _interval(iv: Interval | None) -> dict | None:
    if iv is None:
        return None
    return {"lo": _num(iv.lo), "hi": _num(iv.hi), "lo_closed": iv.lo_closed,
            "hi_closed": iv.hi_closed, "unit": iv.unit}


def _test(t: TestIdentity) -> dict:
    return {"system": t.system, "code": t.code, "method": t.method, "specimen": t.specimen}


def _reference_range(r: ReferenceRange) -> dict:
    a = r.applies_to
    return {"interval": _interval(r.interval), "kind": r.kind, "test": _test(r.test),
            "applies_to": {"sex": a.sex, "age_min_days": a.age_min_days, "age_max_days": a.age_max_days},
            "source": r.source, "source_ref": r.source_ref}


def _observation(o: Observation) -> dict:
    out = {"value": _interval(o.value), "dates": dict(o.dates), "source_node": o.source_node,
           "source_record": o.source_record}
    if o.reference_range is not None:   # labels are excluded, as for nodes
        out["reference_range"] = _reference_range(o.reference_range)
    return out


def _node(n: Node) -> dict:
    out = {"id": n.id, "type": n.type, "role": n.role, "code": n.code,
           "polarity": n.polarity, "value": _interval(n.value),
           "attrs": {k: _interval(v) for k, v in n.attrs.items()}}
    # Newer fields appear only when set, so every motif without them keeps its canonical form and hash.
    if n.dates:
        out["dates"] = dict(n.dates)
    if n.test is not None:
        out["test"] = _test(n.test)
    if n.reference_range is not None:
        out["reference_range"] = _reference_range(n.reference_range)
    if n.observations:
        out["observations"] = [_observation(o) for o in n.observations]   # order kept: A1 writes id order
    if n.members:
        g = n.grouping
        out["members"] = [_node(m) for m in n.members]                    # sorted by id (model invariant)
        out["grouping"] = {"kind": g.kind, "system": g.system, "code": g.code, "version": g.version,
                           "source": g.source}
    return out


def _edge(e: Edge) -> dict:
    out = {"s": e.s, "t": e.t, "rel": e.rel, "prov": e.prov,
           "window": _interval(e.window), "bpn_score": _num(e.bpn_score)}
    if e.dates:
        out["dates"] = dict(e.dates)
    return out


def canonical_json(m: Motif) -> str:
    """Structure-only canonical JSON: excludes motif_id and node labels; order-independent."""
    obj = {
        "anchor": m.anchor,
        "nodes": [_node(n) for n in sorted(m.nodes, key=lambda n: n.id)],
        "edges": [_edge(e) for e in sorted(m.edges, key=lambda e: (e.s, e.t, e.rel))],
    }
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def motif_hash(m: Motif) -> str:
    return hashlib.sha256(canonical_json(m).encode("utf-8")).hexdigest()[:16]



def _dump(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def node_descriptor(n: Node) -> str:
    """The node's canonical JSON without its id, or its group members' ids (labels are excluded, as in
    ``canonical_json``): node ids are namespaced per bundle part, so equal groups differ only in them."""
    d = _node(n)
    del d["id"]
    for m in d.get("members", []):
        del m["id"]
    return _dump(d)


def edge_descriptor(e: Edge) -> str:
    """The edge's canonical JSON without its endpoints."""
    d = _edge(e)
    del d["s"], d["t"]
    return _dump(d)


def structural_signature(m: Motif) -> str:
    """Id-free summary: sorted node descriptors, and edge descriptors with endpoints given by node descriptor.

    The anchor's descriptor is included as well (``find_isomorphism`` maps anchor to anchor). A filter only: motifs
    equal up to node ids have equal signatures, but equal signatures prove nothing.
    """
    desc = {n.id: node_descriptor(n) for n in m.nodes}
    edges = sorted(_dump([desc[e.s], desc[e.t], edge_descriptor(e)]) for e in m.edges)
    return _dump({"anchor": desc.get(m.anchor), "nodes": sorted(desc.values()), "edges": edges})
