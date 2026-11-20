"""SNOMED CT concept-model data for concept lift (``semgen.lift``): MRCM domains, attribute domains and ranges, the
inferred defining relationships (incl. concrete values), definition status and OWL axioms of the pinned release.

What this module reads, and from where (all RF2 Snapshot files of the same release as the hierarchy):

- ``der2_sssssssRefset_MRCMDomainSnapshot`` (``Refset/Metadata``): one member per concept-model domain, with an ECL
  ``domainConstraint`` and, for a sub-domain, its ``parentDomain``. Only the constraint forms ``<< id``, ``< id`` and
  ``id`` are evaluated, against the IS-A hierarchy; any other form (e.g. ``^ refset``) is kept as *unsupported* and
  membership in that domain is reported as unknown, never guessed.
- ``der2_cissccRefset_MRCMAttributeDomainSnapshot`` (``Refset/Metadata``): which attribute may be used in which domain.
  It validates the attribute types a boundary policy names; it does not say which attribute matters clinically.
- ``der2_ssccRefset_MRCMAttributeRangeSnapshot`` (``Refset/Metadata``, optional): the permitted values of an attribute.
  Only ranges written as disjunctions of ``<< a``, ``< a`` or ``a`` are evaluated; any other form is unsupported.
- ``sct2_Relationship_Snapshot`` (``Terminology``): active, inferred, non-IS-A relationships (attribute type, value,
  group) and ``sct2_RelationshipConcreteValues_Snapshot`` (concrete ``#``/string values). Only compared.
- ``sct2_sRefset_OWLExpressionSnapshot`` (``Terminology``): active class axioms; a concept with an
  ``EquivalentClasses(:id ...)`` axiom is sufficiently defined in OWL (cross-checked against ``definitionStatusId``).

A missing MRCM/OWL file gives ``mrcm=None`` / ``owl_available=False``; nothing is substituted.
"""
from __future__ import annotations

import hashlib
import os
import pickle
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from semgen.settings import default_cache_dir
from semgen.snomed import INFERRED, IS_A, terminology_dir

CACHE_VERSION = "4"
PRIMITIVE = "900000000000074008"   # RF2 definitionStatusId: primitive
# Concept ids are matched as one word token (SCTIDs are digits; tests use readable ids).
_CONSTRAINT = re.compile(r"^\s*(<<|<)?\s*(\w+)\s*(\|[^|]*\|)?\s*$")
_ID = re.compile(r"^\s*(\w+)")
_RANGE_TERM = re.compile(r"^\s*(<<|<)?\s*(\w+)\s*(\|[^|]*\|)?\s*$")


@dataclass(frozen=True)
class MrcmDomain:
    concept: str                 # the concept identifying the domain
    constraint: str              # domainConstraint as published
    operator: str | None         # "<<", "<", "" (self) or None = unsupported constraint form
    focus: str | None            # the constraint's focus concept (None when unsupported)
    parent_domain: str | None    # None for a root (top) domain

    @property
    def supported(self) -> bool:
        return self.operator is not None


@dataclass(frozen=True)
class Mrcm:
    domains: tuple[MrcmDomain, ...]
    attribute_domains: frozenset[tuple[str, str]]   # (attribute concept, domain concept), active rows
    provenance: dict
    # attribute -> ((operator, focus), ...) of its range; None = range present but in an unsupported form
    attribute_ranges: dict[str, tuple[tuple[str, str], ...] | None] = field(default_factory=dict)

    def domain(self, concept: str) -> MrcmDomain | None:
        return next((d for d in self.domains if d.concept == concept), None)

    @property
    def roots(self) -> tuple[MrcmDomain, ...]:
        return tuple(d for d in self.domains if d.parent_domain is None)

    def attribute_allowed(self, attribute: str, domain: str) -> bool:
        return (attribute, domain) in self.attribute_domains


@dataclass(frozen=True)
class ConceptModel:
    """MRCM (or None) plus the attribute relationships: concept -> ((type, value, group), ...) sorted.

    ``primitive``: active concepts whose RF2 definition status is primitive (their definition may be incomplete, so a
    missing attribute is not evidence that it does not apply). ``relationships_available`` is False when no attribute
    relationship file was loaded (every attribute is then unavailable, not absent)."""

    mrcm: Mrcm | None
    attributes: dict[str, tuple[tuple[str, str, str], ...]] = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    primitive: frozenset[str] = frozenset()
    relationships_available: bool = True
    concrete: dict[str, tuple[tuple[str, str, str], ...]] = field(default_factory=dict)  # (type, value, group)
    owl_axiom: frozenset[str] = frozenset()     # concepts with at least one active OWL class axiom
    owl_defined: frozenset[str] = frozenset()   # concepts with an EquivalentClasses axiom (sufficiently defined)
    owl_available: bool = False

    def values(self, concept: str, attr_type: str) -> frozenset[str]:
        return frozenset(v for t, v, _ in self.attributes.get(concept, ()) if t == attr_type)

    def defining(self, concept: str) -> tuple[tuple[str, str, str], ...]:
        """Every inferred defining relationship (type, value, group): concept-valued then concrete."""
        return self.attributes.get(concept, ()) + self.concrete.get(concept, ())


