"""No clinical constants in ``src/`` or the packaged config (``src/semgen/resources/``, design §10): no SCTID-shaped integers (6-18 digits), no
FSN-shaped strings (``Term (tag)``) and no numeric literals in config values, except the exemptions listed in
``tests/fixtures/hardcoding_exemptions.yaml`` (each with value, file and reason). An exemption that no longer occurs in its
file is stale and fails the test, so the list cannot outlive what it excuses.

Python sources are scanned token by token (number literals; string literals, docstrings included); comments are
not constants and are skipped. Config values are read as YAML (or CSV cells) and walked. Hex digests (sha256) and
version strings are not numbers: runs of 32+ hex digits are removed from strings before the SCTID check.
"""
from __future__ import annotations

import ast
import csv
import io
import re
import tokenize
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
EXEMPTIONS = REPO / "tests" / "fixtures" / "hardcoding_exemptions.yaml"
RESOURCES = REPO / "src" / "semgen" / "resources"
SCTID = re.compile(r"(?<![\w.])\d{6,18}(?![\w.])")
HEX = re.compile(r"[0-9a-fA-F]{32,}")
FSN = re.compile(r"[A-Z][^()\n]*\s\([a-z][a-z /+-]*\)")   # a whole string "Term words (semantic tag)"
STRING_TOKENS = {tokenize.STRING} | ({tokenize.FSTRING_MIDDLE} if hasattr(tokenize, "FSTRING_MIDDLE") else set())


def _string_hits(text: str) -> list[str]:
    """SCTID-shaped digit runs anywhere in the string; the string itself if it is FSN-shaped as a whole (prose
    with a parenthesis is not an FSN)."""
    return SCTID.findall(HEX.sub("", text)) + ([text.strip()] if FSN.fullmatch(text.strip()) else [])


def _py_hits(path: Path) -> list[str]:
    hits: list[str] = []
    with path.open("rb") as f:
        for tok in tokenize.tokenize(f.readline):
            if tok.type == tokenize.NUMBER:
                digits = tok.string.replace("_", "")
                if re.fullmatch(r"\d{6,18}", digits):
                    hits.append(digits)
            elif tok.type == tokenize.STRING:
                value = ast.literal_eval(tok.string)
                hits += _string_hits(value.decode("latin-1") if isinstance(value, bytes) else value)
            elif tok.type in STRING_TOKENS:   # the literal text of an f-string
                hits += _string_hits(tok.string)
    return hits


def _walk(value, hits: list[str]) -> None:
    if isinstance(value, dict):
        for v in value.values():
            _walk(v, hits)
    elif isinstance(value, list):
        for v in value:
            _walk(v, hits)
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, (int, float)):
        hits.append(str(value))          # any numeric literal in a config value
    elif isinstance(value, str):
        hits += _string_hits(value)


def _config_hits(path: Path) -> list[str]:
    hits: list[str] = []
    text = path.read_text(encoding="utf-8")
    if path.suffix in {".yaml", ".yml"}:
        _walk(yaml.safe_load(text), hits)
    elif path.suffix == ".csv":
        for row in csv.reader(io.StringIO(text)):
            for cell in row:
                hits += [cell] if re.fullmatch(r"-?\d+(\.\d+)?", cell) else _string_hits(cell)
    else:
        hits += _string_hits(text)
    return hits


def scan() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for p in sorted((REPO / "src").rglob("*.py")):
        found += [(str(p.relative_to(REPO)), v) for v in _py_hits(p)]
    for p in sorted(RESOURCES.rglob("*")):
        if p.is_file() and p.suffix in {".yaml", ".yml", ".csv", ".json", ".txt"}:
            found += [(str(p.relative_to(REPO)), v) for v in _config_hits(p)]
    return found


def exemptions() -> list[dict]:
    rows = yaml.safe_load(EXEMPTIONS.read_text(encoding="utf-8"))["exemptions"]
    for r in rows:
        assert set(r) == {"value", "file", "reason"} and all(isinstance(r[k], str) and r[k] for k in r), r
    return rows


def test_no_clinical_constants_in_src_or_config():
    allowed = {(r["file"], r["value"]) for r in exemptions()}
    found = scan()
    unexpected = sorted(set(found) - allowed)
    assert not unexpected, f"hard-coded clinical constants (add a reasoned exemption only if legitimate): {unexpected}"
    stale = sorted(allowed - set(found))
    assert not stale, f"stale exemptions (no longer in their file): {stale}"


def test_scanner_detects_each_kind(tmp_path):
    """The scanner is not vacuous: each kind of constant is found."""
    p = tmp_path / "x.py"
    p.write_text('X = 73211009\nY = "Diabetes mellitus (disorder)"\nZ = f"code {1}: 44054006"\n'
                 'H = "3edbad893eaca3825a3f161cf7c0b60df4026ff17f32ebf14d3c3a7fa4b4a107"\n# 46635009 in a comment\n')
    assert _py_hits(p) == ["73211009", "Diabetes mellitus (disorder)", "44054006"]
    c = tmp_path / "c.yaml"
    c.write_text("a: {b: 2500, c: true, d: 'Substance (substance)', sha: 'abc'}\n")
    assert _config_hits(c) == ["2500", "Substance (substance)"]
