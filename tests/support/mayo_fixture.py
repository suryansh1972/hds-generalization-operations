"""Synthetic ``refrange.sqlite`` with the real Mayo schema (tables ``tests``, ``ranges``, ``context``).

Rows are SYNTHETIC test data, not Mayo values. ``build`` fills every unspecified column with NULL, except the
filter columns a usable reference row needs (category, confidence, sex), which default to a usable row.
"""
from __future__ import annotations

import csv
import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

TESTS_COLUMNS = ("mnemonic", "test_id", "name", "analyte_default", "specimen", "specimen_classes", "orderable",
                 "result_kind", "n_ranges", "n_numeric_ranges", "conditions", "pdf_page", "reference_text",
                 "useful_for", "interpretation", "clinical_information")
RANGES_COLUMNS = ("range_id", "mnemonic", "test_name", "analyte", "sex", "age_text", "age_min_days", "age_max_days",
                  "condition", "condition_type", "guideline", "category", "label", "low", "low_op", "high", "high_op",
                  "below_limit", "low_text", "qualitative", "unit", "display_value", "source_section", "confidence",
                  "pdf_page", "raw")
CONTEXT_COLUMNS = ("mnemonic", "kind", "section", "text", "conditions", "pdf_page")
MAP_COLUMNS = ("system", "code", "mnemonic", "analyte", "specimen", "page_ref", "reviewed_by")

RANGE_DEFAULTS = {"category": "reference", "confidence": "high", "sex": "any"}


def build(tmp_path: Path, rows: list[dict], tests: list[dict] = (), name: str = "refrange.sqlite") -> Path:
    """Write a fixture DB; each ``rows`` dict is one ``ranges`` row (unknown keys are an error)."""
    p = Path(tmp_path) / name
    with closing(sqlite3.connect(p)) as con:
        con.execute(f"CREATE TABLE tests ({', '.join(TESTS_COLUMNS)})")
        con.execute(f"CREATE TABLE ranges ({', '.join(RANGES_COLUMNS)})")
        con.execute(f"CREATE TABLE context ({', '.join(CONTEXT_COLUMNS)})")
        for table, cols, items, defaults in (("ranges", RANGES_COLUMNS, rows, RANGE_DEFAULTS),
                                             ("tests", TESTS_COLUMNS, tests, {})):
            for i, r in enumerate(items):
                assert set(r) <= set(cols), set(r) - set(cols)
                full = {**defaults, **r}
                if table == "ranges":
                    full.setdefault("range_id", f"{full.get('mnemonic', 'X')}-{i + 1}")
                con.execute(f"INSERT INTO {table} VALUES ({', '.join('?' * len(cols))})",
                            [full.get(c) for c in cols])
        con.commit()
    return p


def sha256(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write_map(tmp_path: Path, rows: list[dict], name: str = "mayo_test_map.csv") -> Path:
    """A SYNTHETIC test map with the design's columns; missing columns are written empty."""
    p = Path(tmp_path) / name
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MAP_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in MAP_COLUMNS})
    return p
