"""Reference-range evidence for normative bucketing (design §7.1, D7).

Selection order, with no fallback between steps: (a) the range the laboratory reported with the result
(``node.reference_range``), which must pass every eligibility check or the node is ``result_range_unverified``
and Mayo is never consulted; (b) otherwise Mayo ``refrange.sqlite`` through the reviewed test map; any missing,
ambiguous or conflicting evidence is a ``Blocked`` reason. Units must be identical strings (no UCUM file, D7).

Mayo operators map to endpoint closure: ``>=``/``<=`` closed, ``>``/``<`` open, ``=`` on both sides a point.
Age bounds: ``age_min_days`` inclusive, ``age_max_days`` exclusive, null open.
"""
from __future__ import annotations

import csv
import hashlib
import io
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from semgen.bundle import Subject
from semgen.config import ConfigError, MayoConfig
from semgen.interfaces import Blocked
from semgen.model import AppliesTo, Interval, Node, TestIdentity
from semgen.settings import env_path

OP = "normative_bucketing"
ENV_DB = "SEMGEN_MAYO_DB"
MAP_COLUMNS = ("system", "code", "mnemonic", "analyte", "specimen", "page_ref", "reviewed_by")
_RANGE_COLUMNS = ("range_id", "mnemonic", "analyte", "sex", "age_min_days", "age_max_days", "condition", "category",
                  "low", "low_op", "high", "high_op", "unit", "confidence", "pdf_page", "raw")
_LOW_CLOSED = {">=": True, ">": False, "=": True}
_HIGH_CLOSED = {"<=": True, "<": False, "=": True}
ANY_SEX = "any"


@dataclass(frozen=True)
class RangeSelection:
    interval: Interval
    source: dict          # JSON-safe: kind (result | mayo), sha256, range_id, pdf_page, raw, mapping_row, ...
    selection: list[str]  # the filters applied, in order


