"""Exact decision of ``∧ S ⇒ ∨ T`` over motifs (spec §3): every patient matching all sources matches some target.

The sources' finite set of hardest patients (instances) is enumerated: every way of placing source slots on facts
(slots of different sources may share one; every source's ``P`` is the one Patient fact), per fact one code of each minimal profile against the targets, per
interval one point of each cell of the endpoints of S and T, and one patient edge per source edge. Each instance is evaluated with ``semgen.matching``. Containment ``N ⊑ B`` is ``decide([N], [B], h)``.

``VALID`` means proven for every patient (vacuously when no instance exists), ``INVALID`` carries a counterexample the
matcher has confirmed, ``UNKNOWN`` means not decided (inactive or unknown compared codes, an absent node without a
code, an uncoded source slot against an uncoded context target slot of the same type, or the optional ``limit``
on instances reached).
"""
from __future__ import annotations

import itertools
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from semgen.matching import Slot, matches, merge_dates, slots
from semgen.model import PATIENT_ID, Edge, Interval, Motif, Node
from semgen.snomed import Hierarchy


@dataclass(frozen=True)
class Verdict:
    status: Literal["VALID", "INVALID", "UNKNOWN"]
    reason: str
    evidence: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "VALID"


class _Limit(Exception):
    pass


# --- intervals and cells -------------------------------------------------------------------------------------------

_EMPTY = object()


def meet(a: Interval | None, b: Interval | None):
    """The intersection of two intervals (None = unconstrained), or ``_EMPTY``."""
    if a is None or b is None:
        return b if a is None else a
    if a.unit != b.unit:
        return _EMPTY
    lo, lo_c = max((a.lo, a.lo_closed), (b.lo, b.lo_closed), key=lambda x: (-float("inf") if x[0] is None else x[0],
                                                                              not x[1]))
    hi, hi_c = min((a.hi, a.hi_closed), (b.hi, b.hi_closed), key=lambda x: (float("inf") if x[0] is None else x[0],
                                                                             x[1]))
    if lo is not None and hi is not None and (lo > hi or (lo == hi and not (lo_c and hi_c))):
        return _EMPTY
    return Interval(lo=lo, hi=hi, lo_closed=lo_c, hi_closed=hi_c, unit=a.unit)


def representatives(iv: Interval, endpoints: Sequence[float]) -> list[float]:
    """One point of every cell of ``iv``: the line cut at ``endpoints`` (each endpoint a cell, each gap a cell)."""
    pts = sorted(set(endpoints))
    if not pts:
        cands = [0.0]
    else:
        cands = pts + [(x + y) / 2 for x, y in itertools.pairwise(pts)] + [pts[0] - 1, pts[-1] + 1]
    return sorted(x for x in cands if iv.contains_point(x))


def _intervals(m: Motif) -> Iterator[Interval]:
    for s in slots(m):
        if s.value is not None:
            yield s.value
        yield from s.attrs.values()
    yield from (e.window for e in m.edges if e.window is not None)


# --- facts and edges of an instance ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Fact:
    type: str
    role: str
    context: frozenset[str]
    codes: frozenset[str]          # non-context codes the fact must lie at or below
    value: Interval | None
    attrs: Mapping[str, Interval]
    dates: Mapping[str, str]


def _fact(group: Sequence[tuple[int, Slot]]) -> _Fact | None:
    """The fact that serves every slot of ``group``, or None if no single fact can."""
    first = group[0][1]
    context: set[str] = set()
    codes: set[str] = set()
    value, attrs, dates = None, {}, {}
    for _, s in group:
        if s.type != first.type or s.dates is None:
            return None
        if s.code is not None:
            (context if s.role == "context" else codes).add(s.code)
        elif s.role == "context":
            context.add("")   # an uncoded context slot needs an uncoded fact
        value = meet(value, s.value)
        dates = merge_dates(dates, s.dates)
        if value is _EMPTY or dates is None:
            return None
        for k, iv in s.attrs.items():
            attrs[k] = meet(attrs.get(k), iv)
            if attrs[k] is _EMPTY:
                return None
    if len(context) > 1 or ("" in context and codes):
        return None
    return _Fact(first.type, first.role, frozenset(context), frozenset(codes), value, attrs, dates)


@dataclass(frozen=True)
class _EdgeReq:
    """One patient edge required by a source edge (between the facts of its endpoints' slots)."""

    s: int
    t: int
    rel: str
    prov: str
    window: Interval | None
    dates: tuple[tuple[str, str], ...]


def partitions(items: Sequence, can_join: Callable[[list, object], bool]) -> Iterator[list[list]]:
    """Every partition of ``items`` in which each item joins an earlier block only if ``can_join``; the partition
    into singletons comes first."""
    blocks: list[list] = []

    def go(i: int) -> Iterator[list[list]]:
        if i == len(items):
            yield [list(b) for b in blocks]
            return
        x = items[i]
        blocks.append([x])
        yield from go(i + 1)
        blocks.pop()
        for b in blocks:
            if can_join(b, x):
                b.append(x)
                yield from go(i + 1)
                b.pop()

    yield from go(0)


