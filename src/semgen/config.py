"""DRAFT YAML configuration: ladders, floors and relation hierarchy, validated at load."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from semgen.model import Interval


class ConfigError(Exception):
    """Raised when the configuration file is missing, unparsable or invalid."""


class Ladder(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    unit: str
    rungs: tuple[Interval, ...]
    applies_to_concepts: tuple[str, ...] = ()
    applies_to_attr: str | None = None

    def next_rung(self, current: Interval) -> Interval | None:
        """Narrowest rung strictly containing `current`; None if none or unit differs."""
        if current.unit != self.unit:
            return None
        cands = [r for r in self.rungs if r.strictly_contains(current)]
        for c in cands:
            if all(o.contains(c) for o in cands):
                return c
        return None


class RelationHierarchy(BaseModel):
    model_config = ConfigDict(frozen=True)

    parents: dict[str, str]

    def parent(self, rel: str) -> str | None:
        return self.parents.get(rel)

    def leq(self, narrow: str, broad: str) -> bool:
        """Reflexive-transitive: is `broad` equal to or an ancestor of `narrow`?"""
        seen: set[str] = set()
        cur: str | None = narrow
        while cur is not None and cur not in seen:
            if cur == broad:
                return True
            seen.add(cur)
            cur = self.parents.get(cur)
        return False


class FloorSourceConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["phecodex"]
    commit: str
    files: dict[str, str]
    phecode_level: Literal["first_decimal", "integer"] = "first_decimal"
    icd10_map_refset: str = "447562003"
    map_rules: tuple[str, ...] = ("TRUE", "OTHERWISE TRUE")
    licence: str = "unconfirmed"


_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_SHA_RE = re.compile(r"[0-9a-f]{64}")


def _build_floor_source(raw: Any) -> FloorSourceConfig:
    if not isinstance(raw, dict):
        raise ConfigError("floor_source must be a mapping")
    try:
        src = FloorSourceConfig.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(f"invalid floor_source: {e}") from e
    if not _COMMIT_RE.fullmatch(src.commit):
        raise ConfigError(f"floor_source commit {src.commit!r} is not 40 lowercase hex")
    if not src.files:
        raise ConfigError("floor_source files must not be empty")
    for name, sha in src.files.items():
        if not _SHA_RE.fullmatch(sha):
            raise ConfigError(f"floor_source sha256 for {name!r} is not 64 lowercase hex")
    return src


class GenConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    lvef_convention: str
    floors: tuple[str, ...]
    floor_source: FloorSourceConfig
    attribute_flags: dict[str, Literal["concept_dependent", "concept_independent"]]
    value_ladders: tuple[Ladder, ...]
    attr_ladders: tuple[Ladder, ...]
    time_ladder: Ladder
    relations: RelationHierarchy
    protected_roles: frozenset[str]
    allow_drop_absent: bool
    max_depth: int

    def value_ladder_for(self, code: str) -> Ladder | None:
        return next((l for l in self.value_ladders if code in l.applies_to_concepts), None)

    def attr_ladder_for(self, name: str) -> Ladder | None:
        return next((l for l in self.attr_ladders if l.applies_to_attr == name), None)

    def attr_is_concept_dependent(self, name: str) -> bool:
        return self.attribute_flags.get(name, "concept_dependent") != "concept_independent"


def _rung(raw: Any, unit: str, bounds: str, where: str) -> Interval:
    if isinstance(raw, (list, tuple)):
        if len(raw) != 2:
            raise ConfigError(f"{where}: rung {raw!r} must be [lo, hi]")
        data: dict[str, Any] = {"lo": raw[0], "hi": raw[1],
                                "lo_closed": bounds[0] == "[", "hi_closed": bounds[1] == "]"}
    elif isinstance(raw, dict):
        data = {"lo_closed": bounds[0] == "[", "hi_closed": bounds[1] == "]", **raw}
    else:
        raise ConfigError(f"{where}: invalid rung {raw!r}")
    data.setdefault("unit", unit)
    if data["unit"] != unit:
        raise ConfigError(f"{where}: rung unit {data['unit']!r} differs from ladder unit {unit!r}")
    try:
        return Interval.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"{where}: invalid rung {raw!r}: {e}") from e


def _disjoint(a: Interval, b: Interval) -> bool:
    def before(x: Interval, y: Interval) -> bool:
        if x.hi is None or y.lo is None:
            return False
        return x.hi < y.lo or (x.hi == y.lo and not (x.hi_closed and y.lo_closed))
    return before(a, b) or before(b, a)


def _build_ladder(name: str, raw: dict[str, Any], *, time: bool = False) -> Ladder:
    where = f"ladder {name}"
    unit = raw["unit"]
    bounds = raw.get("bounds", "[)")
    if bounds not in ("[)", "(]", "[]"):
        raise ConfigError(f"{where}: bounds {bounds!r} must be '[)', '(]' or '[]'")
    rungs = tuple(_rung(r, unit, bounds, where) for r in raw["rungs"])
    if time:
        for r in rungs:
            if r.lo is not None and r.lo < 0:
                raise ConfigError(f"{where}: negative lower bound {r.lo}")
    for i, a in enumerate(rungs):
        for b in rungs[i + 1:]:
            if not (a.contains(b) or b.contains(a) or _disjoint(a, b)):
                raise ConfigError(f"{where}: rungs {a.to_json()} and {b.to_json()} are not laminar")
    return Ladder(name=name, unit=unit, rungs=rungs,
                  applies_to_concepts=tuple(raw.get("applies_to_concepts", ())),
                  applies_to_attr=raw.get("applies_to_attr"))


def _check_cycles(parents: dict[str, str]) -> None:
    for start in parents:
        seen = {start}
        cur = parents[start]
        while cur in parents:
            if cur in seen:
                raise ConfigError(f"relation_parents contains a cycle through {cur!r}")
            seen.add(cur)
            cur = parents[cur]
        if cur == start:
            raise ConfigError(f"relation_parents contains a cycle through {cur!r}")


def _parse(raw: dict[str, Any]) -> GenConfig:
    floor_source = _build_floor_source(raw["floor_source"])
    floors = tuple(str(f) for f in raw["floors"])
    for f in floors:
        if not f.isascii() or not f.isdigit():
            raise ConfigError(f"floor {f!r} is not a numeric SNOMED id")
    # Build ladders in the controller-specified check order: unit, negative, laminar (per ladder).
    value_ladders = tuple(_build_ladder(k, v) for k, v in raw["value_ladders"].items())
    attr_ladders = tuple(_build_ladder(k, v) for k, v in raw["attr_ladders"].items())
    time_ladder = _build_ladder("time", raw["time_ladder"], time=True)
    parents = dict(raw["relation_parents"])
    _check_cycles(parents)
    return GenConfig(
        status=raw["status"], lvef_convention=raw["lvef_convention"], floors=floors,
        floor_source=floor_source,
        attribute_flags=raw["attribute_flags"], value_ladders=value_ladders,
        attr_ladders=attr_ladders, time_ladder=time_ladder,
        relations=RelationHierarchy(parents=parents),
        protected_roles=frozenset(raw["protected_roles"]),
        allow_drop_absent=raw["negation_policy"]["allow_drop_absent"],
        max_depth=raw["max_depth"])


def load_config(path: str | Path) -> GenConfig:
    p = Path(path)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise ConfigError(f"cannot read config {p}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"config {p} must be a mapping")
    try:
        return _parse(raw)
    except ConfigError:
        raise
    except (ValidationError, KeyError, TypeError, AttributeError, ValueError) as e:
        raise ConfigError(f"invalid config {p}: {e!r}") from e


def config_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
