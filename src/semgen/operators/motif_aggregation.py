"""Motif aggregation (spec §5), an opt-in bundle operator: graph anti-unification of bundle parts.

``generalize(motifs, ctx)`` builds the least general generalizations of two or more motifs within the rules of
spec §5. A correspondence pairs nodes across the inputs (one tuple per generalized node, injective per input; the
patient tuple and the anchor tuple are required). A tuple needs equal type and polarity; context nodes need equal
role and code; A1/A3 nodes identical descriptors. Codes are kept when equal, or abstracted to each minimal common
ancestor reachable from every code by parent steps that concept lift's ``check_lift`` accepts, on nodes without
value, observations, members or concept-dependent attributes. Intervals are kept when equal or when one contains the
others, else dropped; dates, test identity and reference range are kept when equal, else dropped; an edge is kept when
every input has it between the corresponding nodes with equal ``rel`` and ``prov``. An absent code is kept when every
input forbids at least as much with an absent node of the same type. Every drop and abstraction is recorded per input.

Every inclusion-maximal correspondence and ancestor choice gives a candidate; candidates equal up to node ids are
merged, and a candidate is dropped only when another one is proven more specific. ``motif_aggregation(bundle, ctx)``
proposes every pair of parts; ``aggregate(bundle, part_ids, ctx)`` any set. The aggregate replaces the consumed parts
under the bundle's own semantics (and becomes the anchor part if it consumed it). This module only proposes: the
independent checker (``semgen.order.decide_aggregation``) decides every candidate and only ``VALID`` becomes a move.
"""
from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass

from semgen.bundle import MotifBundle, MotifPart
from semgen.canonical import node_descriptor, structural_signature
from semgen.interfaces import Blocked, BundleMove, BundleOperatorResult, ChangeRecord, GenContext
from semgen.model import PATIENT_ID, Edge, Interval, Motif, Node
from semgen.operators.containment_search import find_containment, find_isomorphism
from semgen.order import aggregate_part_id, decide_aggregation, original_part_ids

OP = "motif_aggregation"


@dataclass(frozen=True)
class Generalization:
    motif: Motif
    maps: dict[str, dict[str, str]]        # input motif id -> {aggregate node: input node}
    changes: dict[str, list[list]]         # input motif id -> sorted [kind, where, detail]
    negation: str                          # complete | partial


# --- codes and intervals -------------------------------------------------------------------------------------------


def _reach(code: str, node: Node, ctx: GenContext) -> frozenset[str]:
    """``code`` and every ancestor reachable from it by parent steps that concept lift accepts."""
    seen, todo = {code}, [code]
    while todo:
        c = todo.pop()
        for p in sorted(ctx.hierarchy.parents(c)):
            if p not in seen and ctx.floors.check_lift(c, p, role=node.role, node_id=node.id, cohort=ctx.cohort).ok:
                seen.add(p)
                todo.append(p)
    return frozenset(seen)


def _free(n: Node, ctx: GenContext) -> bool:
    return (n.value is None and not n.observations and not n.members
            and not any(ctx.config.attr_is_concept_dependent(a) for a in n.attrs))


def _code_choices(ns: Sequence[Node], ctx: GenContext) -> list[str | None]:
    """The codes the generalized node may take (empty: the tuple cannot be generalized)."""
    codes = {n.code for n in ns}
    if len(codes) == 1:
        return [ns[0].code]
    h = ctx.hierarchy
    if None in codes or any(n.role == "context" for n in ns) or not all(_free(n, ctx) for n in ns) \
            or not all(h.is_active(c) for c in codes):
        return []
    common = frozenset.intersection(*(_reach(n.code, n, ctx) for n in ns))
    return sorted(a for a in common if not any(b != a and a in h.ancestors(b) for b in common))


def _merge_interval(ivs: Sequence[Interval | None]) -> Interval | None:
    """Equal intervals are kept, and so is one containing all the others; otherwise none (no range is invented)."""
    if any(iv is None for iv in ivs) or len({iv.unit for iv in ivs}) > 1:
        return None
    return next((iv for iv in ivs if all(iv.contains(o) for o in ivs)), None)


def _common(values: Sequence):
    return values[0] if all(v == values[0] for v in values) else None


def _common_dates(ds: Sequence) -> dict[str, str]:
    return {k: v for k, v in ds[0].items() if all(d.get(k) == v for d in ds)}


