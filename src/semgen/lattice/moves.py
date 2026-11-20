"""One-step neighbours of a motif or bundle: every operator move, guarded and order-proven, deduplicated by hash.

The operators come from ``ctx.operators`` (an immutable ``OperatorSet``) or, when unset, the built-in
``semgen.operators.default_operators()``. A bundle of one takes the single-motif path (``neighbors`` +
``check_order``); bundle operators are not applied to it (deletion would be ``last_part``).
"""
from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass

from semgen.bundle import MotifBundle, MotifPart, bundle_canonical_json, bundle_hash
from semgen.canonical import canonical_json, motif_hash
from semgen.interfaces import Blocked, ChangeRecord, GenContext, Move, OperatorSet
from semgen.lattice.policy import GeneralizationOrderError, bundle_guard, guard
from semgen.model import Motif
from semgen.operators import default_operators
from semgen.operators.concept_lift import OP as LIFT_OP
from semgen.order import check_a1_merge, check_bundle_order, check_group_merge, check_order, is_a1_merge, is_group_merge


def operators_of(ctx: GenContext) -> OperatorSet:
    """The operator set of a run: ``ctx.operators``, else the built-in set."""
    return ctx.operators if ctx.operators is not None else default_operators()


@dataclass(frozen=True)
class Neighbor:
    child: Motif
    child_hash: str
    changes: tuple[ChangeRecord, ...]


def _same_motif(stored: Motif, new: Motif, h: str) -> None:
    if canonical_json(stored) != canonical_json(new):
        raise GeneralizationOrderError(f"hash collision on {h}: distinct motifs share a hash")


def _accept(parent: Motif, move: Move, ctx: GenContext) -> None:
    guard(parent, move.child, move.change, ctx)
    r = check_order(parent, move.child, ctx)
    if r.ok and is_a1_merge(parent, move.child):
        r = check_a1_merge(parent, move.child, ctx)   # A1 is `kept`: the merge must be exact, not only contained
    if r.ok and is_group_merge(parent, move.child):
        r = check_group_merge(parent, move.child, ctx)   # A3 is `kept` likewise
    if not r.ok:
        raise GeneralizationOrderError(f"{r.reason} at {r.where}: {move.change}")


def _lifts_of_observation_nodes(motif: Motif, moves: list[Move]) -> tuple[list[Move], list[Blocked]]:
    """Turn every concept-lift move of a node with A1 observations into one ``carries_value`` block per node.

    Concept lift is not changed (it sees ``value=None``); the observations carry the values, so the lift is
    refused here, before the guard, which rejects it again as ``lift_on_valued_node``.
    """
    kept: list[Move] = []
    blocked: dict[str, Blocked] = {}
    for mv in moves:
        node = motif.node(mv.change.target) if mv.change.op == LIFT_OP else None
        if node is not None and node.observations:
            blocked.setdefault(node.id, Blocked(LIFT_OP, node.id, "carries_value", {"code": node.code}))
        else:
            kept.append(mv)
    return kept, list(blocked.values())


def neighbors(motif: Motif, ctx: GenContext) -> tuple[list[Neighbor], list[Blocked]]:
    parent_hash = motif_hash(motif)
    found: dict[str, Neighbor] = {}
    blocked: list[Blocked] = []
    for op in operators_of(ctx).motif:
        res = op(motif, ctx)
        blocked.extend(res.blocked)
        moves, lift_blocks = _lifts_of_observation_nodes(motif, res.moves)
        blocked.extend(lift_blocks)
        for mv in moves:
            h = motif_hash(mv.child)
            if h == parent_hash:
                continue
            _accept(motif, mv, ctx)
            if h in found:
                n = found[h]
                _same_motif(n.child, mv.child, h)
                found[h] = Neighbor(n.child, h, n.changes + (mv.change,))
            else:
                found[h] = Neighbor(mv.child, h, (mv.change,))
    return list(found.values()), blocked


@dataclass(frozen=True)
class BundleNeighbor:
    child: MotifBundle
    child_hash: str
    changes: tuple[ChangeRecord, ...]
    certificate: Mapping | None = None   # of the first move that reached ``child`` (the root proof re-checks it)


def state_hash(b: MotifBundle) -> str:
    """A bundle of one hashes as its motif (every existing hash is kept); otherwise ``bundle_hash``."""
    return motif_hash(b.single_motif) if b.is_single else bundle_hash(b)


