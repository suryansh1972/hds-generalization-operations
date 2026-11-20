"""Generalization operators in fixed order (the lattice applies them in this order): per-motif operators on every
part, then bundle operators.

Per-motif: concept lift, normative bucketing, attribute deletion, attribute aggregation (A1 repeated observations,
A3 SNOMED CT grouping). Bundle: motif deletion. There is no motif aggregation operator: grouping OR alternatives is
an ``"any"`` bundle of plain parts, which needs no generalization move.

The built-in set is ``default_operators()``; a run uses ``GenContext.operators`` when set (see
``semgen.interfaces.OperatorSet``). ``ALL_OPERATORS`` / ``BUNDLE_OPERATORS`` are immutable tuples kept for reading.
"""
from semgen.interfaces import OperatorSet
from semgen.operators.attribute_aggregation import attribute_aggregation
from semgen.operators.attribute_deletion import attribute_deletion
from semgen.operators.concept_lift import concept_lift

# Imported under a private name so that ``semgen.operators.motif_deletion`` stays the module (tests patch it).
from semgen.operators.motif_deletion import motif_deletion as _motif_deletion
from semgen.operators.normative_bucketing import normative_bucketing

ALL_OPERATORS = (concept_lift, normative_bucketing, attribute_deletion, attribute_aggregation)
BUNDLE_OPERATORS = (_motif_deletion,)
_DEFAULT = OperatorSet(ALL_OPERATORS, BUNDLE_OPERATORS)


def default_operators() -> OperatorSet:
    """The built-in operator set, in the order the lattice applies it."""
    return _DEFAULT


__all__ = ["ALL_OPERATORS", "BUNDLE_OPERATORS", "OperatorSet", "attribute_aggregation", "attribute_deletion",
           "concept_lift", "default_operators", "normative_bucketing"]