def _interval_change(s: Interval | None, g: Interval | None) -> str | None:
    if s is None or s == g:
        return None
    return "dropped" if g is None else "widened"


# --- one candidate --------------------------------------------------------------------------------------------------


def _tuple_ok(ns: Sequence[Node], ctx: GenContext) -> bool:
    if len({(n.type, n.polarity) for n in ns}) > 1:
        return False
    if any(n.role == "context" for n in ns) and len({(n.role, n.code) for n in ns}) > 1:
        return False
    if any(n.observations or n.members for n in ns) and len({node_descriptor(n) for n in ns}) > 1:
        return False
    return bool(_code_choices(ns, ctx))


def _general_node(gid: str, ns: Sequence[Node], code: str | None) -> Node:
    ref = ns[0]
    if ref.observations or ref.members:   # identical descriptors: the reference node itself
        return ref.model_copy(update={"id": gid})
    names = sorted(set().union(*(n.attrs for n in ns)))
    attrs = {k: iv for k in names if (iv := _merge_interval([n.attrs.get(k) for n in ns])) is not None}
    return Node(id=gid, type=ref.type, role=ref.role, label=_common([n.label for n in ns]), code=code,
                polarity=ref.polarity, value=_merge_interval([n.value for n in ns]), attrs=attrs,
                dates=_common_dates([n.dates for n in ns]), test=_common([n.test for n in ns]),
                reference_range=_common([n.reference_range for n in ns]))


def _node_changes(s: Node, g: Node) -> list[list]:
    out = []
    if s.code != g.code:
        out.append(["code_abstracted" if s.polarity == "present" else "absent_narrowed", s.id, f"{s.code}->{g.code}"])
    if s.role != g.role:
        out.append(["role_differs", s.id, f"{s.role}->{g.role}"])
    if kind := _interval_change(s.value, g.value):
        out.append([f"value_{kind}", s.id, None])
    out += [[f"attr_{kind}", f"{s.id}:{k}", None] for k in sorted(s.attrs)
            if (kind := _interval_change(s.attrs[k], g.attrs.get(k)))]
    out += [["date_dropped", f"{s.id}:{k}", None] for k in sorted(s.dates) if k not in g.dates]
    if s.test is not None and s.test != g.test:
        out.append(["test_dropped", s.id, None])
    if s.reference_range is not None and s.reference_range != g.reference_range:
        out.append(["reference_range_dropped", s.id, None])
    return out


def _absent_tuples(inputs: Sequence[Motif], taken: set[str], ctx: GenContext) -> tuple[list[tuple[str, list[Node]]],
                                                                                           str]:
    """Absent tuples ``(aggregate id, [one absent node per input])``: a code Y of some input is kept when every input
    has an absent node of the same type at or above Y; only the maximal such codes; each input node used once."""
    h = ctx.hierarchy
    absent = [[n for n in sorted(m.nodes, key=lambda n: n.id) if n.polarity == "absent"] for m in inputs]
    seen: dict[tuple[str, str], Node] = {}
    for ns in absent:
        for n in ns:
            seen.setdefault((n.type, n.code), n)
    ok = {k: n for k, n in seen.items()
          if all(any(x.type == k[0] and h.is_descendant_or_self(k[1], x.code) for x in ns) for ns in absent)}
    keep = [k for k in sorted(ok) if not any(j != k and j[0] == k[0] and h.is_descendant_or_self(k[1], j[1])
                                             for j in ok)]
    used: list[set[str]] = [set() for _ in inputs]
    out = []
    for t, code in keep:
        picks = [next((x for x in ns if x.id not in used[i] and x.type == t and h.is_descendant_or_self(code, x.code)),
                      None) for i, ns in enumerate(absent)]
        if None in picks:
            continue
        src = seen[(t, code)]
        gid = src.id if src.id not in taken else f"{src.id}~{len(taken)}"
        taken.add(gid)
        for i, x in enumerate(picks):
            used[i].add(x.id)
        out.append((gid, [src.model_copy(update={"id": gid})] + picks))
    codes = [sorted((n.type, n.code) for n in ns) for ns in absent]
    return out, "complete" if all(c == codes[0] for c in codes) else "partial"


