"""Build a GenContext (config, SNOMED hierarchy, PhecodeX floor policy) from paths."""
from __future__ import annotations

from pathlib import Path

from semgen.config import load_config
from semgen.floors import PhecodeFloorPolicy
from semgen.operators.base import GenContext
from semgen.snomed import default_rf2_dir, load_rf2


def build_context(config_path: str | Path, rf2_dir: str | Path | None = None,
                  phecodex_dir: str | Path | None = None) -> GenContext:
    cfg = load_config(config_path)
    rf2 = rf2_dir or default_rf2_dir()
    h = load_rf2(rf2)
    floors = PhecodeFloorPolicy.from_config(h, rf2, cfg.floor_source, phecodex_dir)
    return GenContext(h, cfg, floors)
