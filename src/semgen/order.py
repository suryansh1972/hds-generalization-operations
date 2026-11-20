"""Independent generalization-order checker (identity-map proofs and containment certificates, design §6/§8).

``check_order`` proves that ``general`` is at least as general as ``specific`` by comparing every
node and edge of ``general`` against the same-id node / same-key edge of ``specific`` (an A1-merged node is
compared with each specific node its observations came from, design §7.3).
``verify_containment`` re-verifies a node map certificate ``S ⊑ G``; ``check_bundle_order`` derives the
change between two bundles from their diff. None of them reads a ChangeRecord or trusts an operator.

``check_bundle_order`` reasons: ``subject_changed``, ``cohort_changed``, ``semantics_changed``,
``unsupported_transition``; for a part removal ``unknown_bundle_semantics``, ``has_absent_node``,
``certificate_missing`` (a removal submitted without a certificate) and ``not_contained`` (no retained part verifies
under the certificate). A single changed part reports ``check_order``'s reason.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from semgen.bundle import MotifBundle
from semgen.canonical import canonical_json
from semgen.interfaces import GenContext
from semgen.model import PATIENT_ID, Edge, Interval, Motif, Node, Observation


@dataclass(frozen=True)
class OrderResult:
    ok: bool
    reason: str | None = None
    where: str | None = None


def _fail(reason: str, where: str) -> OrderResult:
    return OrderResult(False, reason, where)


def _code_reason(s: Node, g: Node, ctx: GenContext) -> str | None:
    h = ctx.hierarchy
    if g.role == "context":
        return None if s.code == g.code else "context_code_changed"
    if g.polarity == "present":
        if g.code is None:
            return None
        if s.code is None or not h.is_descendant_or_self(s.code, g.code):
            return "concept_not_broader"
        return None
    if (g.code is None) != (s.code is None):
        return "absent_not_narrower"
    if g.code is None:
        return None
    return None if h.is_descendant_or_self(g.code, s.code) else "absent_not_narrower"


def _contained(g: Interval | None, s: Interval | None, added: str, not_contained: str) -> str | None:
    if g is None:
        return None
    if s is None:
        return added
    return None if g.contains(s) else not_contained


def _dates_reason(g: Mapping[str, str], s: Mapping[str, str]) -> str | None:
    """A date may be dropped, never added or moved (dates match by equality)."""
    for k in sorted(g):
        if k not in s:
            return "date_added"
        if g[k] != s[k]:
            return "date_changed"
    return None


def _observations_reason(g: tuple[Observation, ...], s: tuple[Observation, ...]) -> str | None:
    """Every observation of G needs its own observation of S (one-to-one) with containment and equal dates."""
    if not g:
        return None

    def fits(go: Observation, so: Observation) -> bool:
        return go.value.contains(so.value) and _dates_reason(go.dates, so.dates) is None

    def assign(i: int, used: set[int]) -> bool:
        if i == len(g):
            return True
        for j, so in enumerate(s):
            if j not in used and fits(g[i], so) and assign(i + 1, used | {j}):
                return True
        return False

    return None if assign(0, set()) else "observations_not_contained"


def _node_constraint_reason(s: Node, g: Node) -> str | None:
    """Value, attributes and dates of G must each contain (or equal) those of S."""
    if (reason := _contained(g.value, s.value, "value_added", "value_not_contained")) is not None:
        return reason
    for name in sorted(g.attrs):
        if name not in s.attrs:
            return "attr_added"
        if not g.attrs[name].contains(s.attrs[name]):
            return "attr_not_contained"
    return _dates_reason(g.dates, s.dates)


def _constraint_reason(s: Node, g: Node) -> str | None:
    """As ``_node_constraint_reason``, plus G's observations each matched one-to-one by one of S's."""
    return _node_constraint_reason(s, g) or _observations_reason(g.observations, s.observations)


def _observation_fits(go: Observation, value: Interval | None, dates: Mapping[str, str]) -> bool:
    return value is not None and go.value.contains(value) and _dates_reason(go.dates, dates) is None


def _a1_images(g: Node, specific: Motif, general: Motif, used: set[str],
               ctx: GenContext) -> tuple[str | None, list[str]]:
    """A1 rule (design §7.3) for a general node with observations: each observation maps by ``source_node``.

    If the specific node is itself merged, to its observation with the same ``source_node``; otherwise to the
    specific node of that id, which must be ``g`` itself or a node gone from ``general`` and not claimed by another
    general node (one patient fact per observation). Values contain, dates are kept. Returns the reason, and the
    specific node ids the general node stands for (its images for the edge check).
    """
    s = specific.node(g.id)
    if (reason := _node_constraint_reason(s, g)) is not None:
        return reason, []
    sources = [o.source_node for o in g.observations]
    if len(set(sources)) != len(sources):
        return "observation_source_reused", []
    if s.observations:
        s_obs = {o.source_node: o for o in s.observations}
        for go in g.observations:
            so = s_obs.get(go.source_node)
            if so is None:
                return "observation_source_missing", []
            if not _observation_fits(go, so.value, so.dates):
                return "observation_not_contained", []
        return None, [g.id]
    images: list[str] = []
    for go in g.observations:
        x = go.source_node
        if x not in specific.node_ids:
            return "observation_source_missing", []
        if x != g.id and (x in general.node_ids or x in used):
            return "observation_source_reused", []
        sx = specific.node(x)
        if (sx.polarity, sx.type, sx.role) != (g.polarity, g.type, g.role) or sx.observations:
            return "observation_source_mismatch", []
        if (reason := _code_reason(sx, g, ctx) or _node_constraint_reason(sx, g)) is not None:
            return reason, []
        if not _observation_fits(go, sx.value, sx.dates):
            return "observation_not_contained", []
        images.append(x)
    used.update(x for x in images if x != g.id)
    return None, images


def _member_reason(sx: Node, m: Node, ctx: GenContext) -> str | None:
    if (sx.polarity, sx.type, sx.role) != (m.polarity, m.type, m.role) or sx.members:
        return "group_member_mismatch"
    return _code_reason(sx, m, ctx) or _constraint_reason(sx, m)


def _group_images(g: Node, specific: Motif, general: Motif, used: set[str],
                  ctx: GenContext) -> tuple[str | None, list[str]]:
    """A3 rule (design §7.3): a grouped general node stands for its members, each compared with the specific
    node of that id (or, if the specific node is grouped too, with its member of that id) by the ordinary rules.
    Returns the reason and the specific node ids it stands for (its images for the edge check)."""
    s = specific.node(g.id)
    if not g.members:
        return "grouped_node_not_compared", []   # ungrouping is not a transition any operator makes
    if any((m.type, m.role, m.polarity) != (g.type, g.role, g.polarity) for m in g.members):
        return "group_member_mismatch", []
    if s.members:
        sm = {m.id: m for m in s.members}
        if s.grouping != g.grouping or set(sm) != {m.id for m in g.members}:
            return "grouping_changed", []
        for m in g.members:
            if (reason := _member_reason(sm[m.id], m, ctx)) is not None:
                return reason, []
        return None, [g.id]
    images: list[str] = []
    for m in g.members:
        x = m.id
        if x not in specific.node_ids:
            return "group_member_missing", []
        if x != g.id and (x in general.node_ids or x in used):
            return "group_member_reused", []
        if (reason := _member_reason(specific.node(x), m, ctx)) is not None:
            return reason, []
        images.append(x)
    used.update(x for x in images if x != g.id)
    return None, images


def _edge_reason(se: Edge, ge: Edge) -> str | None:
    if se.rel != ge.rel:
        return "relation_changed"   # relations compare by equality (no relation hierarchy)
    if se.prov != ge.prov:
        return "provenance_changed"
    if (reason := _contained(ge.window, se.window, "window_added", "window_not_contained")) is not None:
        return reason
    return _dates_reason(ge.dates, se.dates)


def check_order(specific: Motif, general: Motif, ctx: GenContext) -> OrderResult:
    extra = sorted(general.node_ids - specific.node_ids)
    if extra:
        return _fail("extra_node", extra[0])
    images: dict[str, list[str]] = {}   # general node -> the specific nodes it stands for (A1 merges: several)
    used: set[str] = set()
    for nid in sorted(general.node_ids):
        s, g = specific.node(nid), general.node(nid)
        if s.type != g.type:
            return _fail("type_changed", nid)
        if s.role != g.role:
            return _fail("role_changed", nid)
        if s.polarity != g.polarity:
            return _fail("polarity_changed", nid)
        if (reason := _code_reason(s, g, ctx)) is not None:
            return _fail(reason, nid)
        if g.polarity == "absent" and (s.value != g.value or s.attrs != g.attrs or s.dates != g.dates):
            return _fail("absent_constraint_changed", nid)
        if g.members or s.members:
            reason, images[nid] = _group_images(g, specific, general, used, ctx)
        elif g.observations:
            reason, images[nid] = _a1_images(g, specific, general, used, ctx)
        else:
            reason, images[nid] = _constraint_reason(s, g), [nid]
        if reason is not None:
            return _fail(reason, nid)
    for ge in sorted(general.edges, key=lambda e: e.key):
        where = f"{ge.s}->{ge.t}"
        for a in images[ge.s]:
            for b in images[ge.t]:
                se = specific.edge(a, b)
                if se is None:
                    return _fail("extra_edge", where)
                if (reason := _edge_reason(se, ge)) is not None:
                    return _fail(reason, where)
    return OrderResult(True)


def is_a1_merge(parent: Motif, child: Motif) -> bool:
    """A merge transition: some node has no observations in ``parent`` and has observations in ``child``."""
    return any(not parent.node(n).observations and child.node(n).observations
               for n in sorted(parent.node_ids & child.node_ids))


def check_a1_merge(parent: Motif, child: Motif, ctx: GenContext) -> OrderResult:
    """Exactness proof of an A1 merge transition (design §7.3), read from the two motifs alone.

    For every merged node g: its observations' ``source_node``s are exactly ``{g.id}`` plus parent nodes removed
    in this transition (each removed node claimed once, no other node removed), each observation's value and dates
    equal its source node's, and g is otherwise unchanged apart from ``value``/``dates`` moving into the
    observations. Every other node and edge is unchanged; only the removed nodes' ``P -> node`` edges go.
    Every source node has the merged node's measurement identity: type, role, polarity, code, value unit and a
    fully known, equal ``test`` (system, code, method, specimen), a point value, and no attrs, observations or
    members; each observation keeps its source's reference range and label, and the node keeps a reference range
    only when every source shares it (else none). ``check_order`` (containment) runs as well; this check is what
    makes the ``kept`` label exact.
    """
    merged = [n for n in sorted(parent.node_ids & child.node_ids)
              if not parent.node(n).observations and child.node(n).observations]
    if not merged:
        return _fail("not_a1_merge", "motif")
    removed = parent.node_ids - child.node_ids
    if child.node_ids - parent.node_ids:
        return _fail("extra_node", sorted(child.node_ids - parent.node_ids)[0])
    claimed: set[str] = set()
    for gid in merged:
        pg, cg = parent.node(gid), child.node(gid)
        sources = [o.source_node for o in cg.observations]
        others = set(sources) - {gid}
        if (len(set(sources)) != len(sources) or gid not in sources or not others <= removed
                or others & claimed):
            return _fail("a1_sources_not_exact", gid)
        claimed |= others
        for o in cg.observations:
            src = parent.node(o.source_node)
            if (src.polarity != "present" or src.value is None or o.value != src.value
                    or dict(o.dates) != dict(src.dates) or o.reference_range != src.reference_range
                    or o.label != src.label):
                return _fail("a1_observation_changed", f"{gid}:{o.source_node}")
            if not _same_measurement(src, pg):
                return _fail("a1_identity_differs", f"{gid}:{o.source_node}")
        ranges = {parent.node(s).reference_range for s in sources}
        shared = pg.reference_range if len(ranges) == 1 else None
        if cg.model_copy(update={"observations": ()}) != pg.model_copy(update={"value": None, "dates": {},
                                                                               "reference_range": shared}):
            return _fail("a1_other_change", gid)
    if claimed != removed:
        return _fail("a1_sources_not_exact", sorted(removed - claimed)[0])
    for nid in sorted(child.node_ids - set(merged)):
        if child.node(nid) != parent.node(nid):
            return _fail("a1_other_change", nid)
    dropped = {e.key for e in parent.edges if e.s in removed or e.t in removed}
    if any((PATIENT_ID, x) not in dropped for x in removed) or len(dropped) != len(removed):
        return _fail("a1_other_change", "edges")   # a removed node had an edge other than its P edge
    if ({e.key: e for e in child.edges} != {e.key: e for e in parent.edges if e.key not in dropped}):
        return _fail("a1_other_change", "edges")
    return OrderResult(True)


def _same_measurement(x: Node, g: Node) -> bool:
    """``x`` is a repeat of the measurement ``g`` (both from the parent): identity known and equal, one point value."""
    t = x.test
    return (t is not None and None not in (t.system, t.code, t.method, t.specimen) and t == g.test
            and (x.type, x.role, x.polarity, x.code) == (g.type, g.role, g.polarity, g.code)
            and x.value is not None and g.value is not None and x.value.unit == g.value.unit
            and x.value.lo is not None and x.value.lo == x.value.hi
            and not (x.attrs or x.observations or x.members))


def is_group_merge(parent: Motif, child: Motif) -> bool:
    """An A3 transition: some node has no members in ``parent`` and has members in ``child``."""
    return any(not parent.node(n).members and child.node(n).members
               for n in sorted(parent.node_ids & child.node_ids))


def check_group_merge(parent: Motif, child: Motif, ctx: GenContext) -> OrderResult:
    """Exactness proof of an A3 grouping (design §7.3), read from the two motifs alone: each grouped node's
    members are exactly its own parent node plus parent nodes removed in this transition, verbatim and each claimed
    once; the grouped node carries nothing else (code None, no constraint); every other node is unchanged; only the
    removed nodes' ``P -> node`` edges go. ``check_order`` runs as well; this is what makes ``kept`` exact."""
    merged = [n for n in sorted(parent.node_ids & child.node_ids)
              if not parent.node(n).members and child.node(n).members]
    if not merged:
        return _fail("not_group_merge", "motif")
    if child.node_ids - parent.node_ids:
        return _fail("extra_node", sorted(child.node_ids - parent.node_ids)[0])
    removed = parent.node_ids - child.node_ids
    claimed: set[str] = set()
    for gid in merged:
        pg, cg = parent.node(gid), child.node(gid)
        ids = [m.id for m in cg.members]
        others = set(ids) - {gid}
        if gid not in ids or not others <= removed or others & claimed:
            return _fail("group_members_not_exact", gid)
        claimed |= others
        for m in cg.members:
            if m != parent.node(m.id):
                return _fail("group_member_changed", f"{gid}:{m.id}")
        bare = Node(id=gid, type=pg.type, role=pg.role, polarity=pg.polarity, label=cg.label,
                    members=cg.members, grouping=cg.grouping)
        if cg != bare:
            return _fail("group_other_change", gid)
    if claimed != removed:
        return _fail("group_members_not_exact", sorted(removed - claimed)[0])
    for nid in sorted(child.node_ids - set(merged)):
        if child.node(nid) != parent.node(nid):
            return _fail("group_other_change", nid)
    dropped = {e.key for e in parent.edges if e.s in removed or e.t in removed}
    if any((PATIENT_ID, x) not in dropped for x in removed) or len(dropped) != len(removed):
        return _fail("group_other_change", "edges")
    if {e.key: e for e in child.edges} != {e.key: e for e in parent.edges if e.key not in dropped}:
        return _fail("group_other_change", "edges")
    return OrderResult(True)


