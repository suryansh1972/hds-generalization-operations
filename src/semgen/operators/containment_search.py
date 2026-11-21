"""Search for the containment certificates of design §6 (the order checker only re-verifies them). Proposers'
helpers for motif deletion and aggregation: a map they find only shortens the checker's proof.

``find_containment(narrow, broad)`` looks for an injective map ``broad node -> narrow node`` with ``P -> P``
proving ``narrow ⊑ broad``; ``find_isomorphism(a, b)`` for a bijection under which every field except node ids is
equal. Both backtrack over nodes in sorted id order (``P`` first), so the first map found is deterministic. The
search is sound (every map it returns passes ``verify_containment``) but not complete: ``None`` means "not proven".
The backtracking is exhaustive with no budget: it is sized for the small motifs semgen handles (a few nodes each).
``find_isomorphism`` also requires anchor -> anchor, stricter than §7.4's "equal except node ids" and still sound
(a pair it rejects is only left to the containment rule).
"""
from __future__ import annotations

from collections.abc import Callable

from semgen.canonical import edge_descriptor, node_descriptor
from semgen.interfaces import GenContext
from semgen.model import PATIENT_ID, Motif
from semgen.order import edge_containment_reason, node_containment_reason, verify_containment


def _search_order(m: Motif) -> list[str]:
    return sorted(m.node_ids, key=lambda i: (i != PATIENT_ID, i))


def _backtrack(order: list[str], candidates: dict[str, list[str]],
               consistent: Callable[[str, dict[str, str]], bool],
               accept: Callable[[dict[str, str]], bool]) -> dict[str, str] | None:
    def go(i: int, mapping: dict[str, str], used: set[str]) -> dict[str, str] | None:
        if i == len(order):
            return dict(sorted(mapping.items())) if accept(mapping) else None
        x = order[i]
        for y in candidates[x]:
            if y in used:
                continue
            mapping[x] = y
            if consistent(x, mapping) and (found := go(i + 1, mapping, used | {y})) is not None:
                return found
            del mapping[x]
        return None

    return go(0, {}, set())


def find_containment(narrow: Motif, broad: Motif, ctx: GenContext) -> dict[str, str] | None:
    """An injective map ``broad id -> narrow id`` certifying ``narrow ⊑ broad`` (§6), or None."""
    order = _search_order(broad)
    candidates: dict[str, list[str]] = {}
    for gid in order:
        g = broad.node(gid)
        pool = [PATIENT_ID] if gid == PATIENT_ID else sorted(narrow.node_ids - {PATIENT_ID})
        candidates[gid] = [sid for sid in pool if sid in narrow.node_ids
                           and node_containment_reason(narrow, narrow.node(sid), g, ctx) is None]
        if not candidates[gid]:
            return None

    def consistent(gid: str, mapping: dict[str, str]) -> bool:
        for ge in broad.edges:
            if gid in (ge.s, ge.t) and ge.s in mapping and ge.t in mapping:
                if edge_containment_reason(narrow.edge(mapping[ge.s], mapping[ge.t]), ge) is not None:
                    return False
        return True

    return _backtrack(order, candidates, consistent,
                      lambda mapping: verify_containment(narrow, broad, mapping, ctx).ok)


def _edge_descriptor(m: Motif, s: str, t: str) -> str | None:
    e = m.edge(s, t)
    return None if e is None else edge_descriptor(e)


def find_isomorphism(a: Motif, b: Motif) -> dict[str, str] | None:
    """A bijection ``a id -> b id`` (``P -> P``, anchor -> anchor) under which every node and edge field other than
    the node ids is equal (canonical form, so labels are ignored as in ``motif_hash``), or None."""
    if len(a.nodes) != len(b.nodes) or len(a.edges) != len(b.edges):
        return None
    order = _search_order(a)
    candidates: dict[str, list[str]] = {}
    for x in order:
        dx = node_descriptor(a.node(x))
        if x == PATIENT_ID:
            pool = [PATIENT_ID]
        elif x == a.anchor:
            pool = [b.anchor]
        else:
            pool = sorted(b.node_ids - {PATIENT_ID, b.anchor})
        candidates[x] = [y for y in pool if y in b.node_ids and node_descriptor(b.node(y)) == dx]

    def consistent(x: str, mapping: dict[str, str]) -> bool:
        return all(_edge_descriptor(a, x, z) == _edge_descriptor(b, mapping[x], mapping[z])
                   and _edge_descriptor(a, z, x) == _edge_descriptor(b, mapping[z], mapping[x])
                   for z in mapping)

    # Equal edge counts and every pair of mapped nodes agreeing on its edges in both directions: a bijection.
    return _backtrack(order, candidates, consistent, lambda mapping: True)