def parse_domain(concept: str, constraint: str, parent: str) -> MrcmDomain:
    m = _CONSTRAINT.match(constraint or "")
    pm = _ID.match(parent or "")
    op, focus = (m.group(1) or "", m.group(2)) if m else (None, None)
    return MrcmDomain(concept, constraint, op, focus, pm.group(1) if pm else None)


def parse_range(constraint: str) -> tuple[tuple[str, str], ...] | None:
    """``(operator, focus)`` terms of a range written as ``<< a |..| OR < b |..| OR c``; None for any other form."""
    terms = (constraint or "").split(" OR ")
    out = []
    for t in terms:
        m = _RANGE_TERM.match(t)
        if m is None:
            return None
        out.append((m.group(1) or "", m.group(2)))
    return tuple(sorted(out)) if out else None


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read(path: Path, cols: list[str]) -> pl.DataFrame:
    return pl.read_csv(path, separator="\t", infer_schema=False, quote_char=None, columns=cols)


def _one(d: Path, pattern: str) -> Path | None:
    hits = sorted(d.glob(pattern)) if d.is_dir() else []
    if len(hits) > 1:
        raise FileNotFoundError(f"expected at most one {pattern} in {d}, found {len(hits)}")
    return hits[0] if hits else None


def load_mrcm(metadata_dir: Path) -> Mrcm | None:
    dom_f = _one(metadata_dir, "der2_sssssssRefset_MRCMDomainSnapshot_*.txt")
    att_f = _one(metadata_dir, "der2_cissccRefset_MRCMAttributeDomainSnapshot_*.txt")
    if dom_f is None or att_f is None:
        return None
    dom = _read(dom_f, ["effectiveTime", "active", "referencedComponentId", "domainConstraint", "parentDomain"])
    dom = dom.filter(pl.col("active") == "1")
    domains = tuple(sorted((parse_domain(c, k, p or "") for c, k, p in zip(
        dom["referencedComponentId"], dom["domainConstraint"], dom["parentDomain"])), key=lambda d: d.concept))
    att = _read(att_f, ["effectiveTime", "active", "referencedComponentId", "domainId"]).filter(pl.col("active") == "1")
    pairs = frozenset(zip(att["referencedComponentId"].to_list(), att["domainId"].to_list()))
    rng_f = _one(metadata_dir, "der2_ssccRefset_MRCMAttributeRangeSnapshot_*.txt")
    ranges: dict[str, tuple[tuple[str, str], ...] | None] = {}
    rng_eff: list[str] = []
    if rng_f is not None:
        rng = _read(rng_f, ["effectiveTime", "active", "referencedComponentId", "rangeConstraint"])
        rng = rng.filter(pl.col("active") == "1")
        rng_eff = rng["effectiveTime"].to_list()
        for a, k in sorted(zip(rng["referencedComponentId"], rng["rangeConstraint"])):
            r = parse_range(k)
            # several active rows (content types) for one attribute: the union, or None if any is unsupported
            prev = ranges.get(a, ())
            ranges[a] = None if r is None or prev is None else tuple(sorted(set(prev) | set(r)))
    eff = max(dom["effectiveTime"].to_list() + att["effectiveTime"].to_list() + rng_eff, default=None)
    prov = {"domain_file": dom_f.name, "domain_sha256": _sha256(dom_f),
            "attribute_domain_file": att_f.name, "attribute_domain_sha256": _sha256(att_f),
            "attribute_range_file": rng_f.name if rng_f else None,
            "attribute_range_sha256": _sha256(rng_f) if rng_f else None,
            "latest_effective_time": eff, "domains": len(domains),
            "unsupported_domains": sorted(d.concept for d in domains if not d.supported)}
    return Mrcm(domains, pairs, prov, ranges)