def _same_state(stored: MotifBundle, new: MotifBundle, h: str) -> None:
    if bundle_canonical_json(stored) != bundle_canonical_json(new):
        raise GeneralizationOrderError(f"hash collision on {h}: distinct states share a hash")


def _with_single(bundle: MotifBundle, motif: Motif) -> MotifBundle:
    return bundle.model_copy(update={"parts": (MotifPart(part_id=bundle.parts[0].part_id, motif=motif),)})


def _slots(bundle: MotifBundle) -> list[tuple[str, Motif]]:
    """Every motif a per-motif operator acts on: the parts, by part id."""
    return [(p.part_id, p.motif) for p in sorted(bundle.parts, key=lambda p: p.part_id)]


def _replace_motif(bundle: MotifBundle, part_id: str, motif: Motif) -> MotifBundle:
    """The bundle with one part's motif replaced."""
    new = MotifPart(part_id=part_id, motif=motif)
    return bundle.model_copy(update={"parts": tuple(new if p.part_id == part_id else p for p in bundle.parts)})


def _accept_bundle(parent: MotifBundle, child: MotifBundle, change: ChangeRecord, ctx: GenContext,
                   certificate: Mapping | None = None, changed: tuple[Motif, Motif] | None = None) -> None:
    """``changed`` = (before, after) of a per-motif move (already guarded); A1 merges must also be exact."""
    bundle_guard(parent, child)
    r = check_bundle_order(parent, child, ctx, certificate)
    if r.ok and changed is not None and is_a1_merge(*changed):
        r = check_a1_merge(*changed, ctx)
    if r.ok and changed is not None and is_group_merge(*changed):
        r = check_group_merge(*changed, ctx)
    if not r.ok:
        raise GeneralizationOrderError(f"{r.reason} at {r.where}: {change}")


def bundle_neighbors(bundle: MotifBundle, ctx: GenContext) -> tuple[list[BundleNeighbor], list[Blocked]]:
    """Per-motif operators on every part, then the bundle operators."""
    if bundle.is_single:
        ns, bl = neighbors(bundle.single_motif, ctx)
        return [BundleNeighbor(_with_single(bundle, n.child), n.child_hash, n.changes) for n in ns], bl
    parent_hash = state_hash(bundle)
    found: dict[str, BundleNeighbor] = {}
    blocked: list[Blocked] = []

    def add(child: MotifBundle, change: ChangeRecord, certificate: Mapping | None) -> None:
        h = state_hash(child)
        if h in found:
            n = found[h]
            _same_state(n.child, child, h)
            found[h] = dataclasses.replace(n, changes=n.changes + (change,))
        else:
            found[h] = BundleNeighbor(child, h, (change,), certificate)

    for part_id, motif in _slots(bundle):
        for op in operators_of(ctx).motif:
            res = op(motif, ctx)
            blocked.extend(res.blocked)
            moves, lift_blocks = _lifts_of_observation_nodes(motif, res.moves)
            blocked.extend(lift_blocks)
            for mv in moves:
                if motif_hash(mv.child) == motif_hash(motif):
                    continue
                guard(motif, mv.child, mv.change, ctx)
                child = _replace_motif(bundle, part_id, mv.child)
                _accept_bundle(bundle, child, mv.change, ctx, changed=(motif, mv.child))
                add(child, mv.change, None)
    for bop in operators_of(ctx).bundle:
        res = bop(bundle, ctx)
        blocked.extend(res.blocked)
        for mv in res.moves:
            if state_hash(mv.child) == parent_hash:
                continue
            _accept_bundle(bundle, mv.child, mv.change, ctx, mv.certificate)
            add(mv.child, mv.change, mv.certificate)
    return list(found.values()), blocked


def accept_lift_step(state: MotifBundle, part_id: str | None, motif: Motif, mv: Move,
                     ctx: GenContext) -> tuple[MotifBundle, str] | None:
    """Guard and prove one concept-lift move of a climb (``part_id`` None = a bundle of one); None if it is a no-op."""
    if part_id is None:
        ch = motif_hash(mv.child)
        if ch == motif_hash(motif):
            return None
        _accept(motif, mv, ctx)
        return _with_single(state, mv.child), ch
    child = _replace_motif(state, part_id, mv.child)
    ch = state_hash(child)
    if ch == state_hash(state):
        return None
    guard(motif, mv.child, mv.change, ctx)
    _accept_bundle(state, child, mv.change, ctx, changed=(motif, mv.child))
    return child, ch
