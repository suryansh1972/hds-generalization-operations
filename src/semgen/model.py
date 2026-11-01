"""Frozen data model for clinical graph motifs."""
from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

PATIENT_ID = "P"


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


class Node(_Frozen):
    id: str
    type: str
    role: str
    label: str | None = None
    code: str | None = None
    polarity: Literal["present", "absent"] = "present"
    value: Interval | None = None
    attrs: Mapping[str, Interval] = Field(default_factory=lambda: MappingProxyType({}))

    @field_validator("attrs", mode="after")
    @classmethod
    def _freeze_attrs(cls, v: Mapping[str, Interval]) -> Mapping[str, Interval]:
        return MappingProxyType(dict(v))

    @field_serializer("attrs")
    def _dump_attrs(self, v: Mapping[str, Interval]) -> dict[str, Interval]:
        return dict(v)

    def __deepcopy__(self, memo: dict | None = None) -> Node:
        # mappingproxy cannot be pickled/deep-copied; Intervals are immutable, so rebuild.
        return type(self).model_validate({name: getattr(self, name) for name in type(self).model_fields})

    def __hash__(self) -> int:
        return hash((self.id, self.type, self.role, self.label, self.code, self.polarity,
                     self.value, frozenset(self.attrs.items())))


class Edge(_Frozen):
    s: str
    t: str
    rel: str
    prov: Literal["asserted", "derived", "context"]
    window: Interval | None = None
    bpn_score: float | None = None

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
