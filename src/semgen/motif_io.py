"""Motif and bundle JSON loader with structural validation and exact active-FSN resolution.

File shape accepted by ``load_motifs``: either a top-level JSON list of motif
objects, or an object ``{"_comment": ..., "motifs": [...]}`` (``_comment`` is
ignored). ``load_bundles`` accepts the same (each motif becomes a bundle of one)
or ``{"bundles": [{"bundle_id", "semantics"?, "anchor_motif"?, "subject"?, "motifs": [...]}]}``.

Input conventions: ``value`` and ``attrs`` entries are
``{"interval": [lo, hi], "unit": u}``; edge ``time`` is
``{"window": [lo, hi], "unit": "d"}``; a node ``reference_range`` is
``{"interval": [lo, hi], "unit": u, "kind", "test", "applies_to"?, "source", "source_ref"}``.
All become closed ``Interval``s (a ``null`` bound is unbounded). Node and edge
``dates`` map a name to an ISO 8601 date ``YYYY-MM-DD``; a node ``test`` is
``{"system", "code", "method"?, "specimen"?}``. Null node codes are resolved from the label
by exact active-FSN match; non-null codes are kept verbatim.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from semgen.bundle import CohortDefinition, MotifBundle, MotifPart, Subject
from semgen.model import (
    PATIENT_ID,
    AppliesTo,
    Edge,
    Interval,
    Motif,
    Node,
    ReferenceRange,
    TestIdentity,
    check_iso_date,
)
from semgen.snomed import FsnError, Hierarchy

AGE_CAP = 90.0
_MOTIF_KEYS = {"motif_id", "anchor", "nodes", "edges"}
_NODE_KEYS = {"id", "type", "role", "label", "code", "polarity", "value", "attrs", "dates", "test", "reference_range"}
_EDGE_KEYS = {"s", "t", "rel", "prov", "time", "bpn_score", "dates"}
_TEST_KEYS = {"system", "code", "method", "specimen"}
_RANGE_KEYS = {"interval", "unit", "kind", "test", "applies_to", "source", "source_ref"}
_APPLIES_KEYS = {"sex", "age_min_days", "age_max_days"}
_BUNDLE_KEYS = {"bundle_id", "semantics", "anchor_motif", "subject", "cohort_definition", "motifs"}
_COHORT_KEYS = {"id", "version", "source", "constraints"}
_CONSTRAINT_KEYS = {"motif", "target", "field", "necessity"}
_SUBJECT_KEYS = {"sex", "age_days"}


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


def _dates(raw: Any, what: str, mid: str) -> dict[str, str]:
    """Every date is checked here so the error names the field; the model re-checks as a second line."""
    if not isinstance(raw, dict):
        raise MotifError(f"motif {mid}: {what} dates must be an object")
    for k, v in raw.items():
        if (why := check_iso_date(v)) is not None:
            raise MotifError(f"motif {mid}: {what} dates[{k!r}]: {why}")
    return dict(raw)


def _model(cls, raw: Any, keys: set[str], what: str, mid: str):
    _check_keys(raw, keys, what, mid)
    try:
        return cls.model_validate(raw)
    except ValidationError as e:
        raise MotifError(f"motif {mid}: {what}: {e}") from e


def _reference_range(raw: Any, nid: str, mid: str) -> ReferenceRange:
    what = f"node {nid} reference_range"
    _check_keys(raw, _RANGE_KEYS, what, mid)
    missing = sorted(_RANGE_KEYS - {"applies_to"} - set(raw))
    if missing:
        raise MotifError(f"motif {mid}: {what} is missing {missing}")
    d = {k: raw[k] for k in ("kind", "source", "source_ref")}
    d["interval"] = _interval({"interval": raw["interval"], "unit": raw["unit"]}, "interval", None, what, mid)
    d["test"] = _model(TestIdentity, raw["test"], _TEST_KEYS, f"{what} test", mid)
    d["applies_to"] = _model(AppliesTo, raw.get("applies_to") or {}, _APPLIES_KEYS, f"{what} applies_to", mid)
    for k in ("source", "source_ref"):
        if not isinstance(d[k], str) or not d[k]:
            raise MotifError(f"motif {mid}: {what} {k} must be a non-empty string")
    return _model(ReferenceRange, d, set(d), what, mid)


def _build_node(rn: Any, mid: str) -> Node:
    nid = rn.get("id", "?") if isinstance(rn, dict) else "?"
    _check_keys(rn, _NODE_KEYS, f"node {nid}", mid)
    d = {k: v for k, v in rn.items() if k not in ("value", "attrs", "dates", "test", "reference_range")}
    if rn.get("dates") is not None:
        d["dates"] = _dates(rn["dates"], f"node {nid}", mid)
    if rn.get("test") is not None:
        d["test"] = _model(TestIdentity, rn["test"], _TEST_KEYS, f"node {nid} test", mid)
    if rn.get("reference_range") is not None:
        d["reference_range"] = _reference_range(rn["reference_range"], nid, mid)
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
    d = {k: v for k, v in re_.items() if k not in ("time", "dates")}
    if re_.get("dates") is not None:
        d["dates"] = _dates(re_["dates"], f"edge {name}", mid)
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
        if n.value is not None or n.attrs or n.dates or n.test is not None or n.reference_range is not None:
            raise MotifError(
                f"motif {mid}: absent node {n.id!r} must not carry value, attrs, dates, test or reference_range "
                f"(absent is code-only, D11)")
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


def _namespaced(m: Motif) -> Motif:
    """Prefix every non-patient node id with ``<motif_id>.``, rewriting edge endpoints and the anchor."""
    def ns(i: str) -> str:
        return i if i == PATIENT_ID else f"{m.motif_id}.{i}"
    return m.model_copy(update={
        "anchor": ns(m.anchor),
        "nodes": tuple(n.model_copy(update={"id": ns(n.id)}) for n in m.nodes),
        "edges": tuple(e.model_copy(update={"s": ns(e.s), "t": ns(e.t)}) for e in m.edges)})


def _cohort(raw: Any, bid: str, ids: list[str], multi: bool) -> CohortDefinition | None:
    """``cohort_definition`` (design §5.2 rev 4). Constraint targets name a motif's own ids; with more than one
    motif, ``motif`` is required and the target is namespaced like the nodes (``<motif>.<id>``, ``P`` kept)."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) - _COHORT_KEYS:
        raise MotifError(f"bundle {bid}: cohort_definition must be an object with only {sorted(_COHORT_KEYS)}")
    out = []
    for c in raw.get("constraints") or []:
        if not isinstance(c, dict) or set(c) - _CONSTRAINT_KEYS:
            raise MotifError(f"bundle {bid}: cohort constraint must have only {sorted(_CONSTRAINT_KEYS)}")
        mid = c.get("motif")
        if multi and mid not in ids:
            raise MotifError(f"bundle {bid}: cohort constraint needs 'motif' naming one of {ids}")

        def ns(i: str) -> str:
            return i if not multi or i == PATIENT_ID else f"{mid}.{i}"
        t = str(c.get("target", ""))
        target = "->".join(ns(x) for x in t.split("->")) if "->" in t else ns(t)
        out.append({"target": target, "field": c.get("field"), "necessity": c.get("necessity")})
    try:
        return CohortDefinition.model_validate({**{k: raw.get(k) for k in ("id", "version", "source")},
                                                "constraints": out})
    except ValidationError as e:
        raise MotifError(f"bundle {bid}: cohort_definition: {e}") from e


