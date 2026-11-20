"""DRAFT YAML configuration: pinned attribute definitions and the pinned external sources, validated at load.

Relative paths in a config file are resolved against the directory of that file and stored absolute, so a config
works wherever it is installed. External evidence (Mayo DB, UCUM essence) may also be located by ``semgen.settings``
(``SEMGEN_MAYO_DB`` etc.); the sha256 pins always come from the config.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from semgen.settings import default_config_path


class ConfigError(Exception):
    """Raised when the configuration file is missing, unparsable or invalid."""


_SHA_RE = re.compile(r"[0-9a-f]{64}")


class AttributeDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    about: Literal["patient", "node_concept"]


class MayoConfig(BaseModel):
    """Where the Mayo reference-range DB lives (env ``SEMGEN_MAYO_DB`` overrides ``path``) and its pinned sha256.

    ``path`` and ``test_map`` are optional (absolute after loading). Without a DB bucketing blocks
    ``mayo_unavailable``; without a test map every Mayo lookup blocks ``no_test_mapping``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str | None = None
    sha256: str
    test_map: str | None = None


class UcumConfig(BaseModel):
    """Pinned UCUM essence file (A1 unit validation, rev 4); ``path`` is optional (env ``SEMGEN_UCUM_ESSENCE``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str | None = None
    sha256: str


class GenConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    attribute_definitions: dict[str, AttributeDefinition]
    attribute_definitions_sha256: str
    mayo: MayoConfig
    ucum: UcumConfig | None = None
    protected_roles: frozenset[str]
    allow_drop_absent: bool

    def attr_is_concept_dependent(self, name: str) -> bool:
        """Only an attribute defined ``about: patient`` is independent; an unlisted name is ``node_concept``."""
        d = self.attribute_definitions.get(name)
        return d is None or d.about != "patient"


def _resolve(base: Path, p: str | None) -> str | None:
    """``p`` made absolute against the config file's directory (None stays None)."""
    if p is None:
        return None
    q = Path(p).expanduser()
    return str(q if q.is_absolute() else (base / q).resolve())


def _load_attribute_definitions(raw: Any, base: Path) -> tuple[dict[str, AttributeDefinition], str]:
    """Read the pinned attribute-definitions file; its sha256 must match the config before it is parsed."""
    if not isinstance(raw, dict) or set(raw) != {"path", "sha256"}:
        raise ConfigError("attribute_definitions must be a mapping with exactly 'path' and 'sha256'")
    expected = raw["sha256"]
    if not isinstance(expected, str) or not _SHA_RE.fullmatch(expected):
        raise ConfigError("attribute_definitions sha256 must be 64 lowercase hex")
    p = Path(str(_resolve(base, str(raw["path"]))))
    try:
        data = p.read_bytes()
    except OSError as e:
        raise ConfigError(f"cannot read attribute definitions {p}: {e}") from e
    got = hashlib.sha256(data).hexdigest()
    if got != expected:
        raise ConfigError(f"attribute definitions {p} have sha256 {got}, expected {expected}")
    try:
        doc = yaml.safe_load(data.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as e:
        raise ConfigError(f"cannot parse attribute definitions {p}: {e}") from e
    if not isinstance(doc, dict) or set(doc) != {"attributes"} or not isinstance(doc["attributes"], dict):
        raise ConfigError(f"attribute definitions {p} must be a mapping with exactly one key 'attributes'")
    try:
        defs = {str(k): AttributeDefinition.model_validate(v) for k, v in doc["attributes"].items()}
    except ValidationError as e:
        raise ConfigError(f"invalid attribute definition in {p}: {e}") from e
    return defs, got


def _build_mayo(raw: Any, base: Path) -> MayoConfig:
    if not isinstance(raw, dict):
        raise ConfigError("mayo is required and must be a mapping with 'sha256' and optional 'path' and 'test_map'")
    try:
        m = MayoConfig.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(f"invalid mayo: {e}") from e
    if not _SHA_RE.fullmatch(m.sha256):
        raise ConfigError("mayo sha256 must be 64 lowercase hex")
    return m.model_copy(update={"path": _resolve(base, m.path), "test_map": _resolve(base, m.test_map)})


def _parse(raw: dict[str, Any], base: Path) -> GenConfig:
    if "floor_policy" in raw:
        raise ConfigError("floor_policy is no longer configurable: concept lift is derived from the SNOMED CT release")
    attribute_definitions, attribute_definitions_sha256 = _load_attribute_definitions(raw.get("attribute_definitions"), base)
    for gone, why in (("optimuskg", "attribute deletion is decided by the cohort definition alone"),
                      ("panel_sources", "A2 panel aggregation was removed")):
        if gone in raw:
            raise ConfigError(f"{gone} is no longer supported: {why}")
    mayo = _build_mayo(raw.get("mayo"), base)
    try:
        ucum = None if raw.get("ucum") is None else UcumConfig.model_validate(raw["ucum"])
    except ValidationError as e:
        raise ConfigError(f"invalid ucum: {e}") from e
    if ucum is not None and not _SHA_RE.fullmatch(ucum.sha256):
        raise ConfigError(f"ucum {ucum.path}: sha256 must be 64 lowercase hex")
    if ucum is not None:
        ucum = ucum.model_copy(update={"path": _resolve(base, ucum.path)})
    if raw["negation_policy"]["allow_drop_absent"] is not False:
        raise ConfigError("negation_policy.allow_drop_absent: only false is supported (not supported: true)")
    if set(raw["protected_roles"]) != {"patient", "anchor"}:
        raise ConfigError("protected_roles must be exactly {patient, anchor}")
    if not str(raw["status"]).startswith("DRAFT"):
        raise ConfigError(f"status {raw['status']!r} must start with 'DRAFT'")
    return GenConfig(
        status=raw["status"],
        attribute_definitions=attribute_definitions, attribute_definitions_sha256=attribute_definitions_sha256,
        mayo=mayo, ucum=ucum, protected_roles=frozenset(raw["protected_roles"]),
        allow_drop_absent=raw["negation_policy"]["allow_drop_absent"])


def load_config(path: str | Path | None = None) -> GenConfig:
    """Load and validate a config file (default: the packaged ``semgen/resources/generalization.yaml``)."""
    p = Path(path) if path is not None else default_config_path()
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise ConfigError(f"cannot read config {p}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"config {p} must be a mapping")
    try:
        return _parse(raw, p.resolve().parent)
    except ConfigError:
        raise
    except (ValidationError, KeyError, TypeError, AttributeError, ValueError) as e:
        raise ConfigError(f"invalid config {p}: {e!r}") from e


def config_sha256(path: str | Path | None = None) -> str:
    return hashlib.sha256(Path(path if path is not None else default_config_path()).read_bytes()).hexdigest()
