"""Test-only relevance double: run operator-mechanics tests as if every deletion candidate were declared relaxable.

The relevance gate itself is tested in tests/test_relevance.py; this double exists so tests about what a deletion
does (proofs, lattices, monotonicity) keep exercising deletion moves. Never imported by ``src/``.
"""
import dataclasses

from semgen.bundle import CohortDefinition


class RelaxEverything(CohortDefinition):
    def necessity(self, target: str, field: str) -> str:
        return "relaxable"


RELAX_ALL = RelaxEverything(id="test:relax-all", version="0", source="tests/support/relevance.py")


def relaxed(ctx):
    return dataclasses.replace(ctx, cohort=RELAX_ALL)


def relaxed_bundle(bundle):
    return bundle.model_copy(update={"cohort": RELAX_ALL})
