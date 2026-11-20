"""Run a lattice with a chosen per-motif operator list (the bundle operators stay the built-in ones)."""
import dataclasses

from semgen.interfaces import GenContext, OperatorSet
from semgen.operators import BUNDLE_OPERATORS


def with_ops(ctx: GenContext, *ops) -> GenContext:
    return dataclasses.replace(ctx, operators=OperatorSet(tuple(ops), BUNDLE_OPERATORS))
