"""Motif JSON loader with structural validation and exact active-FSN resolution.

File shape accepted by ``load_motifs``: either a top-level JSON list of motif
objects, or an object ``{"_comment": ..., "motifs": [...]}`` (``_comment`` is
ignored).

Input conventions: ``value`` and ``attrs`` entries are
``{"interval": [lo, hi], "unit": u}``; edge ``time`` is
``{"window": [lo, hi], "unit": "d"}``. All become closed ``Interval``s
(a ``null`` bound is unbounded). Null node codes are resolved from the label
by exact active-FSN match; non-null codes are kept verbatim.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from semgen.model import PATIENT_ID, Edge, Interval, Motif, Node
from semgen.snomed import FsnError, Hierarchy

AGE_CAP = 90.0
_MOTIF_KEYS = {"motif_id", "anchor", "nodes", "edges"}
_NODE_KEYS = {"id", "type", "role", "label", "code", "polarity", "value", "attrs"}
_EDGE_KEYS = {"s", "t", "rel", "prov", "time", "bpn_score"}


class MotifError(Exception):
    """Invalid motif file or motif structure."""


def _check_keys(d: Any, allowed: set[str], what: str, mid: str) -> None:
    if not isinstance(d, dict):
        raise MotifError(f"motif {mid}: {what} must be an object, got {type(d).__name__}")
    extra = set(d) - allowed
    if extra:
        raise MotifError(f"motif {mid}: {what} has unknown field(s) {sorted(extra)}")


def _interval(spec: Any, key: str, unit_default: str | None, what: str, mid: str) -> Interval:
    _check_keys(spec, {key, "unit"}, what, mid)
    pair = spec.get(key)
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        raise MotifError(f"motif {mid}: {what} needs '{key}': [lo, hi]")
    try:
        return Interval(lo=pair[0], hi=pair[1], lo_closed=True, hi_closed=True, unit=spec.get("unit"))
    except ValidationError as e:
        raise MotifError(f"motif {mid}: {what}: {e}") from e


def _build_node(rn: Any, mid: str) -> Node:
    nid = rn.get("id", "?") if isinstance(rn, dict) else "?"
    _check_keys(rn, _NODE_KEYS, f"node {nid}", mid)
    d = {k: v for k, v in rn.items() if k not in ("value", "attrs")}
    if rn.get("value") is not None:
        d["value"] = _interval(rn["value"], "interval", None, f"node {nid} value", mid)
    attrs = rn.get("attrs") or {}
    if not isinstance(attrs, dict):
        raise MotifError(f"motif {mid}: node {nid} attrs must be an object")
    d["attrs"] = {k: _interval(v, "interval", None, f"node {nid} attr {k!r}", mid) for k, v in attrs.items()}
    try:
        return Node.model_validate(d)
    except ValidationError as e:
        raise MotifError(f"motif {mid}: node {nid}: {e}") from e


def _build_edge(re_: Any, mid: str) -> Edge:
    name = f"{re_.get('s', '?')}->{re_.get('t', '?')}" if isinstance(re_, dict) else "?"
    _check_keys(re_, _EDGE_KEYS, f"edge {name}", mid)
    d = {k: v for k, v in re_.items() if k != "time"}
    if re_.get("time") is not None:
        w = _interval(re_["time"], "window", None, f"edge {name} time", mid)
        if w.unit != "d":
            raise MotifError(f"motif {mid}: edge {name} time window unit must be 'd', got {w.unit!r}")
        if w.lo is None or w.lo < 0:
            raise MotifError(
                f"motif {mid}: edge {name} time window has a negative or unbounded lower bound "
                f"({w.lo}); negative lower bounds are rejected, use [0, hi]")
        d["window"] = w
    try:
        return Edge.model_validate(d)
    except ValidationError as e:
        raise MotifError(f"motif {mid}: edge {name}: {e}") from e


def parse_motif(raw: dict, h: Hierarchy | None) -> Motif:
    """Validate and build a Motif. With ``h=None`` every code must already be set."""
    if not isinstance(raw, dict):
        raise MotifError(f"motif must be an object, got {type(raw).__name__}")
    mid = str(raw.get("motif_id", "?"))
    _check_keys(raw, _MOTIF_KEYS, "motif", mid)
    for k in ("motif_id", "anchor", "nodes", "edges"):
        if k not in raw:
            raise MotifError(f"motif {mid}: missing field {k!r}")
    if not isinstance(raw["nodes"], list) or not isinstance(raw["edges"], list):
        raise MotifError(f"motif {mid}: 'nodes' and 'edges' must be lists")
    nodes = [_build_node(n, mid) for n in raw["nodes"]]
    edges = [_build_edge(e, mid) for e in raw["edges"]]
    ids = [n.id for n in nodes]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise MotifError(f"motif {mid}: duplicate node id(s) {dup}")
    idset = set(ids)

    # 1. unknown edge endpoints
    for e in edges:
        for end in (e.s, e.t):
            if end not in idset:
                raise MotifError(f"motif {mid}: edge {e.s}->{e.t} references unknown node {end!r}")
    # 2. anchor exists
    anchor = raw["anchor"]
    if anchor not in idset:
        raise MotifError(f"motif {mid}: anchor {anchor!r} is not a node of the motif")
    # 3. anchor linked to patient
    if not any(e.s == PATIENT_ID and e.t == anchor for e in edges):
        raise MotifError(f"motif {mid}: anchor {anchor!r} has no edge from patient {PATIENT_ID!r}")
    # 4. parallel edges
    seen: set[tuple[str, str]] = set()
    for e in edges:
        if e.key in seen:
            raise MotifError(f"motif {mid}: parallel edges for ordered pair {e.s}->{e.t}")
        seen.add(e.key)
    # 5. absent nodes: exactly one incident edge, from the patient
    for n in nodes:
        if n.polarity != "absent":
            continue
        if n.value is not None or n.attrs:
            raise MotifError(
                f"motif {mid}: absent node {n.id!r} must not carry value or attrs (absent is code-only, D11)")
        inc = [e for e in edges if n.id in (e.s, e.t)]
        if len(inc) != 1 or inc[0].s != PATIENT_ID or inc[0].t != n.id:
            raise MotifError(
                f"motif {mid}: absent node {n.id!r} must be a leaf attached only by a "
                f"{PATIENT_ID}->{n.id} edge (found {[f'{e.s}->{e.t}' for e in inc]})")
    # 6. age_at_dx cap
    for n in nodes:
        iv = n.attrs.get("age_at_dx")
        if iv is not None and iv.hi is not None and iv.lo is not None and iv.lo >= AGE_CAP:
            raise MotifError(
                f"motif {mid}: node {n.id!r} age_at_dx [{iv.lo}, {iv.hi}] is at or above 90; "
                f"ages of 90 and over must be written [90, null]")
    # 7. resolve null codes by exact active FSN
    resolved: list[Node] = []
    for n in nodes:
        if n.code is None and n.id != PATIENT_ID:
            if n.label is None:
                raise MotifError(f"motif {mid}: node {n.id!r} has no code and no label to resolve")
            if h is None:
                raise MotifError(
                    f"motif {mid}: node {n.id!r} has null code (label {n.label!r}) but no hierarchy was given")
            try:
                n = n.model_copy(update={"code": h.resolve_fsn(n.label)})
            except FsnError as e:
                raise MotifError(f"motif {mid}: node {n.id!r} label {n.label!r}: {e}") from e
        resolved.append(n)
    try:
        return Motif(motif_id=raw["motif_id"], anchor=anchor, nodes=tuple(resolved), edges=tuple(edges))
    except ValidationError as e:
        raise MotifError(f"motif {mid}: {e}") from e


def load_motifs(path: str | Path, h: Hierarchy | None) -> list[Motif]:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise MotifError(f"motif file not found: {p}") from e
    except (OSError, json.JSONDecodeError) as e:
        raise MotifError(f"cannot read motif file {p}: {e}") from e
    if isinstance(data, dict):
        if "motifs" not in data:
            raise MotifError(f"{p}: top-level object needs a 'motifs' list")
        data = data["motifs"]
    if not isinstance(data, list):
        raise MotifError(f"{p}: expected a list of motifs")
    return [parse_motif(m, h) for m in data]
