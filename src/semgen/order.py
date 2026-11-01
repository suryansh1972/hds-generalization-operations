"""Independent generalization-order checker (identity-map proof, D8/D9).

Proves that ``general`` is at least as general as ``specific`` by comparing every
node and edge of ``general`` against the same-id node / same-key edge of
``specific``. It never reads a ChangeRecord and trusts nothing the operators say.
"""
from __future__ import annotations

from dataclasses import dataclass

from semgen.model import Interval, Motif, Node
from semgen.operators.base import GenContext


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


def check_order(specific: Motif, general: Motif, ctx: GenContext) -> OrderResult:
    extra = sorted(general.node_ids - specific.node_ids)
    if extra:
        return _fail("extra_node", extra[0])
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
        if g.polarity == "absent" and (s.value != g.value or s.attrs != g.attrs):
            return _fail("absent_constraint_changed", nid)
        if (reason := _contained(g.value, s.value, "value_added", "value_not_contained")) is not None:
            return _fail(reason, nid)
        for name in sorted(g.attrs):
            if name not in s.attrs:
                return _fail("attr_added", nid)
            if not g.attrs[name].contains(s.attrs[name]):
                return _fail("attr_not_contained", nid)
    for ge in sorted(general.edges, key=lambda e: e.key):
        where = f"{ge.s}->{ge.t}"
        se = specific.edge(ge.s, ge.t)
        if se is None:
            return _fail("extra_edge", where)
        if not ctx.config.relations.leq(se.rel, ge.rel):
            return _fail("relation_not_broader", where)
        if se.prov != ge.prov:
            return _fail("provenance_changed", where)
        if (reason := _contained(ge.window, se.window, "window_added", "window_not_contained")) is not None:
            return _fail(reason, where)
    return OrderResult(True)