def parse_bundle(raw: dict, h: Hierarchy | None) -> MotifBundle:
    """Validate and build a bundle; with more than one motif, non-patient node ids are namespaced."""
    if not isinstance(raw, dict):
        raise MotifError(f"bundle must be an object, got {type(raw).__name__}")
    bid = str(raw.get("bundle_id", "?"))
    extra = set(raw) - _BUNDLE_KEYS
    if extra:
        raise MotifError(f"bundle {bid}: unknown field(s) {sorted(extra)}")
    if not isinstance(raw.get("bundle_id"), str) or not raw["bundle_id"]:
        raise MotifError(f"bundle {bid}: 'bundle_id' must be a non-empty string")
    if not isinstance(raw.get("motifs"), list) or not raw["motifs"]:
        raise MotifError(f"bundle {bid}: 'motifs' must be a non-empty list")
    motifs = [parse_motif(m, h) for m in raw["motifs"]]
    ids = [m.motif_id for m in motifs]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise MotifError(f"bundle {bid}: duplicate motif id(s) {dup}")
    semantics = raw.get("semantics")
    if semantics not in ("all", "any", None):
        raise MotifError(f"bundle {bid}: semantics {semantics!r} must be 'all', 'any' or absent")
    anchor = raw.get("anchor_motif")
    if len(motifs) > 1:
        if anchor is None:
            raise MotifError(f"bundle {bid}: 'anchor_motif' is required when the bundle has more than one motif")
    elif semantics is None:
        semantics = "all"   # a bundle of one: both readings coincide (D4); otherwise missing means unknown
    if anchor is None:
        anchor = ids[0]
    if anchor not in ids:
        raise MotifError(f"bundle {bid}: anchor_motif {anchor!r} is not one of its motifs {ids}")
    patients = {m.motif_id: m.node(PATIENT_ID) for m in motifs if PATIENT_ID in m.node_ids}
    if len(patients) != len(motifs) or len(set(patients.values())) != 1:
        raise MotifError(f"bundle {bid}: every motif must contain the same patient node {PATIENT_ID!r} "
                         f"(found {sorted(patients)} of {ids})")
    if len(motifs) > 1:
        motifs = [_namespaced(m) for m in motifs]
        non_p = [i for m in motifs for i in m.node_ids if i != PATIENT_ID]
        clash = sorted({i for i in non_p if non_p.count(i) > 1})
        if clash:
            raise MotifError(f"bundle {bid}: namespaced node ids collide: {clash}")
    subject = None
    if raw.get("subject") is not None:
        s = raw["subject"]
        if not isinstance(s, dict) or set(s) - _SUBJECT_KEYS:
            raise MotifError(f"bundle {bid}: subject must be an object with only {sorted(_SUBJECT_KEYS)}")
        try:
            subject = Subject.model_validate(s)
        except ValidationError as e:
            raise MotifError(f"bundle {bid}: subject: {e}") from e
    cohort = _cohort(raw.get("cohort_definition"), bid, ids, multi=len(motifs) > 1)
    try:
        return MotifBundle(bundle_id=raw["bundle_id"], semantics=semantics, anchor_part=anchor, subject=subject,
                           cohort=cohort,
                           parts=tuple(MotifPart(part_id=m.motif_id, motif=m) for m in motifs))
    except ValidationError as e:
        raise MotifError(f"bundle {bid}: {e}") from e