def _build(inputs: Sequence[Motif], part_id: str, present: dict[str, tuple[str, ...]],
           codes: dict[str, str | None], ctx: GenContext) -> Generalization:
    """The generalization of one correspondence (``present``: aggregate id -> one node id per input) and choice."""
    ref = inputs[0]
    nodes: dict[str, Node] = {}
    members: dict[str, list[Node]] = {}
    for gid, ids in present.items():
        ns = [m.node(i) for m, i in zip(inputs, ids, strict=True)]
        nodes[gid], members[gid] = _general_node(gid, ns, codes[gid]), ns
    absent, negation = _absent_tuples(inputs, set(nodes), ctx)
    for gid, (g, *ns) in absent:
        nodes[gid], members[gid] = g, ns
    edges = []
    for a, b in itertools.product(sorted(members), repeat=2):
        es = [m.edge(members[a][i].id, members[b][i].id) for i, m in enumerate(inputs)]
        if any(e is None for e in es) or len({(e.rel, e.prov) for e in es}) > 1:
            continue
        edges.append(Edge(s=a, t=b, rel=es[0].rel, prov=es[0].prov, window=_merge_interval([e.window for e in es]),
                          bpn_score=_common([e.bpn_score for e in es]), dates=_common_dates([e.dates for e in es])))
    g = Motif(motif_id=part_id, anchor=ref.anchor,
              nodes=tuple(nodes[k] for k in sorted(nodes, key=lambda k: (k != PATIENT_ID, k))), edges=tuple(edges))
    maps, changes = {}, {}
    for i, m in enumerate(inputs):
        mp = {gid: ns[i].id for gid, ns in members.items()}
        inv = {v: k for k, v in mp.items()}
        out = [["node_dropped", n.id, None] for n in m.nodes if n.id not in inv]
        out += [c for gid, ns in members.items() for c in _node_changes(ns[i], nodes[gid])]
        for e in m.edges:
            ge = g.edge(inv[e.s], inv[e.t]) if e.s in inv and e.t in inv else None
            where = f"{e.s}->{e.t}"
            if ge is None:
                out.append(["edge_dropped", where, None])
                continue
            if kind := _interval_change(e.window, ge.window):
                out.append([f"window_{kind}", where, None])
            out += [["edge_date_dropped", f"{where}:{k}", None] for k in sorted(e.dates) if k not in ge.dates]
            if e.bpn_score != ge.bpn_score:
                out.append(["edge_score_dropped", where, None])
        maps[m.motif_id] = dict(sorted(mp.items()))
        changes[m.motif_id] = sorted(out, key=lambda x: (x[0], x[1], x[2] or ""))
    return Generalization(g, maps, changes, negation)


# --- every candidate ------------------------------------------------------------------------------------------------


def _correspondences(inputs: Sequence[Motif], ctx: GenContext) -> list[dict[str, tuple[str, ...]]]:
    """Every inclusion-maximal correspondence over the present nodes (keyed by the reference input's node ids)."""
    ref, others = inputs[0], inputs[1:]
    present = [[n.id for n in sorted(m.nodes, key=lambda n: n.id) if n.polarity == "present"] for m in inputs]
    fixed = {PATIENT_ID: tuple(PATIENT_ID for _ in inputs), ref.anchor: tuple(m.anchor for m in inputs)}
    memo: dict[tuple[str, ...], bool] = {}

    def ok(ids: tuple[str, ...]) -> bool:
        if ids not in memo:
            memo[ids] = _tuple_ok([m.node(i) for m, i in zip(inputs, ids, strict=True)], ctx)
        return memo[ids]

    if not all(ok(t) for t in fixed.values()) or len(set(fixed)) < len(fixed):
        return []
    rest = [x for x in present[0] if x not in fixed]
    found: list[dict[str, tuple[str, ...]]] = []

    def options(x: str, used: list[set[str]]) -> list[tuple[str, ...]]:
        pools = [[y for y in present[i + 1] if y not in used[i]] for i in range(len(others))]
        return [(x, *ys) for ys in itertools.product(*pools) if ok((x, *ys))]

    def go(k: int, chosen: dict[str, tuple[str, ...]], used: list[set[str]], skipped: list[str]) -> None:
        if k == len(rest):
            if not any(options(x, used) for x in skipped):   # nothing can be added: maximal
                found.append(dict(chosen))
            return
        x = rest[k]
        for t in options(x, used):
            chosen[x] = t
            go(k + 1, chosen, [u | {y} for u, y in zip(used, t[1:], strict=True)], skipped)
            del chosen[x]
        go(k + 1, chosen, used, skipped + [x])

    go(0, dict(fixed), [{t[i + 1] for t in fixed.values()} for i in range(len(others))], [])
    return found