def load_concept_model(rf2_dir: str | Path, cache_dir: str | Path | None = None) -> ConceptModel:
    """MRCM from the sibling ``Refset/Metadata`` directory and attribute relationships from ``terminology_dir``."""
    d = Path(terminology_dir(rf2_dir)).resolve()
    rf = _one(d, "sct2_Relationship_Snapshot_*.txt")
    if rf is None:
        raise FileNotFoundError(f"no sct2_Relationship_Snapshot_*.txt in {d}")
    meta = d.parent / "Refset" / "Metadata"
    sig = [str(d), f"v{CACHE_VERSION}"]
    extra = [f for f in (_one(d, "sct2_RelationshipConcreteValues_Snapshot_*.txt"),
                         _one(d, "sct2_sRefset_OWLExpressionSnapshot_*.txt")) if f is not None]
    for f in [rf] + extra + sorted(meta.glob("der2_*MRCM*Snapshot_*.txt") if meta.is_dir() else []):
        st = f.stat()
        sig.append(f"{f.name}|{st.st_size}|{st.st_mtime_ns}")
    key = hashlib.sha256("\n".join(sig).encode()).hexdigest()[:12]
    cdir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    cache = cdir / f"concept_model_{key}.pkl"
    if cache.exists():
        try:
            with cache.open("rb") as fh:
                cm = pickle.load(fh)
            if isinstance(cm, ConceptModel):
                return cm
        except Exception:
            pass  # corrupt cache: rebuild
    rel = _read(rf, ["active", "sourceId", "destinationId", "relationshipGroup", "typeId", "characteristicTypeId"])
    rel = rel.filter((pl.col("active") == "1") & (pl.col("characteristicTypeId") == INFERRED)
                     & (pl.col("typeId") != IS_A))
    acc: dict[str, set[tuple[str, str, str]]] = {}
    for s, t, v, g in zip(rel["sourceId"], rel["typeId"], rel["destinationId"], rel["relationshipGroup"]):
        acc.setdefault(s, set()).add((t, v, g))
    attributes = {c: tuple(sorted(xs)) for c, xs in acc.items()}
    cf = _one(d, "sct2_Concept_Snapshot_*.txt")
    primitive: frozenset[str] = frozenset()
    if cf is not None:
        con = _read(cf, ["id", "active", "definitionStatusId"]).filter(
            (pl.col("active") == "1") & (pl.col("definitionStatusId") == PRIMITIVE))
        primitive = frozenset(con["id"].to_list())
    concrete: dict[str, tuple[tuple[str, str, str], ...]] = {}
    cvf = _one(d, "sct2_RelationshipConcreteValues_Snapshot_*.txt")
    if cvf is not None:
        cv = _read(cvf, ["active", "sourceId", "value", "relationshipGroup", "typeId", "characteristicTypeId"])
        cv = cv.filter((pl.col("active") == "1") & (pl.col("characteristicTypeId") == INFERRED))
        cacc: dict[str, set[tuple[str, str, str]]] = {}
        for s, t, v, g in zip(cv["sourceId"], cv["typeId"], cv["value"], cv["relationshipGroup"]):
            cacc.setdefault(s, set()).add((t, v, g))
        concrete = {c: tuple(sorted(xs)) for c, xs in cacc.items()}
    owl_axiom: frozenset[str] = frozenset()
    owl_defined: frozenset[str] = frozenset()
    owf = _one(d, "sct2_sRefset_OWLExpressionSnapshot_*.txt")
    if owf is not None:
        ow = _read(owf, ["active", "referencedComponentId", "owlExpression"]).filter(pl.col("active") == "1")
        ids, exprs = ow["referencedComponentId"].to_list(), ow["owlExpression"].to_list()
        owl_axiom = frozenset(c for c, e in zip(ids, exprs) if e.startswith(("SubClassOf(", "EquivalentClasses(")))
        owl_defined = frozenset(c for c, e in zip(ids, exprs) if e.startswith(f"EquivalentClasses(:{c} "))
    prov = {"relationship_file": rf.name, "relationship_sha256": _sha256(rf),
            "characteristic_type": "inferred", "attribute_relationships": rel.height,
            "concrete_value_file": cvf.name if cvf else None, "concrete_value_sha256": _sha256(cvf) if cvf else None,
            "owl_file": owf.name if owf else None, "owl_sha256": _sha256(owf) if owf else None,
            "concept_file": cf.name if cf else None, "primitive_concepts": len(primitive)}
    cm = ConceptModel(load_mrcm(meta), attributes, prov, primitive, rel.height > 0, concrete, owl_axiom, owl_defined,
                      owf is not None)
    cdir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=cdir, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            pickle.dump(cm, fh, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, cache)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return cm
