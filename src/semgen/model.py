"""Frozen data model for clinical graph motifs."""
from __future__ import annotations

import datetime as _dt
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

PATIENT_ID = "P"
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _freeze(v: Mapping) -> Mapping:
    """Copy into a fresh dict behind a read-only proxy, so later edits of the caller's dict cannot leak in."""
    return MappingProxyType(dict(v))


def check_iso_date(value: str) -> str | None:
    """None if ``value`` is a calendar date written exactly ``YYYY-MM-DD``, else why not."""
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        return f"{value!r} is not an ISO 8601 date YYYY-MM-DD"
    try:
        _dt.date.fromisoformat(value)
    except ValueError as e:
        return f"{value!r} is not a valid date ({e})"
    return None


def _check_dates(v: Mapping[str, str]) -> Mapping[str, str]:
    for k, d in v.items():
        if (why := check_iso_date(d)) is not None:
            raise ValueError(f"dates[{k!r}]: {why}")
    return _freeze(v)


class _Frozen(BaseModel):
    """Frozen base whose model_copy re-validates, so updates are type-checked."""

    model_config = ConfigDict(frozen=True)

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        current = {name: getattr(self, name) for name in type(self).model_fields}
        if update:
            current.update(update)
        return type(self).model_validate(current)


class Interval(_Frozen):
    lo: float | None
    hi: float | None
    lo_closed: bool = True
    hi_closed: bool = True
    unit: str

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, data: Any) -> Any:
        if isinstance(data, Mapping):
            data = dict(data)
            if data.get("hi") is None:
                data["hi_closed"] = False
            if data.get("lo") is None:
                data["lo_closed"] = False
        return data

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.lo is not None and self.hi is not None:
            if self.lo > self.hi:
                raise ValueError(f"lo {self.lo} > hi {self.hi}")
            if self.lo == self.hi and not (self.lo_closed and self.hi_closed):
                raise ValueError("empty degenerate interval")
        return self

    @classmethod
    def point(cls, x: float, unit: str) -> Interval:
        return cls(lo=x, hi=x, unit=unit)

    @classmethod
    def closed(cls, lo: float, hi: float, unit: str) -> Interval:
        return cls(lo=lo, hi=hi, unit=unit)

    def contains_point(self, x: float) -> bool:
        if self.lo is not None and (x < self.lo or (x == self.lo and not self.lo_closed)):
            return False
        if self.hi is not None and (x > self.hi or (x == self.hi and not self.hi_closed)):
            return False
        return True

    def contains(self, other: Interval) -> bool:
        if self.unit != other.unit:
            return False
        if self.lo is not None:
            if other.lo is None or other.lo < self.lo:
                return False
            if other.lo == self.lo and other.lo_closed and not self.lo_closed:
                return False
        if self.hi is not None:
            if other.hi is None or other.hi > self.hi:
                return False
            if other.hi == self.hi and other.hi_closed and not self.hi_closed:
                return False
        return True

    def strictly_contains(self, other: Interval) -> bool:
        return self.contains(other) and self != other

    def to_json(self) -> dict:
        return {"lo": self.lo, "hi": self.hi, "lo_closed": self.lo_closed,
                "hi_closed": self.hi_closed, "unit": self.unit}


class _FrozenWithMappings(_Frozen):
    """Frozen model holding MappingProxyType fields, which cannot be pickled or deep-copied as is."""

    def __deepcopy__(self, memo: dict | None = None) -> Self:
        # Every value inside is immutable (str or frozen model), so rebuilding is a faithful deep copy.
        return type(self).model_validate({name: getattr(self, name) for name in type(self).model_fields})


class TestIdentity(_Frozen):
    """Exact identity of the test reported with a result (e.g. a LOINC or lab test code); never derived."""

    __test__: ClassVar[bool] = False   # not a pytest test class
    system: str
    code: str
    method: str | None = None
    specimen: str | None = None


class AppliesTo(_Frozen):
    """Patient partition a reference range was stated for: age_min inclusive, age_max exclusive, None = open."""

    sex: str | None = None
    age_min_days: int | None = None
    age_max_days: int | None = None


class ReferenceRange(_Frozen):
    """The range the performing laboratory reported with this result (evidence for bucketing, not a pattern)."""

    interval: Interval
    kind: str
    test: TestIdentity
    applies_to: AppliesTo = AppliesTo()
    source: str
    source_ref: str


class Observation(_FrozenWithMappings):
    """One original observation merged into a node by attribute aggregation (A1): its value (with unit), dates,
    the reference range reported with it, its label and source node, kept verbatim. Test identity is the merged
    node's own ``test``, which A1 requires equal (and fully known) across every original."""

    value: Interval
    dates: Mapping[str, str] = Field(default_factory=lambda: MappingProxyType({}))
    source_node: str
    source_record: str | None = None
    label: str | None = None
    reference_range: ReferenceRange | None = None

    @field_validator("dates", mode="after")
    @classmethod
    def _freeze_dates(cls, v: Mapping[str, str]) -> Mapping[str, str]:
        return _check_dates(v)

    @field_serializer("dates")
    def _dump_dates(self, v: Mapping[str, str]) -> dict[str, str]:
        return dict(v)

    def __hash__(self) -> int:
        return hash((self.value, frozenset(self.dates.items()), self.source_node, self.source_record, self.label,
                     self.reference_range))


