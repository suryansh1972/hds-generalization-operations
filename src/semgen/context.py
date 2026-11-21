"""Build a GenContext (config, SNOMED hierarchy, SNOMED-only concept lift, Mayo source, UCUM essence) from locations.

Concept lift (``semgen.lift.SnomedLift``) is built from the RF2 release alone (hierarchy + concept model); it has no
configuration. A missing Mayo DB gives ``refranges=None`` (bucketing then blocks ``mayo_unavailable``); a sha256
mismatch is a ConfigError. A missing UCUM essence gives ``ucum=None`` (A1 then blocks
``unit_validation_unavailable``). ``subject`` and ``cohort`` stay None here (they come from each bundle).
"""
from __future__ import annotations

from pathlib import Path

from semgen.concept_model import load_concept_model
from semgen.config import ConfigError, UcumConfig, load_config
from semgen.interfaces import GenContext, OperatorSet
from semgen.lift import SnomedLift
from semgen.refrange import open_mayo
from semgen.settings import Settings, env_path
from semgen.snomed import Hierarchy, load_rf2
from semgen.ucum import Ucum

NO_RF2 = ("no SNOMED CT RF2 release configured: pass --rf2 / rf2_dir or set SEMGEN_RF2_DIR "
          "(the release is licensed data and is not shipped with semgen)")


def build_lift(h: Hierarchy, rf2_dir: str | Path, cache_dir: str | Path | None = None) -> SnomedLift:
    """Concept lift over the concept model of the same RF2 release (nothing else)."""
    return SnomedLift(h, load_concept_model(rf2_dir, cache_dir))


def open_ucum(cfg: UcumConfig | None, path: str | Path | None = None) -> Ucum | None:
    """The pinned UCUM essence, or None when unlocated or missing (A1 then blocks). ``path`` overrides env
    ``SEMGEN_UCUM_ESSENCE``, which overrides the config's ``path``."""
    if cfg is None:
        return None
    p = Path(path) if path is not None else env_path("SEMGEN_UCUM_ESSENCE")
    if p is None and cfg.path is not None:
        p = Path(cfg.path)
    return Ucum.load(p, cfg.sha256) if p is not None and p.is_file() else None


def build_context(config_path: str | Path | None = None, rf2_dir: str | Path | None = None, *,
                  settings: Settings | None = None, operators: OperatorSet | None = None) -> GenContext:
    """A context from explicit arguments, falling back to ``settings`` (default ``Settings.from_env()``)."""
    s = settings if settings is not None else Settings.from_env()
    cfg = load_config(config_path if config_path is not None else s.resolved_config_path)
    rf2 = rf2_dir if rf2_dir is not None else s.rf2_dir
    if rf2 is None:
        raise ConfigError(NO_RF2)
    h = load_rf2(rf2, s.cache_dir)
    return GenContext(h, cfg, build_lift(h, rf2, s.cache_dir),
                      refranges=open_mayo(cfg.mayo, s.mayo_db, s.mayo_test_map),
                      ucum=open_ucum(cfg.ucum, s.ucum_essence), operators=operators)