# --- containment certificates (design §6) ----------------------------------------------------------


def _active_code_reason(code: str | None, ctx: GenContext) -> str | None:
    return None if code is not None and ctx.hierarchy.is_active(code) else "snomed_mapping_missing"


def _present_code_reason(s: Node, g: Node, ctx: GenContext) -> str | None:
    if g.role == "context":
        return None if s.code == g.code else "context_code_changed"
    if g.code is None:
        return None
    if s.code is None:
        return "concept_not_broader"
    if _active_code_reason(s.code, ctx) or _active_code_reason(g.code, ctx):
        return "snomed_mapping_missing"
    return None if ctx.hierarchy.is_descendant_or_self(s.code, g.code) else "concept_not_broader"


def _absent_code_reason(g: Node, narrow: Motif, ctx: GenContext) -> str | None:
    """S must forbid at least what G forbids: some absent node of S lies at or above G's absent code."""
    if _active_code_reason(g.code, ctx):
        return "snomed_mapping_missing"
    inactive = False
    for s2 in narrow.nodes:
        if s2.polarity != "absent":
            continue
        if _active_code_reason(s2.code, ctx):
            inactive = True
        elif ctx.hierarchy.is_descendant_or_self(g.code, s2.code):
            return None
    return "snomed_mapping_missing" if inactive else "absent_not_narrower"