def mayo_db_path(cfg: MayoConfig, override: str | Path | None = None) -> Path | None:
    """``override``, else env ``SEMGEN_MAYO_DB``, else the config's (absolute) ``path``; None when none is given."""
    if override is not None:
        return Path(override)
    env = env_path(ENV_DB)
    if env is not None:
        return env
    return Path(cfg.path) if cfg.path is not None else None


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_test_map(p: Path) -> tuple[tuple[dict[str, str], ...], str]:
    try:
        data = p.read_bytes()
    except OSError as e:
        raise ConfigError(f"cannot read Mayo test map {p}: {e}") from e
    try:
        reader = csv.DictReader(io.StringIO(data.decode("utf-8"), newline=""))
        if tuple(reader.fieldnames or ()) != MAP_COLUMNS:
            raise ConfigError(f"Mayo test map {p} must have exactly the columns {', '.join(MAP_COLUMNS)}, "
                              f"got {reader.fieldnames}")
        rows = tuple(dict(r) for r in reader)
    except (UnicodeDecodeError, csv.Error) as e:
        raise ConfigError(f"cannot parse Mayo test map {p}: {e}") from e
    for i, r in enumerate(rows, start=2):
        if None in r or any(v is None for v in r.values()):
            raise ConfigError(f"Mayo test map {p} line {i}: wrong number of fields")
        if not all(r[c] for c in ("system", "code", "mnemonic", "analyte")):
            raise ConfigError(f"Mayo test map {p} line {i}: system, code, mnemonic and analyte are required")
    return rows, hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class MayoSource:
    """The pinned Mayo DB (read only, per query) and the optional reviewed test map.

    ``sexes`` is the source's own sex vocabulary (``SELECT DISTINCT sex FROM ranges`` minus the ``any`` wildcard),
    read once at open: a subject sex outside it would silently match no sex-specific row."""

    path: Path
    sha256: str
    test_map: tuple[dict[str, str], ...] | None   # None: no map file
    test_map_sha256: str | None
    sexes: tuple[str, ...] = ()                   # sorted

    @classmethod
    def open(cls, path: Path, sha256: str, test_map: Path | None) -> MayoSource:
        path = Path(path)
        got = _sha256_file(path)
        if got != sha256:
            raise ConfigError(f"Mayo DB {path} has sha256 {got}, expected {sha256}")
        src = cls(path, sha256, None, None)
        try:
            src._query("SELECT * FROM ranges LIMIT 0")
            sexes = tuple(sorted({r["sex"] for r in src._query("SELECT DISTINCT sex FROM ranges")
                                  if isinstance(r["sex"], str) and r["sex"] != ANY_SEX}))
        except sqlite3.Error as e:
            raise ConfigError(f"Mayo DB {path} has no readable ranges table: {e}") from e
        if test_map is None:
            return cls(path, sha256, None, None, sexes)
        rows, map_sha = _read_test_map(Path(test_map))
        return cls(path, sha256, rows, map_sha, sexes)

    def _query(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        uri = self.path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as con:
            con.row_factory = sqlite3.Row
            return [dict(r) for r in con.execute(sql, args)]

    def mappings(self, test: TestIdentity) -> list[dict[str, str]]:
        """Map rows whose system and code equal the test's exactly (empty without a map file)."""
        return [r for r in self.test_map or () if r["system"] == test.system and r["code"] == test.code]

    def test_specimen(self, mnemonic: str) -> str | None:
        """The specimen Mayo's ``tests`` table states for ``mnemonic`` (None if no row or not stated).

        ``tests.mnemonic`` is unique in the Mayo DB (index ``i4``), so there is at most one row."""
        rows = self._query("SELECT specimen FROM tests WHERE mnemonic = ?", (mnemonic,))
        spec = rows[0]["specimen"] if rows else None
        return spec if isinstance(spec, str) and spec.strip() else None

    def ranges(self, mnemonic: str, analyte: str) -> list[dict[str, Any]]:
        return self._query(f"SELECT {', '.join(_RANGE_COLUMNS)} FROM ranges WHERE mnemonic = ? AND analyte = ? "
                           "ORDER BY range_id", (mnemonic, analyte))


def open_mayo(cfg: MayoConfig, db: str | Path | None = None, test_map: str | Path | None = None) -> MayoSource | None:
    """The configured source, or None if no DB is located or the file is missing; a sha256 mismatch is a
    ConfigError. ``db`` / ``test_map`` override the config (and env ``SEMGEN_MAYO_DB`` / ``SEMGEN_MAYO_TEST_MAP``)."""
    path = mayo_db_path(cfg, db)
    if path is None or not path.is_file():
        return None
    tm = Path(test_map) if test_map is not None else env_path("SEMGEN_MAYO_TEST_MAP")
    if tm is None and cfg.test_map is not None:
        tm = Path(cfg.test_map)
    return MayoSource.open(path, cfg.sha256, tm if tm is not None and tm.is_file() else None)


def buckets(r: Interval) -> list[tuple[str, Interval]]:
    """below / within / above the reference interval R, each outer bucket taking the complementary closure at R's
    endpoints (rev 4 names; were low / reference / high).

    The buckets are disjoint and cover the line, so every value lies in exactly one. One-sided R gives two. R is a
    reference interval only: not a clinical decision limit and not a diagnostic category.
    """
    out: list[tuple[str, Interval]] = []
    if r.lo is not None:
        out.append(("below_reference_interval", Interval(lo=None, hi=r.lo, hi_closed=not r.lo_closed, unit=r.unit)))
    out.append(("within_reference_interval", r))
    if r.hi is not None:
        out.append(("above_reference_interval", Interval(lo=r.hi, lo_closed=not r.hi_closed, hi=None, unit=r.unit)))
    return out


# --- partitions (shared by the result range and Mayo rows) -------------------------------------------


def _needed(sex: str | None, age_min: float | None, age_max: float | None) -> set[str]:
    out = set()
    if sex is not None:
        out.add("sex")
    if age_min is not None or age_max is not None:
        out.add("age_days")
    return out


def _missing(needed: set[str], subject: Subject | None) -> list[str]:
    return sorted(f for f in needed if subject is None or getattr(subject, f) is None)


def _in_partition(sex: str | None, age_min: float | None, age_max: float | None, subject: Subject) -> bool:
    if sex is not None and sex != subject.sex:
        return False
    if age_min is not None and not subject.age_days >= age_min:
        return False
    if age_max is not None and not subject.age_days < age_max:
        return False
    return True


# --- (a) the result's own range ------------------------------------------------------------------------


def _from_result(node: Node, subject: Subject | None) -> RangeSelection | Blocked:
    rr = node.reference_range
    assert rr is not None and node.value is not None

    def unverified(check: str, **extra) -> Blocked:
        return Blocked(OP, node.id, "result_range_unverified", {"check": check, **extra})

    if node.test is None or node.test != rr.test:
        return unverified("test_identity")
    if rr.kind != "reference":
        return unverified("kind", kind=rr.kind)
    if rr.interval.unit != node.value.unit:
        return unverified("unit", range_unit=rr.interval.unit, value_unit=node.value.unit)
    if rr.interval.lo is None and rr.interval.hi is None:
        return unverified("unbounded")   # one bucket over the whole line would carry no information
    a: AppliesTo = rr.applies_to
    if missing := _missing(_needed(a.sex, a.age_min_days, a.age_max_days), subject):
        return Blocked(OP, node.id, "subject_context_missing", {"missing": missing})
    if subject is not None and not _in_partition(a.sex, a.age_min_days, a.age_max_days, subject):
        return unverified("applies_to")
    if not rr.source:
        return unverified("source")
    if not rr.source_ref:
        return unverified("source_ref")
    source = {"kind": "result", "sha256": None, "range_id": None, "pdf_page": None, "raw": None,
              "mapping_row": None, "source": rr.source, "source_ref": rr.source_ref}
    return RangeSelection(rr.interval, source, ["reference_range attached to result", "test identity equal",
                                                "kind = reference", "unit equal", "applies_to satisfied",
                                                "source stated"])


# --- (b) Mayo ----------------------------------------------------------------------------------------


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _row_interval(row: dict[str, Any]) -> Interval | None:
    """The row's numeric interval, or None if its bounds are not numeric with a known operator on each side."""
    lo, lo_op, hi, hi_op = row["low"], row["low_op"] or None, row["high"], row["high_op"] or None
    if lo is None and hi is None:
        return None
    for v, op, table in ((lo, lo_op, _LOW_CLOSED), (hi, hi_op, _HIGH_CLOSED)):
        if (v is None) != (op is None) or (v is not None and (not _num(v) or op not in table)):
            return None
    if "=" in (lo_op, hi_op) and not (lo_op == hi_op == "=" and lo == hi):
        return None   # "=" is a point: both sides, one value
    try:
        return Interval(lo=lo, hi=hi, lo_closed=_LOW_CLOSED.get(lo_op, False),
                        hi_closed=_HIGH_CLOSED.get(hi_op, False), unit=row["unit"] or "")
    except ValidationError:
        return None


def _age_bounds_numeric(row: dict[str, Any]) -> bool:
    return all(row[k] is None or _num(row[k]) for k in ("age_min_days", "age_max_days"))


def _row_partition(row: dict[str, Any]) -> tuple[str | None, float | None, float | None]:
    return (None if row["sex"] == ANY_SEX else row["sex"]), row["age_min_days"], row["age_max_days"]


def _from_mayo(node: Node, subject: Subject | None, mayo: MayoSource) -> RangeSelection | Blocked:
    test, value = node.test, node.value
    assert test is not None and value is not None

    def block(reason: str, **detail) -> Blocked:
        return Blocked(OP, node.id, reason, detail)

    maps = mayo.mappings(test)
    if not maps:
        return block("no_test_mapping", system=test.system, code=test.code)
    fit = [m for m in maps if not (test.specimen and m["specimen"]) or m["specimen"] == test.specimen]
    if not fit:
        return block("specimen_mismatch", conflicting_source="test_map", test_specimen=test.specimen,
                     map_specimens=sorted({m["specimen"] for m in maps}))
    targets = sorted({(m["mnemonic"], m["analyte"]) for m in fit})
    if len(targets) > 1:
        return block("ambiguous_test_mapping", targets=[list(t) for t in targets])
    (mnemonic, analyte), = targets
    mayo_specimen = mayo.test_specimen(mnemonic)
    if test.specimen and mayo_specimen and mayo_specimen != test.specimen:
        return block("specimen_mismatch", conflicting_source="mayo_tests", test_specimen=test.specimen,
                     mnemonic=mnemonic, mayo_specimen=mayo_specimen)
    mapping_row = min(fit, key=lambda m: tuple(m[c] for c in MAP_COLUMNS))
    selection = [f"test_map: {test.system}|{test.code} -> {mnemonic} / {analyte}", "category = reference",
                 "confidence = high", "condition empty", "numeric bounds"]
    rows = mayo.ranges(mnemonic, analyte)
    cands = [(r, iv) for r in rows
             if r["category"] == "reference" and r["confidence"] == "high"
             and not (r["condition"] or "").strip() and _age_bounds_numeric(r)
             and (iv := _row_interval(r)) is not None]
    needed = set().union(*(_needed(*_row_partition(r)) for r, _ in cands))
    if missing := _missing(needed, subject):
        return block("subject_context_missing", missing=missing)
    if "sex" in needed and subject.sex not in mayo.sexes:
        return block("subject_sex_unrecognised", sex=subject.sex, known=list(mayo.sexes))
    if "sex" in needed:
        selection.append(f"sex in ({subject.sex}, {ANY_SEX})")
    if "age_days" in needed:
        selection.append(f"age_days {subject.age_days} in [age_min_days, age_max_days)")
    applicable = [(r, iv) for r, iv in cands if not needed or _in_partition(*_row_partition(r), subject)]
    if not applicable:
        return block("no_applicable_range", mnemonic=mnemonic, analyte=analyte, rows=len(rows),
                     candidates=len(cands))
    if len(applicable) > 1:
        return block("ambiguous_range", range_ids=[r["range_id"] for r, _ in applicable])
    (row, iv), = applicable
    if row["unit"] != value.unit:
        return block("units_not_convertible", range_unit=row["unit"], value_unit=value.unit,
                     range_id=row["range_id"])
    selection.append("unit equal")
    source = {"kind": "mayo", "sha256": mayo.sha256, "range_id": row["range_id"], "pdf_page": row["pdf_page"],
              "raw": row["raw"], "mapping_row": dict(mapping_row), "test_map_sha256": mayo.test_map_sha256}
    return RangeSelection(iv, source, selection)


def select_range(node: Node, subject: Subject | None, mayo: MayoSource | None) -> RangeSelection | Blocked:
    """The reference interval R for ``node``'s value, or why there is none (design §7.1 steps 1-3)."""
    if node.value is None:
        raise ValueError(f"node {node.id} has no value to bucket")
    if node.reference_range is not None:
        return _from_result(node, subject)
    if node.test is None:
        return Blocked(OP, node.id, "no_test_identity", {})
    if mayo is None:
        return Blocked(OP, node.id, "mayo_unavailable", {})
    return _from_mayo(node, subject, mayo)
