"""Reference-range selection (design §7.1): the result's own range first, then Mayo, then a Blocked reason.

Every row, map and range here is SYNTHETIC (built in tmp_path), except ``test_real_alt_has_no_rows``.
"""
import tempfile
from pathlib import Path

import pytest

from semgen.bundle import Subject
from semgen.config import ConfigError, load_config
from semgen.model import AppliesTo, Interval, Node, ReferenceRange, TestIdentity
from semgen.operators.base import Blocked
from semgen.refrange import MayoSource, RangeSelection, mayo_db_path, open_mayo, select_range
from semgen.settings import default_config_path  # noqa: E402
from tests.support import mayo_fixture

CFG = default_config_path()
TEST = TestIdentity(system="urn:synthetic:lab", code="SALT", method="kinetic", specimen="Serum")
MAP_ROW = {"system": TEST.system, "code": TEST.code, "mnemonic": "SALT", "analyte": "Synthetic ALT",
           "specimen": "Serum", "page_ref": "p. 1", "reviewed_by": "synthetic"}
ROW = {"mnemonic": "SALT", "analyte": "Synthetic ALT", "low": 7.0, "low_op": ">=", "high": 56.0, "high_op": "<=",
       "unit": "U/L", "pdf_page": 3, "raw": "7-56 U/L"}
ADULT_MALE = Subject(sex="male", age_days=20000)


def node(value=145.0, unit="U/L", test=TEST, rr=None):
    return Node(id="n3", type="Observable", role="outcome", code="X", value=Interval.point(value, unit),
                test=test, reference_range=rr)


def rr(**kw):
    base = {"interval": Interval.closed(7, 56, "U/L"), "kind": "reference", "test": TEST,
            "applies_to": AppliesTo(), "source": "synthetic-lab-report", "source_ref": "obs/1#range"}
    return ReferenceRange(**{**base, **kw})


def mayo(tmp_path, rows, map_rows=(MAP_ROW,), tests=()):
    d = Path(tempfile.mkdtemp(dir=tmp_path))    # a fresh directory per source
    db = mayo_fixture.build(d, list(rows), list(tests))
    tm = mayo_fixture.write_map(d, list(map_rows)) if map_rows is not None else None
    return MayoSource.open(db, mayo_fixture.sha256(db), tm)


def blocked(res, reason):
    assert isinstance(res, Blocked), res
    assert (res.op, res.target, res.reason) == ("normative_bucketing", "n3", reason), res
    return res.detail


class NeverConsulted:
    """A Mayo stand-in that fails the test if selection touches it at all."""

    def __getattr__(self, name):
        raise AssertionError(f"Mayo consulted ({name}) although the result carries a reference range")


# --- Mayo path (b) ------------------------------------------------------------------------------


def test_exact_mapping_required(tmp_path):
    src = mayo(tmp_path, [ROW], [{**MAP_ROW, "code": "salt"}])           # code differs only in case
    assert blocked(select_range(node(), ADULT_MALE, src), "no_test_mapping") == {
        "system": TEST.system, "code": TEST.code}
    other_system = node(test=TEST.model_copy(update={"system": "urn:other"}))
    blocked(select_range(other_system, ADULT_MALE, mayo(tmp_path, [ROW])), "no_test_mapping")
    blocked(select_range(node(test=None), ADULT_MALE, src), "no_test_identity")


def test_no_map_file_is_no_test_mapping(tmp_path):
    src = mayo(tmp_path, [ROW], map_rows=None)
    assert src.test_map_sha256 is None
    blocked(select_range(node(), ADULT_MALE, src), "no_test_mapping")


def test_mayo_unavailable_and_missing_identity_order():
    blocked(select_range(node(), ADULT_MALE, None), "mayo_unavailable")
    blocked(select_range(node(test=None), ADULT_MALE, None), "no_test_identity")


