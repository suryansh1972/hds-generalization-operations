"""Generalization operators. Later tasks append to ALL_OPERATORS (fixed order)."""
from semgen.operators.attribute_removal import attribute_removal
from semgen.operators.concept_lift import concept_lift

ALL_OPERATORS = [concept_lift, attribute_removal]
