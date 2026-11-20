"""``SemgenEngine``: the library entry point. One loaded context (config + SNOMED CT release + evidence sources) and the
operations on it: parse/validate input, enumerate the generalization lattice, inspect concept lift, report provenance.

The engine is framework-independent; the CLI (``semgen.cli``) and the HTTP API (``semgen.api``) are thin layers over
it. An engine is immutable after construction and safe to share between threads: every run copies the context with
the bundle's subject/cohort, and the release data is only read (the lift's transition memo is a pure cache).
"""
from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from semgen.bundle import MotifBundle
from semgen.context import build_context
from semgen.export import lattice_rows, run_header, semgen_version, write_lattice
from semgen.interfaces import GenContext, OperatorSet
from semgen.lattice import Budget, Lattice, enumerate_lattice, operators_of
from semgen.lift_verify import verify_transition
from semgen.model import Motif
from semgen.motif_io import MotifError, bundles_from_data, load_bundles, parse_bundle, parse_motif
from semgen.order import check_bundle_order, check_order
from semgen.settings import Settings


@dataclass(frozen=True)
class GeneralizationResult:
    """One enumerated lattice with the run header that describes how it was produced."""

    bundle_id: str
    lattice: Lattice
    header: dict

    @property
    def status(self) -> str:
        return self.lattice.status

    def summary(self, depth: int | None = None) -> dict:
        rows = lattice_rows(self.lattice, self.header, depth)
        return {"bundle_id": self.bundle_id, "root": self.lattice.root, "status": self.lattice.status,
                "candidates": len(rows["candidates"]), "edges": len(rows["edges"]),
                "blocked": len(rows["blocked"]), "budget_hit": list(self.lattice.budget_hit)}

    def to_json(self, depth: int | None = None) -> dict:
        """Everything ``write`` would write, as one JSON-safe object."""
        return {"bundle_id": self.bundle_id, "run_header": self.header, **lattice_rows(self.lattice, self.header, depth)}

    def write(self, out_dir: str | Path, depth: int | None = None) -> dict[str, Path]:
        """Write ``run_header.json``, ``candidates.jsonl``, ``edges.jsonl``, ``blocked.jsonl``, ``termination.json``
        to ``out_dir/<bundle_id>`` (deterministic bytes; see ``semgen.export``)."""
        return write_lattice(self.lattice, self.bundle_id, Path(out_dir), self.header, depth)


