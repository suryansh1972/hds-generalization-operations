"""SnomedBoundaryPolicy: DRAFT floor bounding concept lift by SNOMED CT alone (tag, exclusions, breadth ceiling)."""
from __future__ import annotations

from semgen.config import ConfigError, SnomedBoundaryConfig
from semgen.floors import FloorDecision
from semgen.snomed import Hierarchy

STATUS = "DRAFT — computational heuristic, not clinically validated"
TAG_RULE = "parent must keep the child's FSN semantic tag"


class SnomedBoundaryPolicy:
    def __init__(self, hierarchy: Hierarchy, cfg: SnomedBoundaryConfig) -> None:
        if cfg.characteristic_type != hierarchy.characteristic_type:
            raise ConfigError(f"snomed_boundary characteristic_type {cfg.characteristic_type!r} "
                              f"does not match hierarchy {hierarchy.characteristic_type!r}")
        self._h = hierarchy
        self._cfg = cfg
        # FsnError propagates for unresolved/ambiguous/retired roots; sorted by concept id for determinism.
        self._roots = sorted((hierarchy.resolve_fsn(r.fsn), r.fsn, r.reason) for r in cfg.excluded_ancestor_roots)

    @property
    def provenance(self) -> dict:
        return {"mode": "snomed_boundary", "status": STATUS,
                "max_descendants": self._cfg.max_descendants,
                "characteristic_type": self._cfg.characteristic_type,
                "semantic_tag_rule": TAG_RULE,
                "excluded_ancestor_roots": [{"concept_id": c, "fsn": f, "reason": r} for c, f, r in self._roots],
                "snomed_release": self._h.release, "snomed_edition": self._h.edition}

    def anchors(self, c: str) -> frozenset[str]:
        return frozenset()

    def check_lift(self, child: str, parent: str) -> FloorDecision:
        h = self._h
        if not h.is_active(parent):
            return FloorDecision(False, "inactive_parent", {"parent": parent})
        ct, pt = h.semantic_tag(child), h.semantic_tag(parent)
        if ct is None or pt is None:
            return FloorDecision(False, "no_semantic_tag", {"parent": parent, "child_tag": ct, "parent_tag": pt})
        if ct != pt:
            return FloorDecision(False, "semantic_tag_changed", {"parent": parent, "child_tag": ct, "parent_tag": pt})
        for cid, fsn, reason in self._roots:
            if h.is_descendant_or_self(parent, cid):
                return FloorDecision(False, "excluded_ancestor_root", {
                    "parent": parent, "excluded_root": cid, "excluded_fsn": fsn, "reason": reason})
        n, ceiling = h.descendant_count(parent), self._cfg.max_descendants
        if n > ceiling:
            return FloorDecision(False, "above_descendant_ceiling",
                                 {"parent": parent, "descendant_count": n, "ceiling": ceiling})
        return FloorDecision(True, None, {"descendant_count": n, "ceiling": ceiling, "semantic_tag": ct})
