"""Deterministic canonical JSON and short hash for motifs."""
from __future__ import annotations

import hashlib
import json
import math

from .model import Edge, Interval, Motif, Node


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


def _node(n: Node) -> dict:
    return {"id": n.id, "type": n.type, "role": n.role, "code": n.code,
            "polarity": n.polarity, "value": _interval(n.value),
            "attrs": {k: _interval(v) for k, v in n.attrs.items()}}


def _edge(e: Edge) -> dict:
    return {"s": e.s, "t": e.t, "rel": e.rel, "prov": e.prov,
            "window": _interval(e.window), "bpn_score": _num(e.bpn_score)}


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
