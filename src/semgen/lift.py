"""Concept lift decided from SNOMED CT alone: transition evaluation and breadth-first exploration.

Knowledge source: one RF2 release (``Hierarchy`` + ``ConceptModel``): active concepts, FSNs, inferred IS-A and
defining relationships (incl. concrete values), definition status, OWL axioms, MRCM domain / attribute-domain /
attribute-range refsets. No clinical configuration, concept ids, floors, depth limits or count thresholds.

Each child -> parent step gets exactly one outcome from five rules (any ``rejected`` wins, else any ``unknown``, else
``accepted``); every rule's outcome and evidence is recorded:

1. ``concept``   both active; parent is an active inferred IS-A parent of the child.
2. ``hierarchy`` the parent is not the hierarchy root (no parents) nor a top-level concept (all its parents are the
   root), and the child keeps every top-level hierarchy it belongs to.
3. ``semantic_tag`` the FSN semantic tag is unchanged (a changed tag is a different SNOMED category); a missing tag
   is ``unknown``.
4. ``definition`` both concepts have an OWL class axiom and their RF2 definition status agrees with it
   (EquivalentClasses = fully defined); otherwise ``unknown``. Primitive status is recorded, never a stop by itself.
5. ``mrcm_domain`` the parent stays inside every (evaluable) MRCM domain the child is in and is not itself the
   concept that names an MRCM domain (that concept is the whole domain). No MRCM, or no evaluable domain, is unknown.
6. ``defining_relationships`` the parent keeps every defining attribute type of the child and at least as many
   relationship groups: a lift may broaden attribute *values* (that is what an inferred parent does) but must not
   drop an axis of the definition (an axis also counts as dropped when every parent value is a focus of the
   attribute's MRCM range, i.e. its most general permitted value). A child with no defining relationships gives no structural evidence -> unknown.
   Each attribute type must be permitted by the MRCM attribute domain of the child's domains, and the parent's
   values must lie in the attribute's MRCM range where the range is evaluable (else unknown).

The dynamic floor of a branch is the concept whose every parent step is ``rejected`` or ``unknown``; it is derived
per concept by ``explore``, never supplied. Concept-level validity only: motif-level preservation is proved by the
lattice order checker (``semgen.order``), and every applied step is re-checked by ``semgen.lift_verify``.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from dataclasses import dataclass, field

from semgen.concept_model import ConceptModel, MrcmDomain
from semgen.lift_verify import verify_candidate
from semgen.snomed import Hierarchy

ALGORITHM = "semgen-snomed-lift/1"
STATUS = "DRAFT — ontology-derived, not clinically validated"
_TAG = re.compile(r"\(([^()]+)\)$")

REJECT_REASONS = frozenset({"inactive_concept", "inactive_parent", "not_inferred_parent", "hierarchy_root", "top_level_concept",
                            "top_level_hierarchy_lost", "semantic_tag_changed", "mrcm_domain_concept",
                            "mrcm_domain_lost", "defining_attribute_dropped", "role_group_dropped"})
UNKNOWN_REASONS = frozenset({"no_semantic_tag", "owl_unavailable", "owl_axiom_missing", "definition_status_conflict",
                             "mrcm_unavailable", "no_mrcm_domain", "relationships_unavailable",
                             "no_defining_relationships", "attribute_outside_mrcm_domain",
                             "attribute_value_outside_mrcm_range"})


@dataclass(frozen=True)
class FloorDecision:
    """The ``check_lift`` answer the lattice, order and aggregation code consume."""
    ok: bool
    reason: str | None
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Transition:
    child: str
    parent: str
    decision: str                 # accepted | rejected | unknown
    reason: str | None            # first rejecting rule's reason, else first unknown one; None when accepted
    rules: tuple[dict, ...]       # {"rule", "outcome", "reason", "evidence"} for every rule, in order

    def to_json(self) -> dict:
        return {"child": self.child, "parent": self.parent, "decision": self.decision, "reason": self.reason,
                "rules": list(self.rules)}


def _rule(name: str, outcome: str, reason: str | None = None, **evidence) -> dict:
    return {"rule": name, "outcome": outcome, "reason": reason, "evidence": evidence}


class SnomedLift:
    """Boundary evaluator + lift explorer over one RF2 release (also the lattice's ``ctx.floors``)."""

    def __init__(self, hierarchy: Hierarchy, concept_model: ConceptModel) -> None:
        self.h, self.concept_model = hierarchy, concept_model
        mrcm = concept_model.mrcm
        self._domains = tuple(d for d in mrcm.domains if d.supported) if mrcm else ()
        self._unsupported = tuple(d.concept for d in mrcm.domains if not d.supported) if mrcm else ()
        self._memo: dict[tuple[str, str], Transition] = {}
        body = {"algorithm": ALGORITHM, "release": hierarchy.release, "edition": hierarchy.edition,
                "concept_model": concept_model.provenance, "mrcm": mrcm.provenance if mrcm else None}
        self.fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()

    @property
    def provenance(self) -> dict:
        cm = self.concept_model
        return {"mode": "snomed_ontology", "algorithm": ALGORITHM, "status": STATUS, "fingerprint": self.fingerprint,
                "snomed_release": self.h.release, "snomed_edition": self.h.edition,
                "concept_model": cm.provenance, "mrcm": cm.mrcm.provenance if cm.mrcm else None}

    # --- ontology reads -------------------------------------------------------------------------------------------
    def tag(self, c: str) -> str | None:
        m = _TAG.search(self.h.fsn(c) or "")
        return m.group(1) if m else None

    def top_levels(self, c: str) -> frozenset[str]:
        """Concepts on c's ancestor-or-self chain all of whose parents are parentless (the hierarchy root)."""
        h = self.h
        return frozenset(a for a in h.ancestors_or_self(c) if h.parents(a) and all(not h.parents(q) for q in h.parents(a)))

    def _in(self, c: str, d: MrcmDomain) -> bool:
        if d.operator == "":
            return c == d.focus
        anc = self.h.ancestors(c)
        return d.focus in anc or (d.operator == "<<" and c == d.focus)

    def domains(self, c: str) -> tuple[str, ...]:
        return tuple(d.concept for d in self._domains if self._in(c, d))

    def _definition(self, c: str) -> str:
        return "primitive" if c in self.concept_model.primitive else "fully_defined"

    # --- the rules -------------------------------------------------------------------------------------------------
    def _r_concept(self, c: str, p: str) -> dict:
        h = self.h
        if not h.is_active(c) or not h.is_active(p):
            return _rule("concept", "rejected", "inactive_concept" if not h.is_active(c) else "inactive_parent",
                         child_active=h.is_active(c), parent_active=h.is_active(p))
        if p not in h.parents(c):
            return _rule("concept", "rejected", "not_inferred_parent")
        return _rule("concept", "accepted", None, isa=[c, p], characteristic_type=h.characteristic_type)

    def _r_hierarchy(self, c: str, p: str) -> dict:
        h = self.h
        if not h.parents(p):
            return _rule("hierarchy", "rejected", "hierarchy_root")
        ct, pt = self.top_levels(c), self.top_levels(p)
        ev = {"child_top_level": sorted(ct), "parent_top_level": sorted(pt)}
        if p in pt:
            return _rule("hierarchy", "rejected", "top_level_concept", **ev)
        if ct - pt:
            return _rule("hierarchy", "rejected", "top_level_hierarchy_lost", **ev)
        return _rule("hierarchy", "accepted", None, **ev)

    def _r_tag(self, c: str, p: str) -> dict:
        ct, pt = self.tag(c), self.tag(p)
        ev = {"child_fsn": self.h.fsn(c), "parent_fsn": self.h.fsn(p), "child_tag": ct, "parent_tag": pt}
        if ct is None or pt is None:
            return _rule("semantic_tag", "unknown", "no_semantic_tag", **ev)
        return _rule("semantic_tag", "accepted" if ct == pt else "rejected", None if ct == pt else "semantic_tag_changed", **ev)

    def _r_definition(self, c: str, p: str) -> dict:
        cm = self.concept_model
        ev = {"child_definition": self._definition(c), "parent_definition": self._definition(p)}
        if not cm.owl_available:
            return _rule("definition", "unknown", "owl_unavailable", **ev)
        missing = [x for x in (c, p) if x not in cm.owl_axiom]
        if missing:
            return _rule("definition", "unknown", "owl_axiom_missing", missing=missing, **ev)
        conflict = [x for x in (c, p) if (x in cm.owl_defined) == (x in cm.primitive)]
        if conflict:
            return _rule("definition", "unknown", "definition_status_conflict", conflicting=conflict, **ev)
        return _rule("definition", "accepted", None, **ev)

    def _r_domain(self, c: str, p: str) -> dict:
        if self.concept_model.mrcm is None:
            return _rule("mrcm_domain", "unknown", "mrcm_unavailable")
        cd, pd = self.domains(c), self.domains(p)
        ev = {"child_domains": list(cd), "parent_domains": list(pd), "unevaluated_domains": list(self._unsupported)}
        named = sorted(d.concept for d in self._domains if d.focus == p)
        if named:
            return _rule("mrcm_domain", "rejected", "mrcm_domain_concept", domain=named, **ev)
        if set(cd) - set(pd):
            return _rule("mrcm_domain", "rejected", "mrcm_domain_lost", lost=sorted(set(cd) - set(pd)), **ev)
        if not cd:
            return _rule("mrcm_domain", "unknown", "no_mrcm_domain", **ev)
        return _rule("mrcm_domain", "accepted", None, **ev)

    def _r_relationships(self, c: str, p: str) -> dict:
        cm = self.concept_model
        if not cm.relationships_available:
            return _rule("defining_relationships", "unknown", "relationships_unavailable")
        crel, prel = cm.defining(c), cm.defining(p)
        ctypes, ptypes = sorted({t for t, _, _ in crel}), sorted({t for t, _, _ in prel})
        cg, pg = len({g for _, _, g in crel if g != "0"}), len({g for _, _, g in prel if g != "0"})
        ev = {"child_types": ctypes, "parent_types": ptypes, "child_groups": cg, "parent_groups": pg,
              "child_relationships": [list(r) for r in crel], "parent_relationships": [list(r) for r in prel]}
        dropped = sorted(set(ctypes) - set(ptypes))
        mrcm = cm.mrcm
        if mrcm is not None:   # a value equal to its MRCM range focus is the attribute's most general value: axis gone
            for t in sorted(set(ctypes) & set(ptypes)):
                foci = {f for _, f in mrcm.attribute_ranges.get(t) or ()}
                cv, pv = cm.values(c, t), cm.values(p, t)
                if foci and pv and pv <= foci and not cv <= foci:
                    dropped.append(t)
                    ev.setdefault("reduced_to_range_focus", []).append(t)
        if dropped:
            return _rule("defining_relationships", "rejected", "defining_attribute_dropped", dropped=dropped, **ev)
        if pg < cg:
            return _rule("defining_relationships", "rejected", "role_group_dropped", **ev)
        if not crel:
            return _rule("defining_relationships", "unknown", "no_defining_relationships", **ev)
        if mrcm is not None:
            doms = self.domains(c)
            outside = sorted(t for t in ctypes if not any(mrcm.attribute_allowed(t, d) for d in doms))
            if outside:
                return _rule("defining_relationships", "unknown", "attribute_outside_mrcm_domain", outside=outside, **ev)
            bad, unevaluated = [], []
            for t, v, _ in cm.attributes.get(p, ()):
                rng = mrcm.attribute_ranges.get(t, ())
                if rng is None:
                    unevaluated.append(t)
                elif rng and not any(self._in(v, MrcmDomain("", "", op, f, None)) for op, f in rng):
                    bad.append([t, v])
            ev["ranges_not_evaluable"] = sorted(set(unevaluated))
            if bad:
                return _rule("defining_relationships", "unknown", "attribute_value_outside_mrcm_range", values=bad, **ev)
        return _rule("defining_relationships", "accepted", None, **ev)

    # --- public API ------------------------------------------------------------------------------------------------
    def evaluate(self, child: str, parent: str) -> Transition:
        key = (child, parent)
        if key in self._memo:
            return self._memo[key]
        first = self._r_concept(child, parent)
        rules = (first,) if first["outcome"] == "rejected" else (
            first, self._r_hierarchy(child, parent), self._r_tag(child, parent), self._r_definition(child, parent),
            self._r_domain(child, parent), self._r_relationships(child, parent))
        rej = [r["reason"] for r in rules if r["outcome"] == "rejected"]
        unk = [r["reason"] for r in rules if r["outcome"] == "unknown"]
        decision, reason = ("rejected", rej[0]) if rej else ("unknown", unk[0]) if unk else ("accepted", None)
        t = self._memo[key] = Transition(child, parent, decision, reason, rules)
        return t

    def check_lift(self, child: str, parent: str, *, role: str | None = None, node_id: str | None = None,
                   cohort=None) -> FloorDecision:
        """Motif context (``role``/``node_id``/``cohort``) is not ontology evidence and is ignored."""
        t = self.evaluate(child, parent)
        return FloorDecision(t.decision == "accepted", t.reason,
                             {"parent": parent, "decision": t.decision, "transition": t.to_json(),
                              "fingerprint": self.fingerprint})

    def explore(self, code: str, max_transitions: int | None = None, verify: bool = True) -> dict:
        """BFS over every accepted parent branch from ``code``. Returns candidates (deduplicated by concept, every
        derivation path kept), every transition, per-concept termination and completeness. ``max_transitions`` is a
        technical budget only: when it stops the search, ``complete`` is False and the pending concepts are listed."""
        h = self.h
        out: dict = {"origin": code, "origin_fsn": h.fsn(code), "release": h.release, "fingerprint": self.fingerprint}
        if not h.is_active(code):
            return {**out, "eligible": False, "reason": "inactive_concept", "candidates": [], "transitions": [],
                    "terminations": [], "complete": True, "exhausted": True}
        preds: dict[str, list[str]] = {code: []}
        depth = {code: 0}
        transitions: list[Transition] = []
        terminations: list[dict] = []
        queue, n, complete = deque([code]), 0, True
        while queue:
            c = queue.popleft()
            parents = sorted(h.parents(c))
            if max_transitions is not None and n + len(parents) > max_transitions:
                complete = False
                queue.appendleft(c)
                break
            outs = [self.evaluate(c, p) for p in parents]
            n += len(outs)
            transitions += outs
            for t in outs:
                if t.decision != "accepted":
                    continue
                if t.parent not in preds:
                    preds[t.parent], depth[t.parent] = [], depth[c] + 1
                    queue.append(t.parent)
                preds[t.parent].append(c)
            stopped = [{"parent": t.parent, "decision": t.decision, "reason": t.reason} for t in outs if t.decision != "accepted"]
            if stopped or not parents:
                terminations.append({"concept": c, "floor": len(stopped) == len(parents),
                                     "reason": "no_parent" if not parents else None, "stopped": stopped})
        memo: dict[str, list[list[str]]] = {}

        def paths(c: str) -> list[list[str]]:
            if c not in memo:
                memo[c] = [[code]] if c == code else sorted(pp + [c] for q in sorted(preds[c]) for pp in paths(q))
            return memo[c]

        floors = {t["concept"] for t in terminations if t["floor"]}
        cands = [{"original": code, "original_fsn": h.fsn(code), "concept": c, "fsn": h.fsn(c), "depth": depth[c],
                  "paths": paths(c), "is_branch_floor": c in floors, "snomed_release": h.release,
                  "fingerprint": self.fingerprint}
                 for c in sorted(preds, key=lambda x: (depth[x], x)) if c != code]
        by_pair = {(t.child, t.parent): t.to_json() for t in transitions}
        if verify:
            for cand in cands:
                ok, problems = verify_candidate(h, self.concept_model, cand, by_pair, self.fingerprint)
                cand["verification"] = {"status": "verified" if ok else "failed", "problems": problems}
        return {**out, "eligible": True, "origin_floor": code in floors, "candidates": cands,
                "transitions": [t.to_json() for t in transitions], "terminations": terminations,
                "rejected": [[t.child, t.parent, t.reason] for t in transitions if t.decision == "rejected"],
                "unknown": [[t.child, t.parent, t.reason] for t in transitions if t.decision == "unknown"],
                "complete": complete, "exhausted": complete and not queue, "pending": [] if complete else list(queue),
                "transitions_evaluated": n}
