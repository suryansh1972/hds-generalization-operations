"""Runtime settings: where the configuration, the SNOMED CT release, the cache and the external evidence files live.

Nothing here is clinical configuration (that is the YAML config, ``semgen.config``). Every location can be given
explicitly or through the environment; nothing points into a source checkout:

========================  ==========================================================================================
``SEMGEN_CONFIG``         generalization config YAML (default: the packaged ``semgen/resources/generalization.yaml``)
``SEMGEN_RF2_DIR``        SNOMED CT RF2 release: its root, its ``Snapshot`` or its ``Snapshot/Terminology`` directory
``SEMGEN_CACHE_DIR``      parsed-release cache (default: ``$XDG_CACHE_HOME/semgen`` or ``~/.cache/semgen``)
``SEMGEN_MAYO_DB``        Mayo ``refrange.sqlite`` (overrides ``mayo.path`` in the config)
``SEMGEN_MAYO_TEST_MAP``  reviewed Mayo test map CSV (overrides ``mayo.test_map``)
``SEMGEN_UCUM_ESSENCE``   UCUM ``ucum-essence.xml`` (overrides ``ucum.path``)
========================  ==========================================================================================
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path

from pydantic import BaseModel, ConfigDict

ENV = {"config_path": "SEMGEN_CONFIG", "rf2_dir": "SEMGEN_RF2_DIR", "cache_dir": "SEMGEN_CACHE_DIR",
       "mayo_db": "SEMGEN_MAYO_DB", "mayo_test_map": "SEMGEN_MAYO_TEST_MAP", "ucum_essence": "SEMGEN_UCUM_ESSENCE"}


def default_config_path() -> Path:
    """The configuration shipped inside the package (works from a wheel as well as a checkout)."""
    return Path(str(files("semgen").joinpath("resources", "generalization.yaml")))


def default_cache_dir(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    if env.get("SEMGEN_CACHE_DIR"):
        return Path(env["SEMGEN_CACHE_DIR"]).expanduser()
    base = env.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base).expanduser() / "semgen"


def env_path(name: str, environ: Mapping[str, str] | None = None) -> Path | None:
    """A path from the environment variable ``name`` (unset or empty: None)."""
    v = (os.environ if environ is None else environ).get(name)
    return Path(v).expanduser() if v else None


class Settings(BaseModel):
    """Resolved runtime locations. ``None`` means "not configured": an unset RF2 release is an error when a context is
    built; an unset Mayo DB or UCUM essence makes the dependent operators block (``mayo_unavailable`` /
    ``unit_validation_unavailable``), exactly as a missing file does."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    config_path: Path | None = None
    rf2_dir: Path | None = None
    cache_dir: Path | None = None
    mayo_db: Path | None = None
    mayo_test_map: Path | None = None
    ucum_essence: Path | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None, **overrides) -> Settings:
        """Settings from ``SEMGEN_*`` variables; keyword ``overrides`` that are not None win."""
        values = {k: env_path(v, environ) for k, v in ENV.items()}
        values["cache_dir"] = default_cache_dir(environ)
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)

    @property
    def resolved_config_path(self) -> Path:
        return self.config_path if self.config_path is not None else default_config_path()

    def describe(self) -> dict:
        """JSON-safe view for diagnostics: which locations are configured and whether they exist (no contents)."""
        out = {}
        for k in ENV:
            p = self.resolved_config_path if k == "config_path" else getattr(self, k)
            out[k] = {"configured": p is not None, "exists": bool(p is not None and Path(p).exists())}
        return out