def test_specimen_mismatch_blocks(tmp_path):
    src = mayo(tmp_path, [ROW], [{**MAP_ROW, "specimen": "Plasma"}])
    d = blocked(select_range(node(), ADULT_MALE, src), "specimen_mismatch")
    assert d == {"conflicting_source": "test_map", "test_specimen": "Serum", "map_specimens": ["Plasma"]}
    # Compared only when both are stated: an unstated map specimen or test specimen does not block.
    ok = select_range(node(), ADULT_MALE, mayo(tmp_path, [ROW], [{**MAP_ROW, "specimen": ""}]))
    assert isinstance(ok, RangeSelection)
    ok = select_range(node(test=TEST.model_copy(update={"specimen": None})), ADULT_MALE, src)
    assert isinstance(ok, RangeSelection)


def test_mayo_tests_specimen_conflict_blocks(tmp_path):
    """Controller ruling (fix round 1): a specimen stated by Mayo's tests table must also equal the test's."""
    plasma = [{"mnemonic": "SALT", "specimen": "Plasma"}]
    src = mayo(tmp_path, [ROW], tests=plasma)           # map row says Serum (agrees), Mayo tests says Plasma
    d = blocked(select_range(node(), ADULT_MALE, src), "specimen_mismatch")
    assert d == {"conflicting_source": "mayo_tests", "test_specimen": "Serum", "mnemonic": "SALT",
                 "mayo_specimen": "Plasma"}
    agree = mayo(tmp_path, [ROW], tests=[{"mnemonic": "SALT", "specimen": "Serum"}])
    assert isinstance(select_range(node(), ADULT_MALE, agree), RangeSelection)
    unstated = node(test=TEST.model_copy(update={"specimen": None}))   # compared only when both are stated
    assert isinstance(select_range(unstated, ADULT_MALE, src), RangeSelection)
    blank = mayo(tmp_path, [ROW], tests=[{"mnemonic": "SALT", "specimen": None}])
    assert isinstance(select_range(node(), ADULT_MALE, blank), RangeSelection)


def test_ambiguous_mapping_blocks(tmp_path):
    src = mayo(tmp_path, [ROW], [MAP_ROW, {**MAP_ROW, "analyte": "Other analyte"}])
    d = blocked(select_range(node(), ADULT_MALE, src), "ambiguous_test_mapping")
    assert d["targets"] == [["SALT", "Other analyte"], ["SALT", "Synthetic ALT"]]


def test_sex_and_age_partition_selection(tmp_path):
    rows = [{**ROW, "range_id": "M-CHILD", "sex": "male", "age_min_days": 0, "age_max_days": 6570, "high": 40.0},
            {**ROW, "range_id": "M-ADULT", "sex": "male", "age_min_days": 6570.0, "age_max_days": None},
            {**ROW, "range_id": "F-ALL", "sex": "female", "high": 35.0}]
    src = mayo(tmp_path, rows)
    pick = lambda s: select_range(node(), s, src).source["range_id"]
    assert pick(Subject(sex="male", age_days=6569)) == "M-CHILD"
    assert pick(Subject(sex="male", age_days=6570)) == "M-ADULT"    # min inclusive, max exclusive
    assert pick(Subject(sex="male", age_days=0)) == "M-CHILD"
    assert pick(Subject(sex="female", age_days=3)) == "F-ALL"
    blocked(select_range(node(), Subject(sex="other", age_days=3), src), "subject_sex_unrecognised")
    # a recognised sex (it occurs elsewhere in the source) with no row for this analyte: no applicable range
    other = mayo(tmp_path, rows[:2] + [{**ROW, "range_id": "Z", "analyte": "Other", "sex": "female"}])
    blocked(select_range(node(), Subject(sex="female", age_days=3), other), "no_applicable_range")


def test_partial_subject_needed_field_missing(tmp_path):
    rows = [{**ROW, "range_id": "A", "age_min_days": 0, "age_max_days": 6570},
            {**ROW, "range_id": "B", "age_min_days": 6570, "age_max_days": None}]
    src = mayo(tmp_path, rows)
    assert blocked(select_range(node(), Subject(sex="male", age_days=None), src),
                   "subject_context_missing") == {"missing": ["age_days"]}
    assert blocked(select_range(node(), None, src), "subject_context_missing") == {"missing": ["age_days"]}
    sexed = mayo(tmp_path, [{**r, "sex": "male"} for r in rows])
    assert blocked(select_range(node(), None, sexed), "subject_context_missing") == {
        "missing": ["age_days", "sex"]}