# --- codes ----------------------------------------------------------------------------------------------------------


def _below_any(h: Hierarchy, c: str, of: Sequence[str]) -> bool:
    return any(h.is_descendant_or_self(c, x) for x in of)


def _code_options(f: _Fact, h: Hierarchy, source_absent: Sequence[str], target_nc: Sequence[str],
                  target_ctx: Sequence[str]) -> list[str | None]:
    """The fact's possible codes, one per minimal profile against the targets (spec §3.1)."""
    if f.context:
        (c,) = f.context
        code = c or None
        if code is not None and (not all(h.is_descendant_or_self(code, x) for x in f.codes)
                                 or _below_any(h, code, source_absent)):
            return []
        return [code]
    if not f.codes:
        return [None]
    common = None
    for c in sorted(f.codes):
        d = h.descendants_or_self(c)
        common = d if common is None else common & d
    by_profile: dict[tuple[frozenset, frozenset], str] = {}
    for c in sorted(common):
        if _below_any(h, c, source_absent):
            continue
        up = h.ancestors_or_self(c)
        p = (frozenset(x for x in target_nc if x in up), frozenset(x for x in target_ctx if x == c))
        by_profile.setdefault(p, c)
    minimal = [p for p in by_profile
               if not any(q != p and q[0] <= p[0] and q[1] <= p[1] for q in by_profile)]
    return sorted(by_profile[p] for p in minimal)


def _compared_codes(m: Motif) -> set[str]:
    absent = {n.code for n in m.nodes if n.polarity == "absent" and n.code is not None}
    return absent | {s.code for s in slots(m) if s.code is not None and s.role != "context"}


def fresh_type(motifs: Sequence[Motif]) -> str:
    """A node type no pattern uses (longer than every type in use)."""
    used = {n.type for m in motifs for n in m.nodes}
    return "_" * (max(map(len, used), default=0) + 1)


# --- the decision ---------------------------------------------------------------------------------------------------


def _patient(facts: list[tuple[_Fact, str | None, float | None, dict[str, float]]],
             edges: list[tuple[_EdgeReq, float | None]]) -> Motif:
    ids = [PATIENT_ID] + [f"f{i}" for i in range(1, len(facts))]   # fact 0 is the one Patient fact
    nodes = [Node(id=ids[i], type=f.type, role=f.role, code=code,
                  value=None if x is None else Interval.point(x, f.value.unit),
                  attrs={k: Interval.point(v, f.attrs[k].unit) for k, v in pts.items()}, dates=dict(f.dates))
             for i, (f, code, x, pts) in enumerate(facts)]
    es = [Edge(s=ids[e.s], t=ids[e.t], rel=e.rel, prov=e.prov,
               window=None if w is None else Interval.point(w, e.window.unit), dates=dict(e.dates)) for e, w in edges]
    return Motif(motif_id="counterexample", anchor=nodes[0].id, nodes=tuple(nodes), edges=tuple(es))