def verify_containment(narrow: Motif, broad: Motif, mapping: Mapping[str, str], ctx: GenContext) -> OrderResult:
    """Re-verify the certificate ``narrow ⊑ broad``: ``mapping`` sends every broad node id to a narrow node id.

    Sound for the matching semantics (an injective map composes with the patient match); not complete, so a
    failure means "not proven", never "not contained".
    """
    missing = sorted(broad.node_ids - set(mapping))
    if missing:
        return _fail("mapping_incomplete", missing[0])
    for gid in sorted(mapping):
        if gid not in broad.node_ids or mapping[gid] not in narrow.node_ids:
            return _fail("mapping_invalid", gid)
    images = [mapping[g] for g in sorted(mapping)]
    if len(set(images)) != len(images):
        return _fail("mapping_not_injective", next(g for g in sorted(mapping) if images.count(mapping[g]) > 1))
    if PATIENT_ID in broad.node_ids and mapping[PATIENT_ID] != PATIENT_ID:
        return _fail("patient_not_fixed", PATIENT_ID)
    for gid in sorted(broad.node_ids):
        if (reason := node_containment_reason(narrow, narrow.node(mapping[gid]), broad.node(gid), ctx)) is not None:
            return _fail(reason, gid)
    for ge in sorted(broad.edges, key=lambda e: e.key):
        if (reason := edge_containment_reason(narrow.edge(mapping[ge.s], mapping[ge.t]), ge)) is not None:
            return _fail(reason, f"{ge.s}->{ge.t}")
    return OrderResult(True)


