"""UCUM unit-string validation against a pinned ``ucum-essence.xml`` (design §7.3 rev 4, A1 evidence).

Case-sensitive (c/s) syntax: a term is components joined by ``.`` and ``/`` (a leading ``/`` allowed); a component
is ``(term)``, an integer factor, an annotation ``{...}``, or a unit atom (optionally with a prefix, only when the
atom is metric) with an optional signed integer exponent and an optional trailing annotation. Atoms and prefixes
come only from the essence file. This validates syntax and atoms; it does not convert units.
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

_EXP = re.compile(r"^(.*?)([+-]?\d+)$")


@dataclass(frozen=True)
class Ucum:
    version: str
    sha256: str
    atoms: frozenset[str]          # every unit atom code (base units and units)
    metric: frozenset[str]         # atoms that accept a prefix
    prefixes: frozenset[str]

    @classmethod
    def load(cls, path: str | Path, sha256: str) -> Ucum:
        data = Path(path).read_bytes()
        got = hashlib.sha256(data).hexdigest()
        if got != sha256:
            raise ValueError(f"ucum essence {path} has sha256 {got}, expected {sha256}")
        root = ET.fromstring(data)
        atoms, metric, prefixes = set(), set(), set()
        for el in root.iter():
            tag = el.tag.rsplit("}", 1)[-1]
            code = el.get("Code")
            if code is None:
                continue
            if tag == "prefix":
                prefixes.add(code)
            elif tag == "base-unit":
                atoms.add(code)
                metric.add(code)
            elif tag == "unit":
                atoms.add(code)
                if el.get("isMetric") == "yes":
                    metric.add(code)
        return cls(root.get("version", ""), got, frozenset(atoms), frozenset(metric), frozenset(prefixes))

    def provenance(self) -> dict:
        return {"version": self.version, "sha256": self.sha256}

    def _simple(self, s: str) -> bool:
        if s in self.atoms:
            return True
        return any(s.startswith(p) and s[len(p):] in self.metric for p in self.prefixes if len(s) > len(p))

    def _component(self, c: str) -> bool:
        if not c:
            return False
        if c.startswith("(") and c.endswith(")"):
            return self.is_valid(c[1:-1])
        if c.isdigit():
            return True
        if c.startswith("{") and c.endswith("}") and "}" not in c[1:-1]:
            return True
        if c.endswith("}") and "{" in c:
            c = c[:c.index("{")]
            if not c:
                return False
        if self._simple(c):
            return True
        m = _EXP.match(c)
        return bool(m and m.group(1) and self._simple(m.group(1)))

    def is_valid(self, unit: str) -> bool:
        """True iff ``unit`` is a syntactically valid case-sensitive UCUM expression over the essence's atoms."""
        if not unit or any(ch.isspace() for ch in unit):
            return False
        parts, depth, cur = [], 0, ""
        for ch in unit:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
                if depth < 0:
                    return False
            if ch in "./" and depth == 0:
                parts.append(cur)
                cur = ""
            else:
                cur += ch
        if depth != 0:
            return False
        parts.append(cur)
        if unit.startswith("/"):
            parts = parts[1:]
        return all(self._component(p) for p in parts)

    def check(self, unit: str) -> dict:
        return {"unit": unit, "status": "valid" if self.is_valid(unit) else "invalid", **self.provenance()}