def _instances(sources: Sequence[Motif], targets: Sequence[Motif], h: Hierarchy,
               source_absent: Sequence[str]) -> Iterator[Motif]:
    cut: dict[str, list[float]] = {}
    for m in (*sources, *targets):
        for iv in _intervals(m):
            cut.setdefault(iv.unit, []).extend(x for x in (iv.lo, iv.hi) if x is not None)
    tgt = [s for m in targets for s in slots(m)]
    target_nc = {t: sorted({s.code for s in tgt if s.type == t and s.role != "context" and s.code}) for t in
                 {s.type for s in tgt}}
    target_ctx = {t: sorted({s.code for s in tgt if s.type == t and s.role == "context" and s.code}) for t in
                  {s.type for s in tgt}}
    items = [(i, s) for i, m in enumerate(sources) for s in slots(m)]
    owner = {k: i for k, (i, _) in enumerate(items)}
    edge_specs = []   # (source index, pattern edge), between present nodes
    for i, m in enumerate(sources):
        present = {n.id for n in m.nodes if n.polarity == "present"}
        edge_specs += [(i, e) for e in m.edges if e.s in present and e.t in present]

    # Shared patient identity: every source's P slot is on the one Patient fact, which no other slot uses; a patient
    # graph has no second fact of that type, so another slot of the patient's type leaves no instance.
    patient = [k for k, (_, s) in enumerate(items) if s.node == PATIENT_ID]
    rest = [k for k in range(len(items)) if k not in patient]
    if any(items[k][1].type == items[patient[0]][1].type for k in rest):
        return

    def can_join(block: list[int], k: int) -> bool:
        return owner[k] not in {owner[j] for j in block} and _fact([items[j] for j in block + [k]]) is not None

    for placed in partitions(rest, can_join):
        blocks = [patient] + placed
        facts = [_fact([items[j] for j in b]) for b in blocks]
        if None in facts:   # a slot no fact can serve (its own dates disagree): this placement has no instance
            continue
        where = {j: bi for bi, b in enumerate(blocks) for j in b}
        options = [_code_options(f, h, source_absent, target_nc.get(f.type, []), target_ctx.get(f.type, []))
                   for f in facts]
        if any(not o for o in options):
            continue
        # One patient edge per required edge: targets never need two distinct patient edges (any edge serves), so an
        # edge shared by several requirements is never harder for them than one edge each (spec §3.3).
        served = sorted({_EdgeReq(where[a], where[b], e.rel, e.prov, e.window, tuple(sorted(e.dates.items())))
                         for i, e in edge_specs
                         for a in (k for k, (o, s) in enumerate(items) if o == i and s.node == e.s)
                         for b in (k for k, (o, s) in enumerate(items) if o == i and s.node == e.t)},
                        key=lambda r: (r.s, r.t, r.rel, r.prov, repr(r.window), r.dates))
        wins = [[None] if r.window is None else representatives(r.window, cut[r.window.unit]) for r in served]
        points = [([None] if f.value is None else representatives(f.value, cut[f.value.unit]),
                   {k: representatives(iv, cut[iv.unit]) for k, iv in sorted(f.attrs.items())}) for f in facts]
        fact_choices = [list(itertools.product(opts, vals, *(pts.values())))
                        for opts, (vals, pts) in zip(options, points, strict=True)]
        for fc in itertools.product(*fact_choices):
            spec = [(f, c[0], c[1], dict(zip(sorted(f.attrs), c[2:], strict=True))) for f, c in zip(facts, fc, strict=True)]
            for ws in itertools.product(*wins):
                yield _patient(spec, list(zip(served, ws, strict=True)))


def decide(sources: Sequence[Motif], targets: Sequence[Motif], h: Hierarchy, limit: int | None = None) -> Verdict:
    """Whether every patient matching every source matches some target (spec §3)."""
    if len(sources) > 1 and len(targets) == 1:   # a single source that implies the target already decides it
        for m in sources:
            v = decide([m], targets, h, limit)
            if v.ok:
                return Verdict("VALID", v.reason, v.evidence | {"covered_by": m.motif_id})
    motifs = [*sources, *targets]
    no_patient = sorted(m.motif_id for m in sources
                        if PATIENT_ID not in m.node_ids or m.node(PATIENT_ID).polarity != "present")
    if no_patient:
        return Verdict("UNKNOWN", "patient_node_missing", {"motifs": no_patient})
    missing = sorted(f"{m.motif_id}:{n.id}" for m in motifs for n in m.nodes if n.polarity == "absent" and n.code is None)
    if missing:
        return Verdict("UNKNOWN", "absent_code_missing", {"nodes": missing})
    inactive = sorted({c for m in motifs for c in _compared_codes(m) if not h.is_active(c)})
    if inactive:
        return Verdict("UNKNOWN", "snomed_mapping_missing", {"inactive_codes": inactive})
    # An uncoded fact is the hardest case for every target slot but an uncoded context one, which only it satisfies;
    # the codes that would be needed instead are not derived, so that pairing is not decided.
    uncoded = {s.type for m in sources for s in slots(m) if s.code is None and s.role != "context"}
    clash = sorted({s.type for m in targets for s in slots(m) if s.code is None and s.role == "context"} & uncoded)
    if clash:
        return Verdict("UNKNOWN", "uncoded_context_target", {"types": clash})
    source_absent = sorted({n.code for m in sources for n in m.nodes if n.polarity == "absent"})
    uncovered = {i: sorted(n.code for n in t.nodes if n.polarity == "absent"
                           and not _below_any(h, n.code, source_absent)) for i, t in enumerate(targets)}
    extra_type = fresh_type(motifs)
    n = 0
    for inst in _instances(sources, targets, h, source_absent):
        n += 1
        if limit is not None and n > limit:
            return Verdict("UNKNOWN", "search_incomplete", {"instances_checked": limit})
        if any(not uncovered[i] and matches(t, inst, h) for i, t in enumerate(targets)):
            continue
        extra = [Node(id=f"x{i}", type=extra_type, role=extra_type, code=uncovered[i][0])
                 for i in sorted(uncovered) if uncovered[i]]
        cx = inst.model_copy(update={"nodes": inst.nodes + tuple(extra)})
        if all(matches(m, cx, h) for m in sources) and not any(matches(t, cx, h) for t in targets):
            return Verdict("INVALID", "not_contained", {"counterexample": cx.model_dump(mode="json")})
        return Verdict("UNKNOWN", "counterexample_unconfirmed", {"instance": cx.model_dump(mode="json")})
    if n == 0:
        return Verdict("VALID", "sources_unsatisfiable", {"instances": 0})
    return Verdict("VALID", "contained", {"instances": n})
