"""Shared operator interfaces.

Conventions for every operator:
- ``target`` is a node id, or ``"s->t"`` for an edge; ``field`` names the changed
  field (``"code"`` for a concept lift).
- ``before``/``after`` hold a code string, a relation string, an ``Interval.to_json()``
  dict, or None.
- ``evidence``/``detail`` hold only JSON-safe values (str, int, float, bool, None and
  lists/dicts of those), with lists sorted or otherwise in a deterministic order.
- Operators are pure: they never mutate the input motif.
- ``concept_lift`` blocked reasons: ``carries_value``, ``concept_dependent_attr``,
  ``no_floor`` (non-Disorder), ``unmapped`` (no PhecodeX anchors), ``inactive_parent``
  and ``outside_floor`` (a parent's active descendant leaves the child's anchors).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from semgen.config import GenConfig
from semgen.floors import FloorDecision
from semgen.model import Edge, Motif
from semgen.snomed import Hierarchy

CLINICAL_TYPES = frozenset({"Disorder", "Substance", "Observable", "Procedure", "Finding"})


class FloorPolicy(Protocol):
    def check_lift(self, child: str, parent: str) -> FloorDecision: ...

    @property
    def provenance(self) -> dict: ...


@dataclass(frozen=True)
class GenContext:
    hierarchy: Hierarchy
    config: GenConfig
    floors: FloorPolicy


@dataclass(frozen=True)
class ChangeRecord:
    op: str
    target: str
    field: str
    before: Any
    after: Any
    evidence: dict

    def to_json(self) -> dict:
        return {"op": self.op, "target": self.target, "field": self.field,
                "before": self.before, "after": self.after, "evidence": self.evidence}


@dataclass(frozen=True)
class Move:
    child: Motif
    change: ChangeRecord


@dataclass(frozen=True)
class Blocked:
    op: str
    target: str
    reason: str
    detail: dict

    def to_json(self) -> dict:
        return {"op": self.op, "target": self.target, "reason": self.reason, "detail": self.detail}


@dataclass(frozen=True)
class OperatorResult:
    moves: list[Move] = field(default_factory=list)
    blocked: list[Blocked] = field(default_factory=list)


Operator = Callable[[Motif, GenContext], OperatorResult]


def is_absent_touching(motif: Motif, edge: Edge) -> bool:
    """True if either endpoint of ``edge`` is an absent (negated) node."""
    return any(motif.node(i).polarity == "absent" for i in (edge.s, edge.t))
