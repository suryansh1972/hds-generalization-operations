"""Shared operator interfaces.

Conventions for every operator:
- ``target`` is a node id, or ``"s->t"`` for an edge; ``field`` names the changed
  field (``"code"`` for a concept lift).
- ``before``/``after`` hold a code string, a relation string, an ``Interval.to_json()``
  dict, or None.
- ``evidence``/``detail`` hold only JSON-safe values (str, int, float, bool, None and
  lists/dicts of those), with lists sorted or otherwise in a deterministic order.
- Operators are pure: they never mutate the input motif.
- ``concept_lift`` blocked reasons: ``unknown_concept``, ``carries_value``, ``concept_dependent_attr``, ``no_parent``, ``inactive_parent``;
  from the selected floor policy: snomed_boundary gives ``no_semantic_tag``, ``semantic_tag_changed``,
  ``excluded_ancestor_root`` and ``above_descendant_ceiling``; phecodex gives ``unmapped`` (no PhecodeX
  anchors, any SNOMED-coded node) and ``outside_floor`` (a parent's active descendant leaves the child's anchors).
- ``attribute_removal`` blocked reason: ``concept_dependent_attr`` (detail ``{"attr": name}``);
  only a value or a concept-independent attribute may be removed.
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
# Why a climb stops: the policy boundary, the top of the hierarchy, or any other reason (a restriction on the node).
BOUNDARY_REASONS = frozenset({"outside_floor", "above_descendant_ceiling", "semantic_tag_changed",
                              "excluded_ancestor_root", "inactive_parent"})
TOP_REASONS = frozenset({"no_parent"})


class FloorPolicy(Protocol):
    """Decides whether a concept may lift to a parent; ``provenance`` carries ``mode`` and is written to the run header.

    ``anchors`` is the policy's containment set (empty for snomed_boundary, which has none).
    """

    def check_lift(self, child: str, parent: str) -> FloorDecision: ...

    def anchors(self, c: str) -> frozenset[str]: ...

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
