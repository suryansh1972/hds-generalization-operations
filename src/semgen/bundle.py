"""Motif bundles: all motifs of one patient/episode, joined at the shared patient node (design §5.2).

A bundle of one plain part hashes exactly like its motif, so single-motif runs keep every existing hash.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal, Self

from pydantic import model_validator

from semgen.canonical import canonical_json, motif_hash
from semgen.model import Motif, _Frozen


class Subject(_Frozen):
    """Selection context only (sex, age in days); immutable within a lattice run."""

    sex: str | None = None
    age_days: int | None = None


class CohortConstraint(_Frozen):
    """One declared constraint of the cohort definition: ``target``/``field`` as in a ChangeRecord."""

    target: str
    field: str
    necessity: Literal["required", "relaxable"]


class CohortDefinition(_Frozen):
    """The declared cohort definition (design §5.2 rev 4): selection context, immutable within a run.

    A constraint it does not list has necessity ``unknown``; nothing is inferred from its absence.
    """

    id: str
    version: str
    source: str
    constraints: tuple[CohortConstraint, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> Self:
        keys = [(c.target, c.field) for c in self.constraints]
        if len(keys) != len(set(keys)):
            raise ValueError(f"cohort {self.id}: a (target, field) is declared more than once")
        return self

    def necessity(self, target: str, field: str) -> str:
        for c in self.constraints:
            if (c.target, c.field) == (target, field):
                return c.necessity
        return "unknown"


class MotifPart(_Frozen):
    part_id: str   # the root motif_id
    motif: Motif

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.part_id != self.motif.motif_id:
            raise ValueError(f"part id {self.part_id!r} differs from its motif_id {self.motif.motif_id!r}")
        return self


class MotifBundle(_Frozen):
    """The parts joined by ``semantics``: ``"all"`` (AND: a patient matches every part) or ``"any"`` (OR: some
    part); grouped OR alternatives are an ``"any"`` bundle of plain parts. ``None`` is unknown."""

    bundle_id: str
    semantics: Literal["all", "any"] | None   # None = unknown: never read as "all" (D4)
    anchor_part: str
    parts: tuple[MotifPart, ...]
    subject: Subject | None = None
    cohort: CohortDefinition | None = None   # selection context like subject (rev 4); excluded from the hash

    @model_validator(mode="after")
    def _check(self) -> Self:
        ids = [p.part_id for p in self.parts]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError(f"bundle {self.bundle_id}: part ids {ids} must be non-empty and distinct")
        if self.anchor_part not in ids:
            raise ValueError(f"bundle {self.bundle_id}: anchor part {self.anchor_part!r} is not a part")
        return self

    @classmethod
    def of(cls, motif: Motif) -> MotifBundle:
        return cls(bundle_id=motif.motif_id, semantics="all", anchor_part=motif.motif_id,
                   parts=(MotifPart(part_id=motif.motif_id, motif=motif),))

    def part(self, part_id: str) -> MotifPart:
        for p in self.parts:
            if p.part_id == part_id:
                return p
        raise KeyError(part_id)

    @property
    def is_single(self) -> bool:
        return len(self.parts) == 1

    @property
    def single_motif(self) -> Motif:
        if not self.is_single:
            raise ValueError(f"bundle {self.bundle_id} is not a single plain part")
        return self.parts[0].motif


def _part_obj(p: MotifPart) -> dict:
    return {"part_id": p.part_id, "motif": json.loads(canonical_json(p.motif))}


def bundle_canonical_json(b: MotifBundle) -> str:
    """A bundle of one plain part is its motif's canonical JSON; otherwise semantics, anchor and sorted parts.

    ``bundle_id``, ``subject`` and ``cohort`` are excluded (both are immutable within a run; the order checker enforces
    it).
    """
    if b.is_single:
        return canonical_json(b.single_motif)
    obj = {"semantics": b.semantics, "anchor_part": b.anchor_part,
           "parts": [_part_obj(p) for p in sorted(b.parts, key=lambda p: p.part_id)]}
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def bundle_hash(b: MotifBundle) -> str:
    if b.is_single:
        return motif_hash(b.single_motif)
    return hashlib.sha256(bundle_canonical_json(b).encode("utf-8")).hexdigest()[:16]
