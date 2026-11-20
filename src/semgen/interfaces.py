"""Operator interfaces and the generation context shared by every layer (operators, order proofs, lattice).

This module imports only domain modules (model, bundle, config, snomed, lift) and never ``semgen.operators``,
so ``semgen.order``, ``semgen.refrange`` and the operators can all depend on it without an import cycle.

Conventions for every operator:
- ``target`` is a node id, or ``"s->t"`` for an edge; ``field`` names the changed
  field (``"code"`` for a concept lift).
- ``before``/``after`` hold a code string, a relation string, an ``Interval.to_json()``
  dict, or None.
- ``evidence``/``detail`` hold only JSON-safe values (str, int, float, bool, None and
  lists/dicts of those), with lists sorted or otherwise in a deterministic order.
- Operators are pure: they never mutate the input motif.
- ``concept_lift`` blocked reasons: ``unknown_concept``, ``carries_value``, ``concept_dependent_attr``, ``no_parent``,
  then per parent the ``semgen.lift`` transition reason (``REJECT_REASONS`` or ``UNKNOWN_REASONS``) with detail
  ``parent``, ``decision`` (rejected | unknown), ``transition`` (every rule's outcome and evidence), ``fingerprint``.
  The lattice also reports ``carries_value`` for a lift of a node with A1 observations.
- ``normative_bucketing`` blocked reasons (``semgen.refrange``): ``result_range_unverified`` (detail ``check``),
  ``subject_context_missing`` (detail ``missing``), ``subject_sex_unrecognised`` (Mayo path, only when a
  candidate row partitions on sex and ``subject.sex`` is not in the source's own ``ranges.sex`` vocabulary; detail
  ``sex``, ``known``), ``no_test_identity``, ``mayo_unavailable``,
  ``no_test_mapping``, ``specimen_mismatch``, ``ambiguous_test_mapping``, ``no_applicable_range``,
  ``ambiguous_range``, ``units_not_convertible``.
- ``attribute_deletion`` blocked reasons: ``concept_dependent_attr`` (detail ``{"attr": name}``); only a
  value, date, window (or bound), A1 observation or concept-independent attribute may be deleted; and from the
  relevance gate (``semgen.relevance``: the declared cohort definition alone) ``relevance_retain`` (declared
  required) / ``relevance_unknown`` (undeclared, no cohort, or relaxable in conflict with the attribute definitions;
  detail = the assessment: field, decision, reason, necessity).
- ``motif_deletion`` (a bundle operator) blocked reasons, ``target`` a part id: ``unknown_bundle_semantics``,
  ``last_part``, ``anchor_part_protected``, ``has_absent_node``, ``snomed_mapping_missing`` (detail
  ``inactive_codes``), ``not_contained``.
- ``attribute_aggregation`` blocked reasons: ``measurement_identity_unknown``, ``measurement_identity_differs``,
  ``observation_has_other_edges``, ``observation_has_attrs``, ``observation_not_attached``,
  ``observation_edges_differ``, ``anchor_would_be_removed``, ``unit_validation_unavailable``, ``unit_invalid`` (A1);
  ``ontology_evidence_unknown``, ``multiple_minimal_ancestors``, ``lcs_outside_floor``, ``group_types_differ``,
  ``group_edges_differ`` (A3).
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

from semgen.bundle import MotifBundle
from semgen.config import GenConfig
from semgen.lift import REJECT_REASONS, FloorDecision
from semgen.model import Edge, Motif
from semgen.snomed import Hierarchy

if TYPE_CHECKING:
    from semgen.bundle import CohortDefinition, Subject
    from semgen.refrange import MayoSource
    from semgen.ucum import Ucum

# Why a climb stops: an ontology-derived rejection (the floor), the top of the hierarchy, or anything else
# (an unknown transition or a restriction on the node).
BOUNDARY_REASONS = REJECT_REASONS - {"hierarchy_root"}
TOP_REASONS = frozenset({"no_parent", "hierarchy_root"})


class CodeTable(Protocol):
    """A pinned terminology table for one code system (e.g. a LOINC release): ``lookup`` returns at least
    ``{"status": ...}`` for a code, ``{"status": "not_found"}`` when absent (adapter contract; none configured)."""

    def lookup(self, code: str) -> dict: ...


class FloorPolicy(Protocol):
    """Decides one concept-lift step (``semgen.lift.SnomedLift``). ``concept_model`` and ``fingerprint`` feed the
    independent verifier in the lattice guard; ``provenance`` is written to the run header."""

    concept_model: Any
    fingerprint: str

    def check_lift(self, child: str, parent: str, *, role: str | None = None, node_id: str | None = None,
                   cohort=None) -> FloorDecision: ...

    @property
    def provenance(self) -> dict: ...


@dataclass(frozen=True)
class GenContext:
    hierarchy: Hierarchy
    config: GenConfig
    floors: FloorPolicy
    refranges: MayoSource | None = None   # None: the Mayo DB is unavailable (bucketing blocks mayo_unavailable)
    subject: Subject | None = None        # selection context of the bundle; None for a bare motif
    cohort: CohortDefinition | None = None   # declared cohort definition of the bundle; None = undeclared
    ucum: Ucum | None = None                 # pinned UCUM essence (A1 unit validation); None = A1 blocks
    code_tables: Mapping[str, CodeTable] = field(default_factory=dict)  # test.system -> code table (none today)
    operators: OperatorSet | None = None     # None = the built-in set (``semgen.operators.default_operators()``)


@dataclass(frozen=True)
class ChangeRecord:
    op: str
    target: str
    field: str
    before: Any
    after: Any
    evidence: dict
    meaning: Literal["kept", "generalized"] = "generalized"  # kept = match set provably unchanged
    rule_id: str | None = None   # readers treat a missing rule_id as equal to ``op``
    source: dict | None = None   # pinned source evidence (kind, sha256, ...)

    def to_json(self) -> dict:
        # Defaults are omitted so records built without the new fields (concept lift) export unchanged.
        out = {"op": self.op, "target": self.target, "field": self.field,
               "before": self.before, "after": self.after, "evidence": self.evidence}
        if self.meaning != "generalized":
            out["meaning"] = self.meaning
        if self.rule_id is not None:
            out["rule_id"] = self.rule_id
        if self.source is not None:
            out["source"] = self.source
        return out


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


@dataclass(frozen=True)
class BundleMove:
    """A bundle-level move with the certificate the order checker re-verifies: for a deletion the containment map
    ``{broad node id: narrow node id}`` (design §6)."""

    child: MotifBundle
    change: ChangeRecord
    certificate: dict[str, str]


@dataclass(frozen=True)
class BundleOperatorResult:
    moves: list[BundleMove] = field(default_factory=list)
    blocked: list[Blocked] = field(default_factory=list)


BundleOperator = Callable[[MotifBundle, GenContext], BundleOperatorResult]


def is_absent_touching(motif: Motif, edge: Edge) -> bool:
    """True if either endpoint of ``edge`` is an absent (negated) node."""
    return any(motif.node(i).polarity == "absent" for i in (edge.s, edge.t))


@dataclass(frozen=True)
class OperatorSet:
    """The operators a lattice run applies, in order: per-motif operators on every part, then bundle operators.

    Immutable: build a new set with ``with_operator`` / ``without`` instead of mutating a registry. Every move an
    operator proposes still passes the lattice guard and the independent order proof, so an added operator can
    widen what is explored but cannot make an unsound candidate reach the output.
    """

    motif: tuple[Operator, ...] = ()
    bundle: tuple[BundleOperator, ...] = ()

    @staticmethod
    def name_of(op: Any) -> str:
        return str(getattr(op, "op_name", None) or getattr(op, "__name__", repr(op)))

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self.name_of(op) for op in (*self.motif, *self.bundle))

    def with_operator(self, op: Any, *, bundle: bool = False, before: str | None = None) -> OperatorSet:
        """A new set with ``op`` appended (or inserted before the operator named ``before``)."""
        name = self.name_of(op)
        if name in self.names:
            raise ValueError(f"operator {name!r} is already in the set")
        seq: list[Any] = list(self.bundle if bundle else self.motif)
        if before is None:
            seq.append(op)
        else:
            idx = [self.name_of(o) for o in seq]
            if before not in idx:
                raise ValueError(f"no operator {before!r} to insert before")
            seq.insert(idx.index(before), op)
        return OperatorSet(self.motif, tuple(seq)) if bundle else OperatorSet(tuple(seq), self.bundle)

    def without(self, *names: str) -> OperatorSet:
        unknown = set(names) - set(self.names)
        if unknown:
            raise ValueError(f"unknown operators {sorted(unknown)}")
        return OperatorSet(tuple(o for o in self.motif if self.name_of(o) not in names),
                           tuple(o for o in self.bundle if self.name_of(o) not in names))

    def only(self, *names: str) -> OperatorSet:
        return self.without(*(n for n in self.names if n not in names))