def test_partial_subject_unneeded_field_missing_ok(tmp_path):
    rows = [{**ROW, "range_id": "M", "sex": "male"}, {**ROW, "range_id": "F", "sex": "female", "high": 35.0}]
    sel = select_range(node(), Subject(sex="female", age_days=None), mayo(tmp_path, rows))
    assert isinstance(sel, RangeSelection) and sel.source["range_id"] == "F"
    assert sel.interval == Interval.closed(7, 35, "U/L")
    sel = select_range(node(), None, mayo(tmp_path, [ROW]))    # nothing partitions: no subject needed
    assert isinstance(sel, RangeSelection)


def test_sex_vocabulary_read_from_source(tmp_path):
    rows = [{**ROW, "range_id": "M", "sex": "male"}, {**ROW, "range_id": "F", "sex": "female", "high": 35.0},
            {**ROW, "range_id": "X", "mnemonic": "OTHER", "analyte": "Other", "sex": "unspecified"}]
    assert mayo(tmp_path, rows).sexes == ("female", "male", "unspecified")   # DISTINCT, minus the "any" wildcard
    assert mayo(tmp_path, [ROW]).sexes == ()


def test_unrecognised_subject_sex_blocks(tmp_path):
    rows = [{**ROW, "range_id": "M", "sex": "male"}, {**ROW, "range_id": "F", "sex": "female", "high": 35.0}]
    d = blocked(select_range(node(), Subject(sex="F", age_days=20000), mayo(tmp_path, rows)),
                "subject_sex_unrecognised")
    assert d == {"sex": "F", "known": ["female", "male"]}


def test_sex_abbreviation_no_longer_buckets_on_overlap(tmp_path):
    """"F" used to drop the female row silently and pick the ``any`` row; "female" sees both and is ambiguous."""
    rows = [{**ROW, "range_id": "ANY"}, {**ROW, "range_id": "F", "sex": "female", "high": 35.0}]
    src = mayo(tmp_path, rows)
    blocked(select_range(node(), Subject(sex="F", age_days=20000), src), "subject_sex_unrecognised")
    assert blocked(select_range(node(), Subject(sex="female", age_days=20000), src),
                   "ambiguous_range") == {"range_ids": ["ANY", "F"]}


def test_recognised_or_unneeded_sex_unchanged(tmp_path):
    rows = [{**ROW, "range_id": "M", "sex": "male"}, {**ROW, "range_id": "F", "sex": "female", "high": 35.0}]
    sel = select_range(node(), Subject(sex="female", age_days=20000), mayo(tmp_path, rows))
    assert sel.source["range_id"] == "F"
    # no candidate row partitions on sex: the subject's sex is not needed, so it is not checked
    sel = select_range(node(), Subject(sex="F", age_days=20000), mayo(tmp_path, [ROW]))
    assert isinstance(sel, RangeSelection) and sel.source["range_id"] == "SALT-1"


def test_ambiguous_rows(tmp_path):
    src = mayo(tmp_path, [{**ROW, "range_id": "A"}, {**ROW, "range_id": "B", "high": 60.0}])
    assert blocked(select_range(node(), ADULT_MALE, src), "ambiguous_range") == {"range_ids": ["A", "B"]}


def test_condition_and_non_reference_and_low_confidence_rows_ignored(tmp_path):
    rows = [{**ROW, "range_id": "GOOD"},
            {**ROW, "range_id": "COND", "condition": "Therapeutic"},
            {**ROW, "range_id": "CRIT", "category": "Critical value"},
            {**ROW, "range_id": "MED", "confidence": "medium"},
            {**ROW, "range_id": "LOWC", "confidence": "low"},
            {**ROW, "range_id": "NONUM", "low": None, "low_op": None, "high": None, "high_op": None},
            {**ROW, "range_id": "TEXT", "low": "7", "high": "56"},
            {**ROW, "range_id": "OTHER", "analyte": "Different analyte"},
            {**ROW, "range_id": "EMPTYCOND", "condition": "", "high": 50.0}]
    d = blocked(select_range(node(), ADULT_MALE, mayo(tmp_path, rows)), "ambiguous_range")
    assert d == {"range_ids": ["EMPTYCOND", "GOOD"]}     # an empty-string condition counts as no condition
    sel = select_range(node(), ADULT_MALE, mayo(tmp_path, rows[:-1]))
    assert sel.source["range_id"] == "GOOD"
    assert sel.selection == ["test_map: urn:synthetic:lab|SALT -> SALT / Synthetic ALT", "category = reference",
                             "confidence = high", "condition empty", "numeric bounds", "unit equal"]


