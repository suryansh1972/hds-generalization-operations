"""Independent verifier for concept-lift steps (does not import or call ``semgen.lift``).

It re-derives every check from the raw release data with different logic than the generator:
- activity and the inferred IS-A edge (read from ``Hierarchy.parents``);
- the boundary: the parent is not parentless, not a child of only parentless concepts, keeps the FSN tag (own regex),
  is not an MRCM domain's focus, and lies in every evaluable MRCM domain containing the child (own ECL evaluation over
  the ancestor closure);
- the concept model by value subsumption: for every defining relationship (type, value) of the child the parent has
  one of the same type whose value is the child's value or an IS-A ancestor of it (concrete values: equal), not all
  of them reduced to a focus of the attribute's MRCM range, and no fewer relationship groups; the child must have at least one defining relationship;
- OWL: both concepts carry an axiom and the RF2 definition status matches it;
- the record: an ``accepted`` transition for exactly this child/parent, produced under the same release fingerprint.
A path additionally has to start at the original concept and be a chain of such steps.
Concept-level only: it says nothing about motif containment (``semgen.order`` proves that).
"""
from __future__ import annotations

import re

from semgen.concept_model import ConceptModel
from semgen.snomed import Hierarchy

_TAG = re.compile(r"\(([^()]+)\)\s*$")


def _member(h: Hierarchy, c: str, op: str | None, focus: str | None) -> bool:
    up = h.ancestors_or_self(c)
    return {"<<": focus in up, "<": focus in up and c != focus, "": c == focus}.get(op, False)


def verify_transition(h: Hierarchy, cm: ConceptModel, child: str, parent: str, record: dict | None,
                      fingerprint: str | None, expected_fingerprint: str | None) -> list[str]:
    """Problems with one applied step (empty = verified). ``record`` is the generator's transition JSON or None."""
    p: list[str] = []
    if not h.is_active(child) or not h.is_active(parent):
        return ["inactive_concept"]
    if child == parent or parent not in h.parents(child):
        return ["not_an_inferred_parent"]
    roots = {a for a in h.ancestors_or_self(child) if not h.parents(a)}
    if parent in roots or h.parents(parent) <= roots:
        p.append("reaches_hierarchy_top")
    tags = [_TAG.search(h.fsn(x) or "") for x in (child, parent)]
    if not all(tags) or tags[0].group(1) != tags[1].group(1):
        p.append("semantic_tag_not_preserved")
    if cm.mrcm is None:
        p.append("mrcm_missing")
    else:
        for d in cm.mrcm.domains:
            if d.operator is None:
                continue
            if d.focus == parent:
                p.append(f"parent_is_domain:{d.concept}")
            elif _member(h, child, d.operator, d.focus) and not _member(h, parent, d.operator, d.focus):
                p.append(f"domain_left:{d.concept}")
    crel, prel = cm.attributes.get(child, ()), cm.attributes.get(parent, ())
    ccon, pcon = cm.concrete.get(child, ()), cm.concrete.get(parent, ())
    if not crel and not ccon:
        p.append("no_defining_evidence")
    for t, v, _ in crel:
        up = h.ancestors_or_self(v)
        if not any(pt == t and pv in up for pt, pv, _ in prel):
            p.append(f"relationship_not_subsumed:{t}={v}")
    if cm.mrcm is not None:
        for t in sorted({t for t, _, _ in crel}):
            foci = {f for _, f in cm.mrcm.attribute_ranges.get(t) or ()}
            cv = {v for tt, v, _ in crel if tt == t}
            pv = {v for tt, v, _ in prel if tt == t}
            if foci and pv and all(v in foci for v in pv) and any(v not in foci for v in cv):
                p.append(f"attribute_reduced_to_range_focus:{t}")
    for t, v, _ in ccon:
        if not any(pt == t and pv == v for pt, pv, _ in pcon):
            p.append(f"concrete_value_not_kept:{t}={v}")
    groups = lambda rs: len({g for *_, g in rs if g != "0"})   # noqa: E731
    if groups(prel + pcon) < groups(crel + ccon):
        p.append("relationship_groups_lost")
    for x in (child, parent):
        if not cm.owl_available or x not in cm.owl_axiom:
            p.append(f"no_owl_axiom:{x}")
        elif (x in cm.owl_defined) == (x in cm.primitive):
            p.append(f"definition_status_mismatch:{x}")
    if record is not None:
        if (record.get("child"), record.get("parent"), record.get("decision")) != (child, parent, "accepted"):
            p.append("record_mismatch")
    if fingerprint != expected_fingerprint:
        p.append("fingerprint_mismatch")
    return p


def verify_candidate(h: Hierarchy, cm: ConceptModel, cand: dict, transitions: dict, fingerprint: str) -> tuple[bool, list[str]]:
    """Every derivation path of an explorer candidate: starts at the original, ends at the candidate, each step a
    verified transition recorded as accepted, and the candidate's release/fingerprint are the current ones."""
    problems: list[str] = []
    if cand.get("snomed_release") != h.release:
        problems.append("release_mismatch")
    if not cand.get("paths"):
        problems.append("no_derivation_path")
    for path in cand.get("paths", []):
        if path[0] != cand["original"] or path[-1] != cand["concept"]:
            problems.append(f"path_endpoints:{'>'.join(path)}")
        for c, q in zip(path, path[1:]):
            problems += [f"{c}>{q}:{x}" for x in verify_transition(h, cm, c, q, transitions.get((c, q)),
                                                                   cand.get("fingerprint"), fingerprint)]
    return not problems, sorted(set(problems))
