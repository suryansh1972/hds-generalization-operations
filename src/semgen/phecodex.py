"""PhecodeX tables: ICD-10 -> phecodes (with prefix fallback), rollup relation, labels (DRAFT, POC only)."""
from __future__ import annotations

import csv
from pathlib import Path

MAP_FILE = "phecodeX_R_map_ICD_10_WHO.csv"
ROLLUP_FILE = "phecodeX_R_rollup_map.csv"
LABELS_FILE = "phecodeX_R_labels.csv"


def truncate(p: str, level: str) -> str:
    """Cut a phecode to `integer` (ID_001.12 -> ID_001) or `first_decimal` (-> ID_001.1) precision."""
    if level not in ("integer", "first_decimal"):
        raise ValueError(f"unknown phecode level {level!r}")
    pre, sep, num = p.partition("_")
    if not sep:
        return p
    whole, dot, frac = num.partition(".")
    if level == "integer" or not dot:
        return f"{pre}_{whole}"
    return f"{pre}_{whole}.{frac[:1]}" if frac else f"{pre}_{whole}"


class PhecodeX:
    def __init__(self, icd_to_phecodes: dict[str, frozenset[str]], rollup: dict[str, frozenset[str]],
                 labels: dict[str, str]) -> None:
        self._icd = icd_to_phecodes
        self._rollup = rollup
        self._labels = labels

    @classmethod
    def from_maps(cls, icd_to_phecodes: dict[str, set[str]], rollup: dict[str, set[str]],
                  labels: dict[str, str] | None = None) -> PhecodeX:
        return cls({k: frozenset(v) for k, v in icd_to_phecodes.items()},
                   {k: frozenset(v) for k, v in rollup.items()}, dict(labels or {}))

    @classmethod
    def load(cls, dir_: Path) -> PhecodeX:
        dir_ = Path(dir_)
        icd: dict[str, set[str]] = {}
        up: dict[str, set[str]] = {}
        labels: dict[str, str] = {}
        with open(dir_ / MAP_FILE, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                icd.setdefault(r["code"], set()).add(r["phecode"])
        with open(dir_ / ROLLUP_FILE, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                up.setdefault(r["code"], set()).add(r["phecode_unrolled"])
        with open(dir_ / LABELS_FILE, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                labels[r["phenotype"]] = r["description"]
        return cls.from_maps(icd, up, labels)

    def phecodes_for_icd(self, code: str) -> tuple[frozenset[str], str | None]:
        """Exact match, else drop trailing characters (and any trailing '.') down to 3 characters."""
        y = code
        while y not in self._icd and len(y) > 3:
            y = y[:-1].rstrip(".")
        if y in self._icd:
            return self._icd[y], y
        return frozenset(), None

    def rolls_up(self, p: str, q: str) -> bool:
        return p == q or q in self._rollup.get(p, ())

    def label(self, p: str) -> str | None:
        return self._labels.get(p)