class Grouping(_Frozen):
    """Where an A3 group came from (design §7.3): the members' lowest common SNOMED CT ancestor in the named
    release. Organisation only: never used for matching."""

    kind: Literal["ontology"]
    system: str
    code: str
    label: str | None = None
    version: str
    source: str


class Node(_FrozenWithMappings):
    id: str
    type: str
    role: str
    label: str | None = None
    code: str | None = None
    polarity: Literal["present", "absent"] = "present"
    value: Interval | None = None
    attrs: Mapping[str, Interval] = Field(default_factory=lambda: MappingProxyType({}))
    dates: Mapping[str, str] = Field(default_factory=lambda: MappingProxyType({}))
    test: TestIdentity | None = None
    reference_range: ReferenceRange | None = None
    observations: tuple[Observation, ...] = ()
    members: tuple[Node, ...] = ()        # A3: the original nodes, verbatim
    grouping: Grouping | None = None

    @field_validator("attrs", mode="after")
    @classmethod
    def _freeze_attrs(cls, v: Mapping[str, Interval]) -> Mapping[str, Interval]:
        return _freeze(v)

    @field_validator("dates", mode="after")
    @classmethod
    def _freeze_dates(cls, v: Mapping[str, str]) -> Mapping[str, str]:
        return _check_dates(v)

    @field_serializer("attrs")
    def _dump_attrs(self, v: Mapping[str, Interval]) -> dict[str, Interval]:
        return dict(v)

    @field_serializer("dates")
    def _dump_dates(self, v: Mapping[str, str]) -> dict[str, str]:
        return dict(v)

    @model_validator(mode="after")
    def _observations_replace_value(self) -> Self:
        if self.observations and self.value is not None:
            raise ValueError(f"node {self.id}: a node with observations has no value")
        if (self.members == ()) != (self.grouping is None):
            raise ValueError(f"node {self.id}: members and grouping are set together")
        if self.members:
            own = (self.code, self.value, self.test, self.reference_range)
            if own != (None, None, None, None) or self.attrs or self.dates or self.observations:
                raise ValueError(f"node {self.id}: a grouped node carries no constraint of its own")
            ids = [m.id for m in self.members]
            if len(ids) < 2 or ids != sorted(set(ids)) or self.id not in ids:
                raise ValueError(f"node {self.id}: members must be two or more distinct ids, sorted, including it")
            if any(m.members for m in self.members):
                raise ValueError(f"node {self.id}: groups do not nest")
        return self

    def __hash__(self) -> int:
        return hash((self.id, self.type, self.role, self.label, self.code, self.polarity,
                     self.value, frozenset(self.attrs.items()), frozenset(self.dates.items()),
                     self.test, self.reference_range, self.observations, self.members, self.grouping))


class Edge(_FrozenWithMappings):
    s: str
    t: str
    rel: str
    prov: Literal["asserted", "derived", "context"]
    window: Interval | None = None
    bpn_score: float | None = None
    dates: Mapping[str, str] = Field(default_factory=lambda: MappingProxyType({}))

    @field_validator("dates", mode="after")
    @classmethod
    def _freeze_dates(cls, v: Mapping[str, str]) -> Mapping[str, str]:
        return _check_dates(v)

    @field_serializer("dates")
    def _dump_dates(self, v: Mapping[str, str]) -> dict[str, str]:
        return dict(v)

    def __hash__(self) -> int:
        return hash((self.s, self.t, self.rel, self.prov, self.window, self.bpn_score,
                     frozenset(self.dates.items())))

    @property
    def key(self) -> tuple[str, str]:
        return (self.s, self.t)


class Motif(_Frozen):
    motif_id: str
    anchor: str
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]

    @property
    def node_ids(self) -> frozenset[str]:
        return frozenset(n.id for n in self.nodes)

    def node(self, id: str) -> Node:
        for n in self.nodes:
            if n.id == id:
                return n
        raise KeyError(id)

    def edge(self, s: str, t: str) -> Edge | None:
        for e in self.edges:
            if e.s == s and e.t == t:
                return e
        return None

    def replace_node(self, node: Node) -> Motif:
        if node.id not in self.node_ids:
            raise KeyError(node.id)
        return self.model_copy(update={"nodes": tuple(node if n.id == node.id else n for n in self.nodes)})

    def replace_edge(self, edge: Edge) -> Motif:
        if self.edge(edge.s, edge.t) is None:
            raise KeyError(edge.key)
        return self.model_copy(update={"edges": tuple(edge if e.key == edge.key else e for e in self.edges)})

    def without(self, node_ids: set[str], edge_keys: set[tuple[str, str]]) -> Motif:
        return self.model_copy(update={
            "nodes": tuple(n for n in self.nodes if n.id not in node_ids),
            "edges": tuple(e for e in self.edges
                           if e.key not in edge_keys and e.s not in node_ids and e.t not in node_ids),
        })