def test_unit_mismatch(tmp_path):
    src = mayo(tmp_path, [{**ROW, "unit": "IU/L"}])
    assert blocked(select_range(node(), ADULT_MALE, src), "units_not_convertible") == {
        "range_unit": "IU/L", "value_unit": "U/L", "range_id": "SALT-1"}


@pytest.mark.parametrize("ops,expected", [
    ((">=", "<="), Interval(lo=7, hi=56, unit="U/L")),
    ((">", "<"), Interval(lo=7, hi=56, lo_closed=False, hi_closed=False, unit="U/L")),
    ((">=", "<"), Interval(lo=7, hi=56, hi_closed=False, unit="U/L")),
])
def test_mayo_operators_map_to_closure(tmp_path, ops, expected):
    sel = select_range(node(), ADULT_MALE, mayo(tmp_path, [{**ROW, "low_op": ops[0], "high_op": ops[1]}]))
    assert sel.interval == expected


def test_mayo_one_sided_and_point_rows(tmp_path):
    upper = {**ROW, "low": None, "low_op": None, "high": 40.0, "high_op": "<"}
    sel = select_range(node(), ADULT_MALE, mayo(tmp_path, [upper]))
    assert sel.interval == Interval(lo=None, hi=40, hi_closed=False, unit="U/L")
    point = {**ROW, "low": 5.0, "low_op": "=", "high": 5.0, "high_op": "="}
    assert select_range(node(), ADULT_MALE, mayo(tmp_path, [point])).interval == Interval.point(5, "U/L")


def test_mayo_source_record(tmp_path):
    src = mayo(tmp_path, [ROW])
    sel = select_range(node(), ADULT_MALE, src)
    assert sel.source == {"kind": "mayo", "sha256": src.sha256, "range_id": "SALT-1", "pdf_page": 3,
                          "raw": "7-56 U/L", "mapping_row": MAP_ROW, "test_map_sha256": src.test_map_sha256}


def test_open_rejects_sha_mismatch_and_bad_map(tmp_path):
    db = mayo_fixture.build(tmp_path, [ROW])
    with pytest.raises(ConfigError, match="sha256"):
        MayoSource.open(db, "0" * 64, None)
    bad = tmp_path / "bad.csv"
    bad.write_text("system,code\nx,y\n")
    with pytest.raises(ConfigError, match="columns"):
        MayoSource.open(db, mayo_fixture.sha256(db), bad)


def test_missing_db_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("SEMGEN_MAYO_DB", str(tmp_path / "nope.sqlite"))
    cfg = load_config(CFG)
    assert mayo_db_path(cfg.mayo) == tmp_path / "nope.sqlite"
    assert open_mayo(cfg.mayo) is None


def test_env_override_opens_with_pinned_sha(tmp_path, monkeypatch):
    db = mayo_fixture.build(tmp_path, [ROW])
    monkeypatch.setenv("SEMGEN_MAYO_DB", str(db))
    with pytest.raises(ConfigError, match="sha256"):      # the config pins the real DB's sha256
        open_mayo(load_config(CFG).mayo)


# --- result range path (a) -----------------------------------------------------------------------


@pytest.mark.parametrize("bad,check", [
    ({"node_test": None}, "test_identity"),
    ({"test": TEST.model_copy(update={"method": "other"})}, "test_identity"),
    ({"test": TEST.model_copy(update={"specimen": None})}, "test_identity"),    # null != stated
    ({"kind": "critical"}, "kind"),
    ({"interval": Interval.closed(7, 56, "IU/L")}, "unit"),
    ({"interval": Interval(lo=None, hi=None, unit="U/L")}, "unbounded"),
    ({"applies_to": AppliesTo(sex="female")}, "applies_to"),
    ({"applies_to": AppliesTo(age_min_days=0, age_max_days=6570)}, "applies_to"),
    ({"source": ""}, "source"),
    ({"source_ref": ""}, "source_ref"),
])
def test_result_range_checks(bad, check):
    kw = {k: v for k, v in bad.items() if k != "node_test"}
    n = node(test=bad.get("node_test", TEST), rr=rr(**kw))
    d = blocked(select_range(n, ADULT_MALE, NeverConsulted()), "result_range_unverified")
    assert d["check"] == check


