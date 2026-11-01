"""PhecodeFloorPolicy: deterministic containment rule deciding whether a disorder may lift to a parent (DRAFT)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from semgen.config import FloorSourceConfig
from semgen.icd10map import Icd10Map, load_icd10_map
from semgen.phecodex import PhecodeX, truncate
from semgen.snomed import Hierarchy
from semgen.sources import default_phecodex_dir, verify_phecodex


@dataclass(frozen=True)
class FloorDecision:
    ok: bool
    reason: str | None
    detail: dict = field(default_factory=dict)


def _copy(d: FloorDecision) -> FloorDecision:
    return FloorDecision(d.ok, d.reason,
                         {k: list(v) if isinstance(v, list) else v for k, v in d.detail.items()})


class PhecodeFloorPolicy:
    def __init__(self, hierarchy: Hierarchy, icd_map: Icd10Map, phecodex: PhecodeX, level: str) -> None:
        truncate("X_1", level)  # validates level
        self._h = hierarchy
        self._icd = icd_map
        self._px = phecodex
        self.level = level
        self._phecodes: dict[str, frozenset[str]] = {}
        self._anchors: dict[str, frozenset[str]] = {}
        self._memo: dict[tuple[str, frozenset[str]], FloorDecision] = {}

    @classmethod
    def from_config(cls, hierarchy: Hierarchy, terminology_dir: str | Path, src: FloorSourceConfig,
                    phecodex_dir: Path | None = None) -> PhecodeFloorPolicy:
        d = Path(phecodex_dir) if phecodex_dir is not None else default_phecodex_dir(src)
        verify_phecodex(d, src)  # SourceError on missing/tampered; never silently "no floors"
        icd = load_icd10_map(terminology_dir, src.icd10_map_refset, src.map_rules)
        return cls(hierarchy, icd, PhecodeX.load(d), src.phecode_level)

    @property
    def provenance(self) -> dict:
        return {"floor_source": "phecodex", "phecode_level": self.level,
                "icd10_map_refset": self._icd.refset_id, "icd10_map_release": self._icd.release}

    def phecodes(self, c: str) -> frozenset[str]:
        got = self._phecodes.get(c)
        if got is None:
            got = frozenset(p for t in self._icd.targets(c) for p in self._px.phecodes_for_icd(t)[0])
            self._phecodes[c] = got
        return got

    def anchors(self, c: str) -> frozenset[str]:
        got = self._anchors.get(c)
        if got is None:
            a = {truncate(p, self.level) for p in self.phecodes(c)}
            got = frozenset(q for q in a if not any(r != q and self._px.rolls_up(r, q) for r in a))
            self._anchors[c] = got
        return got

    def _inside(self, x: str, q: str) -> bool:
        rolls = self._px.rolls_up
        return any(rolls(p, q) or rolls(truncate(p, self.level), q) for p in self.phecodes(x))

    def check_lift(self, child: str, parent: str) -> FloorDecision:
        anchors = self.anchors(child)
        if not anchors:
            return FloorDecision(False, "unmapped", {"code": child})
        if not self._h.is_active(parent):
            return FloorDecision(False, "inactive_parent", {"parent": parent})
        key = (parent, anchors)
        hit = self._memo.get(key)
        if hit is None:
            hit = self._compute(parent, anchors)
            self._memo[key] = hit
        return _copy(hit)

    def _compute(self, parent: str, anchors: frozenset[str]) -> FloorDecision:
        ordered = sorted(anchors)
        checked = 0
        for d in sorted(self._h.descendants_or_self(parent)):
            if not self._h.is_active(d):
                continue
            checked += 1
            for q in ordered:
                if not self._inside(d, q):
                    return FloorDecision(False, "outside_floor", {
                        "parent": parent, "blocking_descendant": d,
                        "blocking_fsn": self._h.fsn(d), "anchor": q})
        return FloorDecision(True, None, {"anchors": ordered, "phecode_level": self.level,
                                          "checked_descendants": checked})