class SemgenEngine:
    """Generalize clinical graph motifs against one SNOMED CT release.

    >>> engine = SemgenEngine.from_config(rf2_dir="/data/SnomedCT_InternationalRF2_...")   # doctest: +SKIP
    >>> result = engine.generalize({"motif_id": "M1", ...}, Budget(max_depth=2))           # doctest: +SKIP
    >>> result.write("runs/")                                                                # doctest: +SKIP
    """

    def __init__(self, context: GenContext, *, config_path: str | Path | None = None) -> None:
        self._ctx = context
        self._config_path = Path(config_path) if config_path is not None else None

    # --- construction ------------------------------------------------------------------------------------------
    @classmethod
    def from_config(cls, config_path: str | Path | None = None, rf2_dir: str | Path | None = None, *,
                    settings: Settings | None = None, operators: OperatorSet | None = None) -> SemgenEngine:
        """Load config and release. Unset arguments fall back to ``settings`` (default: ``Settings.from_env()``);
        ``config_path`` None with no ``SEMGEN_CONFIG`` uses the packaged config."""
        s = settings if settings is not None else Settings.from_env()
        cfg_path = Path(config_path) if config_path is not None else s.resolved_config_path
        ctx = build_context(cfg_path, rf2_dir, settings=s, operators=operators)
        return cls(ctx, config_path=cfg_path)

    @classmethod
    def from_settings(cls, settings: Settings | None = None, *, operators: OperatorSet | None = None) -> SemgenEngine:
        return cls.from_config(settings=settings, operators=operators)

    def with_operators(self, operators: OperatorSet) -> SemgenEngine:
        """A new engine over the same loaded release with a different operator set (nothing is reloaded)."""
        return SemgenEngine(dataclasses.replace(self._ctx, operators=operators), config_path=self._config_path)

    # --- state ---------------------------------------------------------------------------------------------------
    @property
    def context(self) -> GenContext:
        return self._ctx

    @property
    def operators(self) -> OperatorSet:
        return operators_of(self._ctx)

    @property
    def release(self) -> dict:
        h = self._ctx.hierarchy
        return {"edition": h.edition, "release": h.release}

    def header(self, budget: Budget | None = None) -> dict:
        """The run header a lattice run with ``budget`` would carry."""
        return run_header(self._ctx, self._config_path, budget or Budget())

    def provenance(self) -> dict:
        """Release, config and source provenance plus the operator set (content hashes, never local paths)."""
        hdr = self.header()
        hdr.pop("budget")
        return {**hdr, "operators": {"motif": [OperatorSet.name_of(o) for o in self.operators.motif],
                                     "bundle": [OperatorSet.name_of(o) for o in self.operators.bundle]},
                "sources_available": {"mayo": self._ctx.refranges is not None, "ucum": self._ctx.ucum is not None}}

    # --- input ---------------------------------------------------------------------------------------------------
    def parse(self, data: Any) -> list[MotifBundle]:
        """Validate input: one motif or bundle object, a motif list, ``{"motifs": [...]}`` or ``{"bundles": [...]}``.
        FSN labels are resolved against the loaded release. Raises ``MotifError``."""
        return bundles_from_data(data, self._ctx.hierarchy)

    def load(self, path: str | Path) -> list[MotifBundle]:
        """Validate a motif or bundle file (see ``parse``)."""
        return load_bundles(path, self._ctx.hierarchy)

    def _root(self, root: Motif | MotifBundle | dict) -> MotifBundle:
        if isinstance(root, MotifBundle):
            return root
        if isinstance(root, Motif):
            return MotifBundle.of(root)
        if isinstance(root, dict):
            h = self._ctx.hierarchy
            return parse_bundle(root, h) if "motifs" in root else MotifBundle.of(parse_motif(root, h))
        raise MotifError(f"expected a Motif, MotifBundle or dict, got {type(root).__name__}")

    # --- operations ----------------------------------------------------------------------------------------------
    def generalize(self, root: Motif | MotifBundle | dict, budget: Budget | None = None, *, climb: bool = True,
                   progress: str | Path | None = None) -> GeneralizationResult:
        """Enumerate the lattice of one motif or bundle. Every candidate is proven more general than the root; a
        failed proof raises ``GeneralizationOrderError`` / ``PolicyViolation`` (never a silently dropped move).
        ``budget`` bounds the search (default unbounded); see ``semgen.lattice.Budget``."""
        b = self._root(root)
        budget = budget or Budget()
        lat = enumerate_lattice(b, self._ctx, budget, climb=climb, progress=Path(progress) if progress else None)
        return GeneralizationResult(b.bundle_id, lat, self.header(budget))

    def generalize_all(self, roots: Iterable[Motif | MotifBundle | dict],
                       budget: Budget | None = None) -> list[GeneralizationResult]:
        return [self.generalize(r, budget) for r in roots]

    def verify(self, specific: Motif | MotifBundle | dict, general: Motif | MotifBundle | dict,
               certificate: dict[str, str] | None = None) -> dict:
        """The independent order proof that ``general`` matches every patient ``specific`` matches: ``check_order``
        for two single motifs, else ``check_bundle_order`` (a part removal needs its containment ``certificate``,
        which is re-verified, never trusted). This is the proof only, not the lattice policy guard."""
        s, g = self._root(specific), self._root(general)
        if s.is_single and g.is_single:
            r = check_order(s.single_motif, g.single_motif, self._ctx)
        else:
            ctx = dataclasses.replace(self._ctx, subject=s.subject, cohort=s.cohort)
            r = check_bundle_order(s, g, ctx, certificate)
        return {"ok": r.ok, "reason": r.reason, "where": r.where}

    def check_lift(self, child: str, parent: str) -> dict:
        """One concept-lift step: the generator's transition record and the independent verifier's verdict."""
        floors = self._ctx.floors
        d = floors.check_lift(child, parent)
        problems = verify_transition(self._ctx.hierarchy, floors.concept_model, child, parent,
                                     d.detail.get("transition"), floors.fingerprint, floors.fingerprint)
        return {"child": child, "parent": parent, "accepted": d.ok, "reason": d.reason,
                "transition": d.detail.get("transition"), "fingerprint": floors.fingerprint,
                "verification": {"status": "verified" if not problems else "failed", "problems": problems}}

    def inspect_lift(self, code: str, max_transitions: int | None = None) -> dict:
        """Every accepted ancestor of ``code`` with its derivation paths, every evaluated transition and where each
        branch stops (``semgen.lift.SnomedLift.explore``), each candidate re-checked by the independent verifier."""
        explore = getattr(self._ctx.floors, "explore", None)
        if explore is None:
            raise NotImplementedError("the configured concept-lift policy does not support exploration")
        return explore(code, max_transitions=max_transitions, verify=True)

    def concept(self, code: str) -> dict:
        h = self._ctx.hierarchy
        active = h.is_active(code)
        return {"code": code, "active": active, "fsn": h.fsn(code) if active else None,
                "parents": sorted(h.parents(code)) if active else []}

    @staticmethod
    def version() -> str:
        return semgen_version()
