"""Generalization operators. Later tasks append to ALL_OPERATORS (fixed order)."""
from semgen.operators.concept_lift import concept_lift

ALL_OPERATORS = [concept_lift]