def _read(path: str | Path) -> tuple[Path, Any]:
    p = Path(path)
    try:
        return p, json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise MotifError(f"motif file not found: {p}") from e
    except (OSError, json.JSONDecodeError) as e:
        raise MotifError(f"cannot read motif file {p}: {e}") from e


def _motif_list(p: Path | str, data: Any) -> list:
    if isinstance(data, dict):
        if "motifs" not in data:
            raise MotifError(f"{p}: top-level object needs a 'motifs' list")
        data = data["motifs"]
    if not isinstance(data, list):
        raise MotifError(f"{p}: expected a list of motifs")
    return data


def load_motifs(path: str | Path, h: Hierarchy | None) -> list[Motif]:
    p, data = _read(path)
    return [parse_motif(m, h) for m in _motif_list(p, data)]


def bundles_from_data(data: Any, h: Hierarchy | None, source: str = "input") -> list[MotifBundle]:
    """Bundles from parsed JSON: ``{"bundles": [...]}``, a motif list or ``{"motifs": [...]}`` (each motif a bundle
    of one), or a single bundle (``bundle_id``) or motif (``motif_id``) object. ``source`` names the input in errors."""
    if isinstance(data, dict) and "bundle_id" in data:
        data = {"bundles": [data]}
    elif isinstance(data, dict) and "motif_id" in data:
        data = [data]
    if isinstance(data, dict) and "bundles" in data:
        if "motifs" in data:
            raise MotifError(f"{source}: a file has either 'bundles' or 'motifs', not both")
        if not isinstance(data["bundles"], list):
            raise MotifError(f"{source}: 'bundles' must be a list")
        bundles = [parse_bundle(b, h) for b in data["bundles"]]
    else:
        bundles = [MotifBundle.of(parse_motif(m, h)) for m in _motif_list(source, data)]
    # Ids are output directory names: ids equal after casefold() would share one directory on a case-insensitive
    # filesystem, so they count as duplicates too. Motif-list files share this check (bundle id = motif id).
    folded = [b.bundle_id.casefold() for b in bundles]
    dup = sorted({b.bundle_id for b, f in zip(bundles, folded) if folded.count(f) > 1})
    if dup:
        raise MotifError(f"{source}: duplicate bundle id(s) {dup} (compared case-insensitively)")
    return bundles


def load_bundles(path: str | Path, h: Hierarchy | None) -> list[MotifBundle]:
    """A ``{"bundles": [...]}`` file, or a motif-list file whose motifs each become a bundle of one."""
    p, data = _read(path)
    return bundles_from_data(data, h, str(p))