def generalize(motifs: Sequence[Motif], ctx: GenContext, part_id: str | None = None) -> tuple[list[Generalization],
                                                                                              dict]:
    """The least general generalizations of ``motifs`` (two or more) within spec §5, and a summary of the search."""
    inputs = sorted(motifs, key=lambda m: min(original_part_ids(m.motif_id)))
    part_id = part_id or aggregate_part_id([m.motif_id for m in inputs])
    built: list[Generalization] = []
    corr = _correspondences(inputs, ctx)
    for c in corr:
        choices = {gid: _code_choices([m.node(i) for m, i in zip(inputs, ids, strict=True)], ctx)
                   for gid, ids in sorted(c.items())}
        for pick in itertools.product(*choices.values()):
            built.append(_build(inputs, part_id, c, dict(zip(choices, pick, strict=True)), ctx))
    unique: list[Generalization] = []
    for cand in built:
        if not any(structural_signature(u.motif) == structural_signature(cand.motif)
                   and find_isomorphism(u.motif, cand.motif) is not None for u in unique):
            unique.append(cand)
    kept = [c for c in unique
            if not any(o is not c and find_containment(o.motif, c.motif, ctx) is not None
                       and find_containment(c.motif, o.motif, ctx) is None for o in unique)]
    summary = {"correspondences": len(corr), "built": len(built), "distinct": len(unique), "kept": len(kept),
               "search": "exhaustive"}
    return kept, summary


def aggregate(bundle: MotifBundle, part_ids: Sequence[str], ctx: GenContext) -> BundleOperatorResult:
    """Moves replacing the parts ``part_ids`` (two or more) of ``bundle`` by each verified generalization."""
    new_id = aggregate_part_id(part_ids)
    if bundle.semantics is None:
        return BundleOperatorResult([], [Blocked(OP, new_id, "unknown_bundle_semantics", {})])
    if new_id in {p.part_id for p in bundle.parts}:
        return BundleOperatorResult([], [Blocked(OP, new_id, "part_id_taken", {})])
    consumed = sorted(set(part_ids))
    cands, summary = generalize([bundle.part(p).motif for p in consumed], ctx, new_id)
    if not cands:
        return BundleOperatorResult([], [Blocked(OP, new_id, "no_correspondence", summary)])
    moves, blocked = [], []
    anchor = new_id if bundle.anchor_part in consumed else bundle.anchor_part
    reference = min(consumed, key=lambda p: min(original_part_ids(p)))
    for cand in cands:
        parts = tuple(p for p in bundle.parts if p.part_id not in consumed) + (MotifPart(part_id=new_id,
                                                                                         motif=cand.motif),)
        child = bundle.model_copy(update={"parts": parts, "anchor_part": anchor})
        cert = {"maps": cand.maps, "changes": cand.changes}
        verdict = decide_aggregation(bundle, child, ctx, cert)
        if not verdict.ok:
            blocked.append(Blocked(OP, new_id, verdict.reason, {"status": verdict.status} | verdict.evidence))
            continue
        evidence = {"inputs": consumed, "reference": reference, "maps": cand.maps,
                    "changes": cand.changes, "completeness": {"search": summary["search"], "negation": cand.negation,
                                                              "scope": "spec §5 rules, one correspondence per input"},
                    "summary": summary}
        moves.append(BundleMove(child, ChangeRecord(OP, new_id, "parts", consumed, new_id, evidence,
                                                    rule_id="motif.aggregate.lgg"), cert))
    return BundleOperatorResult(moves, blocked)


def motif_aggregation(bundle: MotifBundle, ctx: GenContext) -> BundleOperatorResult:
    """Every pair of parts (larger sets arise by aggregating an aggregate again)."""
    moves, blocked = [], []
    for a, b in itertools.combinations(sorted(p.part_id for p in bundle.parts), 2):
        res = aggregate(bundle, [a, b], ctx)
        moves += res.moves
        blocked += res.blocked
    return BundleOperatorResult(moves, blocked)