def _group_shape(n: Node) -> tuple | None:
    """A grouped node's content with node ids removed (ids differ between namespaced bundle parts)."""
    if not n.members:
        return None
    g = n.grouping
    return (n.type, n.role, n.polarity, g.kind, g.system, g.code, g.version, g.source,
            tuple(m.model_copy(update={"id": ""}) for m in n.members))


def node_containment_reason(narrow: Motif, s: Node, g: Node, ctx: GenContext) -> str | None:
    """§6 for one mapped pair ``g -> s`` (``s`` a node of ``narrow``); None if it holds."""
    if g.members or s.members:   # A3: only an identical grouped node (ids aside) is compared
        return None if _group_shape(g) == _group_shape(s) else "grouped_node_not_compared"
    if s.type != g.type:
        return "type_changed"
    if s.role != g.role:
        return "role_changed"
    if s.polarity != g.polarity:
        return "polarity_changed"
    if g.polarity == "present":
        return _present_code_reason(s, g, ctx) or _constraint_reason(s, g)
    return _absent_code_reason(g, narrow, ctx) or _constraint_reason(s, g)


def edge_containment_reason(se: Edge | None, ge: Edge) -> str | None:
    """§6 for one broad edge ``ge`` and the narrow edge between its endpoints' images (None if there is none)."""
    return "missing_edge" if se is None else _edge_reason(se, ge)


