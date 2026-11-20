"""Relevance gate for attribute deletion: the declared cohort definition decides (design §7.2).

Every deletion candidate (any field of any patient-level node or edge; nothing is listed by name) is assessed from
the bundle's declared ``CohortDefinition`` alone:

| declaration      | decision    |
|------------------|-------------|
| ``required``     | ``retain``  (deletion rejected)                    |
| ``relaxable``    | ``relaxable`` (a candidate; the lattice guard and ``check_order`` must still accept it) |
| not declared     | ``unknown`` (deletion blocked; nothing is inferred from the absence) |

How the constrained node relates to the anchor (a path in the motif or in a knowledge graph) does not decide
necessity: being connected to the anchor does not make every attribute of a node mandatory, and no path is read as
irrelevance. A ``relaxable`` declaration that conflicts with another explicit requirement (``conflicts``, e.g. the
attribute definitions mark the attribute concept-dependent) is ``unknown``: a requirement is never overridden.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from semgen.interfaces import GenContext


def assess(target: str, field: str, ctx: GenContext, conflicts: tuple[str, ...] = ()) -> dict:
    """Assess one deletion candidate; ``target``/``field`` are the ChangeRecord keys the cohort definition uses."""
    cohort = ctx.cohort
    need = cohort.necessity(target, field) if cohort is not None else "unknown"
    necessity = {"status": need, "source": None if cohort is None else {"id": cohort.id, "version": cohort.version,
                                                                         "source": cohort.source}}
    if need == "required":
        decision, reason = "retain", "required by the declared cohort definition"
    elif need == "unknown":
        decision, reason = "unknown", ("no cohort definition declared" if cohort is None
                                       else "the cohort definition does not declare this constraint")
    elif conflicts:
        decision, reason = "unknown", "conflict: declared relaxable, but " + "; ".join(conflicts)
    else:
        decision, reason = "relaxable", "declared relaxable by the cohort definition"
    return {"field": field, "decision": decision, "reason": reason, "necessity": necessity}
