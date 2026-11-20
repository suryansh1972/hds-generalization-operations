"""Motif deletion (design §7.4), a bundle operator: drop a redundant part whose removal keeps the bundle's match
set, proven by a SNOMED-constrained query containment certificate (§6).

By the bundle's declared semantics (``None`` = unknown: every deletion blocks):
- ``"all"`` (A AND B): if a retained part S has ``S ⊑ G`` then ``S AND G = S``, so the broader part G goes;
- ``"any"`` (A OR B): if a retained part G has ``S ⊑ G`` then ``S OR G = G``, so the narrower part S goes.
Exact duplicates (isomorphic up to node ids, contained both ways): the larger ``part_id`` goes, unless it is the anchor
part, then the other one (a total order on ids, independent of traversal). The anchor part is never deleted, the
last part never goes, a part with an absent node is never compared, and every remaining part is unchanged. A part
whose nodes are A3 groups is compared only with an identical group (``order.node_containment_reason``).

One move per deletable part: duplicates are tried first, then containment, each over the other parts in sorted id
order, and the first cover found is recorded. Every move is ``kept``; its certificate is the map
``{G node: S node}``, re-verified by ``order.check_bundle_order``. The evidence keeps the deleted part's id and
canonical JSON, the covering part and the direction, so the removal stays traceable. No similarity score is used:
a pair without a verified certificate is ``not_contained``.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from semgen.bundle import MotifBundle
from semgen.canonical import canonical_json, structural_signature
from semgen.interfaces import Blocked, BundleMove, BundleOperatorResult, ChangeRecord, GenContext
from semgen.model import Motif
from semgen.operators.containment_search import find_containment, find_isomorphism, inactive_obstruction
from semgen.order import verify_containment

OP = "motif_deletion"


class _Cover(NamedTuple):
    rule: str                  # exact_duplicate | query_contained
    cover: str                 # the retained part or member id
    certificate: dict[str, str]


def _has_absent(m: Motif) -> bool:
    return any(n.polarity == "absent" for n in m.nodes)


def _duplicate_map(deleted: Motif, kept: Motif, delete_broader: bool, ctx: GenContext) -> dict[str, str] | None:
    """For an exact duplicate, the certificate in the direction the rule needs (``{G node: S node}``), or None.

    The signature only filters; the isomorphism confirms, and the containment it induces must verify both ways
    (it does not when a code is inactive).
    """
    if structural_signature(deleted) != structural_signature(kept):
        return None
    iso = find_isomorphism(deleted, kept)   # deleted id -> kept id
    if iso is None:
        return None
    inverse = dict(sorted((v, k) for k, v in iso.items()))
    if not (verify_containment(kept, deleted, iso, ctx).ok and verify_containment(deleted, kept, inverse, ctx).ok):
        return None
    return iso if delete_broader else inverse


def _find_cover(cand: str, motifs: dict[str, Motif], delete_broader: bool, keeps_duplicate: Callable[[str, str], bool],
                ctx: GenContext) -> _Cover | tuple[str, dict] | None:
    """The first cover of ``cand``; else ``(blocked reason, detail)``; None when
    ``cand`` is only the retained side of an exact duplicate (that is not a blocked deletion).

    A failure is ``snomed_mapping_missing`` when, in some pair actually tried, a node pair of equal type, role and
    polarity fails only because a code is inactive (§6: both codes active); otherwise ``not_contained``.
    """
    m = motifs[cand]
    others = sorted(set(motifs) - {cand})
    duplicates: set[str] = set()
    inactive: set[str] = set()
    for o in others:
        if (cert := _duplicate_map(m, motifs[o], delete_broader, ctx)) is None:
            continue
        if not keeps_duplicate(cand, o):
            return _Cover("exact_duplicate", o, cert)
        duplicates.add(o)
    for o in others:
        if o in duplicates:
            continue   # one move per duplicate pair: the duplicate rule alone decides it
        narrow, broad = (motifs[o], m) if delete_broader else (m, motifs[o])
        if (cert := find_containment(narrow, broad, ctx)) is not None:
            return _Cover("query_contained", o, cert)
        inactive.update(inactive_obstruction(narrow, broad, ctx))
    if duplicates:
        return None
    if inactive:
        return "snomed_mapping_missing", {"inactive_codes": sorted(inactive)}
    return "not_contained", {}


def _record(target: str, scope: str, reason: str, deleted: str, motif: Motif, cover: str, direction: str,
            cert: dict[str, str]) -> ChangeRecord:
    evidence = {"scope": scope, "deleted": deleted, "deleted_canonical": canonical_json(motif), "subsumed_by": cover,
                "direction": direction, "mapping": cert}
    return ChangeRecord(OP, target, "part", deleted, None, evidence, meaning="kept", rule_id=f"motif.delete.{reason}")


def _scope_a(bundle: MotifBundle, ctx: GenContext, moves: list[BundleMove], blocked: list[Blocked]) -> None:
    plain = {p.part_id: p.motif for p in bundle.parts}
    delete_broader = bundle.semantics == "all"
    direction = "deleted_is_broader" if delete_broader else "deleted_is_narrower"

    def keeps(cand: str, other: str) -> bool:
        """True if ``cand`` is the retained side of the duplicate pair ``{cand, other}``."""
        if bundle.anchor_part in (cand, other):
            return cand == bundle.anchor_part
        return cand < other

    for part in sorted(bundle.parts, key=lambda p: p.part_id):
        pid = part.part_id
        if bundle.semantics is None:
            reason = "unknown_bundle_semantics"
        elif len(bundle.parts) < 2:
            reason = "last_part"
        elif pid == bundle.anchor_part:
            reason = "anchor_part_protected"
        elif _has_absent(part.motif):
            reason = "has_absent_node"
        else:
            found = _find_cover(pid, plain, delete_broader, keeps, ctx)
            if isinstance(found, _Cover):
                child = bundle.model_copy(update={"parts": tuple(p for p in bundle.parts if p.part_id != pid)})
                record = _record(pid, "bundle_part", found.rule, pid, part.motif, found.cover, direction,
                                 found.certificate)
                moves.append(BundleMove(child, record, found.certificate))
            elif found is not None:
                blocked.append(Blocked(OP, pid, *found))
            continue
        blocked.append(Blocked(OP, pid, reason, {}))


def motif_deletion(bundle: MotifBundle, ctx: GenContext) -> BundleOperatorResult:
    moves: list[BundleMove] = []
    blocked: list[Blocked] = []
    _scope_a(bundle, ctx, moves, blocked)
    return BundleOperatorResult(moves, blocked)