# --- bundle order (design §8) ----------------------------------------------------------------------


def _same(a: Motif, b: Motif) -> bool:
    return canonical_json(a) == canonical_json(b)


def _has_absent(m: Motif) -> bool:
    return any(n.polarity == "absent" for n in m.nodes)


def check_bundle_order(parent: MotifBundle, child: MotifBundle, ctx: GenContext,
                       certificate: Mapping | None = None) -> OrderResult:
    """Prove ``child`` matches every patient ``parent`` matches, from the two bundles alone (design §8).

    The transition is derived from the diff of part ids: none changed (at most one part changed in place, proven by
    ``check_order``; monotone under "all" and "any" alike), or one part removed with every other part unchanged.
    ``certificate`` (a removal's containment map ``{broad node: narrow node}``) is never trusted: it is re-verified.
    Anything else is ``unsupported_transition``.
    """
    if parent.subject != child.subject:
        return _fail("subject_changed", "subject")
    if parent.cohort != child.cohort:
        return _fail("cohort_changed", "cohort")
    if parent.semantics != child.semantics:
        return _fail("semantics_changed", "semantics")
    if parent.anchor_part != child.anchor_part:
        return _fail("unsupported_transition", "anchor_part")
    p_ids, c_ids = {p.part_id for p in parent.parts}, {p.part_id for p in child.parts}
    gone, new = sorted(p_ids - c_ids), sorted(c_ids - p_ids)
    if new:
        return _fail("unsupported_transition", new[0])
    if not gone:
        changed = [pid for pid in sorted(p_ids) if not _same(parent.part(pid).motif, child.part(pid).motif)]
        if len(changed) > 1:
            return _fail("unsupported_transition", ",".join(changed))
        if not changed:
            return OrderResult(True)
        pid = changed[0]
        r = check_order(parent.part(pid).motif, child.part(pid).motif, ctx)
        return r if r.ok else OrderResult(False, r.reason, f"{pid}:{r.where}")
    for pid in sorted(c_ids):
        if not _same(parent.part(pid).motif, child.part(pid).motif):
            return _fail("unsupported_transition", pid)
    if len(gone) != 1:
        return _fail("unsupported_transition", "parts")
    return _check_part_removal(parent, gone[0], ctx, certificate)


def _check_part_removal(parent: MotifBundle, removed: str, ctx: GenContext,
                        certificate: Mapping[str, str] | None) -> OrderResult:
    """One part removed, every other part unchanged, covered by a retained part.

    ``"all"`` (A AND B): the removed part is the broader G of a retained ``S ⊑ G`` (``S AND G = S``); ``"any"``
    (A OR B): the narrower S of a retained ``S ⊑ G`` (``S OR G = G``). The anchor part cannot be removed (the child
    keeps the parent's anchor, which must be one of its parts) and the last part cannot be removed (a bundle is never
    empty).
    """
    if parent.semantics is None:
        return _fail("unknown_bundle_semantics", removed)
    gone = parent.part(removed)
    if _has_absent(gone.motif):
        return _fail("has_absent_node", removed)
    if certificate is None:
        return _fail("certificate_missing", removed)
    for p in sorted(parent.parts, key=lambda p: p.part_id):
        if p.part_id == removed:
            continue
        narrow, broad = (p.motif, gone.motif) if parent.semantics == "all" else (gone.motif, p.motif)
        if verify_containment(narrow, broad, certificate, ctx).ok:
            return OrderResult(True)
    return _fail("not_contained", removed)