def test_result_range_null_fields_equal():
    t = TestIdentity(system="urn:synthetic:lab", code="SALT")
    sel = select_range(node(test=t, rr=rr(test=t)), ADULT_MALE, NeverConsulted())
    assert isinstance(sel, RangeSelection) and sel.source["kind"] == "result"


def test_result_range_selected_without_mayo():
    sel = select_range(node(rr=rr()), ADULT_MALE, NeverConsulted())
    assert sel.interval == Interval.closed(7, 56, "U/L")
    assert sel.source == {"kind": "result", "sha256": None, "range_id": None, "pdf_page": None, "raw": None,
                          "mapping_row": None, "source": "synthetic-lab-report", "source_ref": "obs/1#range"}
    assert sel.selection == ["reference_range attached to result", "test identity equal", "kind = reference",
                             "unit equal", "applies_to satisfied", "source stated"]


def test_result_range_age_bounds_semantics():
    band = rr(applies_to=AppliesTo(age_min_days=100, age_max_days=200))
    ok = lambda age: isinstance(select_range(node(rr=band), Subject(sex="male", age_days=age), NeverConsulted()),
                                RangeSelection)
    assert ok(100) and ok(199) and not ok(200) and not ok(99)
    open_hi = rr(applies_to=AppliesTo(age_min_days=100))
    assert isinstance(select_range(node(rr=open_hi), Subject(age_days=10**6), NeverConsulted()), RangeSelection)
    d = blocked(select_range(node(rr=band), Subject(sex="male"), NeverConsulted()), "subject_context_missing")
    assert d == {"missing": ["age_days"]}
    d = blocked(select_range(node(rr=rr(applies_to=AppliesTo(sex="male"))), None, NeverConsulted()),
                "subject_context_missing")
    assert d == {"missing": ["sex"]}


# --- real data ----------------------------------------------------------------------------------


def test_real_alt_has_no_rows(tmp_path):
    cfg = load_config(CFG).mayo
    db = mayo_db_path(cfg)
    if db is None or not db.exists():
        pytest.skip("Mayo refrange.sqlite not available (set SEMGEN_MAYO_DB)")
    # A SYNTHETIC map row pointing a synthetic test code at Mayo ALT; the real DB has no ALT range rows.
    tm = mayo_fixture.write_map(tmp_path, [{**MAP_ROW, "mnemonic": "ALT",
                                            "analyte": "Alanine Aminotransferase (ALT) (GPT)"}])
    src = MayoSource.open(db, cfg.sha256, tm)
    d = blocked(select_range(node(), ADULT_MALE, src), "no_applicable_range")
    assert d["mnemonic"] == "ALT" and d["rows"] == 0


@pytest.mark.snomed
def test_build_context_wires_mayo(monkeypatch, tmp_path):
    import os

    from semgen.context import build_context
    from semgen.snomed import default_rf2_dir
    if default_rf2_dir() is None or not default_rf2_dir().exists():
        pytest.skip("RF2 directory not found")
    real = os.environ.get("SEMGEN_MAYO_DB")
    monkeypatch.setenv("SEMGEN_MAYO_DB", str(tmp_path / "missing.sqlite"))
    ctx = build_context(CFG)
    assert ctx.refranges is None and ctx.subject is None
    monkeypatch.delenv("SEMGEN_MAYO_DB")
    assert mayo_db_path(load_config(CFG).mayo) is None    # the packaged config names no location
    if real is None or not Path(real).exists():
        pytest.skip("Mayo refrange.sqlite not available (set SEMGEN_MAYO_DB)")
    monkeypatch.setenv("SEMGEN_MAYO_DB", real)
    ctx = build_context(CFG)
    assert ctx.refranges is not None and ctx.refranges.sha256 == load_config(CFG).mayo.sha256
    assert ctx.refranges.test_map is None and ctx.refranges.test_map_sha256 is None   # no mayo_test_map.csv
