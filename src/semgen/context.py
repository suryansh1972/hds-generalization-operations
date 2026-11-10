"""Build a GenContext (config, SNOMED hierarchy, selected floor policy) from paths.

The effective floor mode is ``floor_mode`` if given, else ``floor_policy.mode`` from the config; only that
policy is built (snomed_boundary by default; phecodex touches PhecodeX and the ICD-10 map only when selected).
"""
from __future__ import annotations

from pathlib import Path

from semgen.config import ConfigError, load_config
from semgen.floors import PhecodeFloorPolicy
from semgen.operators.base import GenContext
from semgen.snomed import default_rf2_dir, load_rf2
from semgen.snomed_floor import SnomedBoundaryPolicy

MODES = ("snomed_boundary", "phecodex")


def build_context(config_path: str | Path, rf2_dir: str | Path | None = None,
                  phecodex_dir: str | Path | None = None, floor_mode: str | None = None) -> GenContext:
    cfg = load_config(config_path)
    mode = floor_mode if floor_mode is not None else cfg.floor_policy.mode
    if mode not in MODES:
        raise ConfigError(f"floor policy {mode!r} must be one of {', '.join(MODES)}")
    if mode == "phecodex" and cfg.floor_source is None:
        raise ConfigError("floor policy phecodex requires a floor_source block in the config")
    if mode == "snomed_boundary" and cfg.floor_policy.snomed_boundary is None:
        raise ConfigError("floor policy snomed_boundary requires floor_policy.snomed_boundary in the config")
    if mode != "phecodex" and phecodex_dir is not None:
        raise ConfigError(f"--phecodex conflicts with floor policy {mode!r}; pass --floor-policy phecodex")
    rf2 = rf2_dir or default_rf2_dir()
    h = load_rf2(rf2)
    if mode == "phecodex":
        floors = PhecodeFloorPolicy.from_config(h, rf2, cfg.floor_source, phecodex_dir)
    else:
        floors = SnomedBoundaryPolicy(h, cfg.floor_policy.snomed_boundary)
    return GenContext(h, cfg, floors)
