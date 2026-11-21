"""Motif deletion (spec §4), a bundle operator: drop a part whose removal keeps the bundle's match set.

By the bundle's declared semantics (``None`` = unknown: every deletion blocks):
- ``"all"`` (A AND B): a part goes when the other parts together imply it (pairwise: a retained S with ``S ⊑ G``
  makes the broader G redundant, ``S AND G = S``);
- ``"any"`` (A OR B): a part goes when it implies the disjunction of the others (pairwise: a retained G with
  ``S ⊑ G`` makes the narrower S redundant, ``S OR G = G``).

This module only proposes. For each deletable part it looks for a cheap certificate (an exact duplicate, then a
containment map from one other part, ``containment_search``) and otherwise proposes the removal against the whole
expression; the independent checker (``semgen.order.decide_part_removal``) decides every proposal, and only a
``VALID`` verdict becomes a move. Exact duplicates (isomorphic up to node ids): the larger ``part_id`` goes, unless it
is the anchor part, then the other one; the retained side of a duplicate pair is not proposed. The anchor part and
the last part are never deleted. Every move is ``kept``; its evidence keeps the deleted part's id and canonical JSON,
the covering part (if one part covers it) and the direction.
"""
from __future__ import annotations

from semgen.bundle import MotifBundle
from semgen.canonical import canonical_json, structural_signature
from semgen.interfaces import Blocked, BundleMove, BundleOperatorResult, ChangeRecord, GenContext
from semgen.model import Motif
from semgen.operators.containment_search import find_containment, find_isomorphism
from semgen.order import decide_part_removal

OP = "motif_deletion"


def _duplicate_map(deleted: Motif, kept: Motif, delete_broader: bool) -> dict[str, str] | None:
    """For an exact duplicate, the map in the direction the rule needs (``{G node: S node}``), or None. The
    signature only filters; the isomorphism confirms; the checker re-verifies the map."""
    if structural_signature(deleted) != structural_signature(kept):
        return None
    iso = find_isomorphism(deleted, kept)   # deleted id -> kept id
    if iso is None:
        return None
    return iso if delete_broader else dict(sorted((v, k) for k, v in iso.items()))


def _proposal(pid: str, motifs: dict[str, Motif], bundle: MotifBundle,
              ctx: GenContext) -> tuple[str, str | None, dict[str, str] | None] | None:
    """``(rule, covering part, certificate)`` for part ``pid``; None when ``pid`` is the retained side of a duplicate."""
    delete_broader = bundle.semantics == "all"
    m, others = motifs[pid], sorted(set(motifs) - {pid})
    retained_duplicate = False
    for o in others:
        if (cert := _duplicate_map(m, motifs[o], delete_broader)) is None:
            continue
        if bundle.anchor_part == pid or (bundle.anchor_part != o and pid < o):
            retained_duplicate = True   # this part is the one the duplicate rule keeps
            continue
        return "exact_duplicate", o, cert
    if retained_duplicate:
        return None
    for o in others:
        narrow, broad = (motifs[o], m) if delete_broader else (m, motifs[o])
        if (cert := find_containment(narrow, broad, ctx)) is not None:
            return "query_contained", o, cert
    return "expression_redundant", None, None


def motif_deletion(bundle: MotifBundle, ctx: GenContext) -> BundleOperatorResult:
    moves: list[BundleMove] = []
    blocked: list[Blocked] = []
    motifs = {p.part_id: p.motif for p in bundle.parts}
    direction = "deleted_is_broader" if bundle.semantics == "all" else "deleted_is_narrower"
    for part in sorted(bundle.parts, key=lambda p: p.part_id):
        pid = part.part_id
        if bundle.semantics is None:
            blocked.append(Blocked(OP, pid, "unknown_bundle_semantics", {}))
            continue
        if len(bundle.parts) < 2:
            blocked.append(Blocked(OP, pid, "last_part", {}))
            continue
        if pid == bundle.anchor_part:
            blocked.append(Blocked(OP, pid, "anchor_part_protected", {}))
            continue
        found = _proposal(pid, motifs, bundle, ctx)
        if found is None:
            continue
        rule, cover, cert = found
        verdict = decide_part_removal(bundle, pid, ctx, cert)
        if not verdict.ok:
            blocked.append(Blocked(OP, pid, verdict.reason, {"status": verdict.status} | verdict.evidence))
            continue
        cover = cover if rule != "expression_redundant" else verdict.evidence.get("covered_by")
        evidence = {"scope": "bundle_part", "deleted": pid, "deleted_canonical": canonical_json(part.motif),
                    "subsumed_by": cover, "direction": direction, "mapping": cert or {},
                    "verdict": verdict.reason}
        child = bundle.model_copy(update={"parts": tuple(p for p in bundle.parts if p.part_id != pid)})
        moves.append(BundleMove(child, ChangeRecord(OP, pid, "part", pid, None, evidence, meaning="kept",
                                                    rule_id=f"motif.delete.{rule}"), cert or {}))
    return BundleOperatorResult(moves, blocked)
