import json

import pytest

from semgen.motif_io import MotifError, load_motifs, parse_motif
from semgen.snomed import FsnError


def base():  # minimal valid motif, codes already filled
    return {"motif_id": "T", "anchor": "n1",
            "nodes": [{"id": "P", "type": "Patient", "role": "patient"},
                      {"id": "n1", "type": "Disorder", "code": "1", "polarity": "present", "role": "anchor"},
                      {"id": "n2", "type": "Disorder", "code": "2", "polarity": "absent", "role": "modifier"}],
            "edges": [{"s": "P", "t": "n1", "rel": "has_condition", "prov": "asserted"},
                      {"s": "P", "t": "n2", "rel": "has_condition", "prov": "asserted"}]}


def test_absent_node_must_be_patient_leaf():
    d = base(); d["edges"].append({"s": "n1", "t": "n2", "rel": "x", "prov": "asserted"})
    with pytest.raises(MotifError, match="absent"): parse_motif(d, None)


@pytest.mark.parametrize("extra", [
    {"value": {"interval": [1, 2], "unit": "%"}},
    {"attrs": {"age_at_dx": {"interval": [1, 2], "unit": "a"}}},
])
def test_absent_node_with_value_or_attrs_rejected(extra):
    d = base(); d["nodes"][2].update(extra)
    with pytest.raises(MotifError, match="absent"): parse_motif(d, None)


@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d["edges"].append({"s": "P", "t": "zz", "rel": "r", "prov": "asserted"}), "unknown node"),
    (lambda d: d.update(anchor="nX"), "anchor"),
    (lambda d: d["edges"].pop(0), "anchor"),
    (lambda d: d["edges"].append({"s": "P", "t": "n1", "rel": "other", "prov": "asserted"}), "parallel"),
    (lambda d: d["nodes"][1].update(attrs={"age_at_dx": {"interval": [92, 92], "unit": "a"}}), "90"),
    (lambda d: d["nodes"][1].update(attrs={"age_at_dx": {"interval": [90, 95], "unit": "a"}}), "90"),
])
def test_structural_rejections(mutate, msg):
    d = base(); mutate(d)
    with pytest.raises(MotifError, match=msg) as ei:
        parse_motif(d, None)
    assert "T" in str(ei.value)


def test_age_90_open_ended_allowed():
    d = base(); d["nodes"][1]["attrs"] = {"age_at_dx": {"interval": [90, None], "unit": "a"}}
    iv = parse_motif(d, None).node("n1").attrs["age_at_dx"]
    assert (iv.lo, iv.hi) == (90, None)


def test_window_becomes_closed_interval():
    d = base(); d["nodes"].append({"id": "n3", "type": "Substance", "code": "3", "polarity": "present", "role": "exposure"})
    d["edges"] += [{"s": "P", "t": "n3", "rel": "administered_drug", "prov": "asserted"},
                   {"s": "n3", "t": "n1", "rel": "followed_by", "prov": "asserted", "time": {"window": [23, 23], "unit": "d"}}]
    w = parse_motif(d, None).edge("n3", "n1").window
    assert (w.lo, w.hi, w.lo_closed, w.hi_closed, w.unit) == (23, 23, True, True, "d")


def test_null_code_without_hierarchy_is_error():
    d = base(); d["nodes"][1].update(code=None, label="Foo (disorder)")
    with pytest.raises(MotifError, match="Foo"): parse_motif(d, None)


def test_null_code_without_label_is_error():
    d = base(); d["nodes"][1].update(code=None)
    with pytest.raises(MotifError, match="n1"): parse_motif(d, None)


def test_fsn_error_wrapped(fake_h):
    d = base(); d["nodes"][1].update(code=None, label="No such thing (disorder)")
    with pytest.raises(MotifError, match="No such thing") as ei:
        parse_motif(d, fake_h)
    assert "T" in str(ei.value) and "n1" in str(ei.value)
    assert isinstance(ei.value.__cause__, FsnError)


def test_unknown_field_is_motif_error():
    d = base(); d["nodes"][1]["bogus"] = 1
    with pytest.raises(MotifError, match="n1.*bogus"): parse_motif(d, None)


def test_pydantic_type_error_is_chained():
    d = base(); d["edges"][0]["prov"] = "invented"
    with pytest.raises(MotifError, match="P->n1") as ei: parse_motif(d, None)
    assert ei.value.__cause__ is not None


def test_load_motifs_errors(tmp_path):
    with pytest.raises(MotifError, match="nope"): load_motifs(tmp_path / "nope.json", None)
    p = tmp_path / "bad.json"; p.write_text("{not json")
    with pytest.raises(MotifError, match="bad.json"): load_motifs(p, None)


def test_load_motifs_accepts_list_and_object(tmp_path):
    p = tmp_path / "a.json"; p.write_text(json.dumps([base()]))
    q = tmp_path / "b.json"; q.write_text(json.dumps({"_comment": "x", "motifs": [base()]}))
    assert [m.motif_id for m in load_motifs(p, None)] == ["T"]
    assert [m.motif_id for m in load_motifs(q, None)] == ["T"]


def test_fake_fixtures_parse(fake_m1, fake_m2):
    assert fake_m1.node("n2").attrs["cumulative_dose"].unit == "mg/m2"
    assert fake_m1.edge("n2", "n3").window.lo == 23
    assert fake_m2.node("n2").polarity == "absent"
    assert fake_m2.node("n5").value.lo == 42


@pytest.mark.snomed
def test_real_motifs_resolve(real_motifs):
    ids = {m.motif_id: m for m in real_motifs}
    assert set(ids) == {"M1", "M2", "M3", "M4"}
    assert ids["M2"].node("n1").code == "44054006" and ids["M2"].node("n2").code == "46635009"
    assert ids["M3"].node(ids["M3"].anchor).code == "703228009"
    assert ids["M4"].node("n3").code == "364571000119101" and ids["M4"].node("n3").value.unit == "xULN"


def _with_window(window, unit="d"):
    d = base(); d["nodes"].append({"id": "n3", "type": "Substance", "code": "3", "polarity": "present", "role": "exposure"})
    d["edges"] += [{"s": "P", "t": "n3", "rel": "administered_drug", "prov": "asserted"},
                   {"s": "n3", "t": "n1", "rel": "followed_by", "prov": "asserted",
                    "time": {"window": window, "unit": unit}}]
    return d


@pytest.mark.parametrize("window,unit,msg", [([-1, 5], "d", "negative"), ([None, 5], "d", "negative"),
                                             ([1, 5], "h", "unit")])
def test_bad_window_rejected(window, unit, msg):
    with pytest.raises(MotifError, match=msg) as ei: parse_motif(_with_window(window, unit), None)
    assert "T" in str(ei.value) and "n3->n1" in str(ei.value)


def test_window_zero_to_open_allowed():
    w = parse_motif(_with_window([0, None]), None).edge("n3", "n1").window
    assert (w.lo, w.hi) == (0, None)


# --- Task 1: bundles and new node/edge keys ---
from semgen.bundle import MotifBundle  # noqa: E402
from semgen.canonical import motif_hash  # noqa: E402
from semgen.motif_io import load_bundles, parse_bundle  # noqa: E402


def _named(mid):
    d = base(); d["motif_id"] = mid
    return d


def _bundle(*motifs, **kw):
    return {"bundle_id": "B1", "semantics": "all", "anchor_motif": "M1", "motifs": list(motifs)} | kw


def test_bundle_namespaces_clashing_ids():
    m1, m2 = _named("M1"), _named("M2")
    m2["nodes"].append({"id": "n3", "type": "Substance", "code": "3", "polarity": "present", "role": "exposure"})
    m2["edges"] += [{"s": "P", "t": "n3", "rel": "administered_drug", "prov": "asserted"},
                    {"s": "n3", "t": "n1", "rel": "followed_by", "prov": "asserted"}]
    b = parse_bundle(_bundle(m1, m2), None)
    assert [p.part_id for p in b.parts] == ["M1", "M2"] and b.anchor_part == "M1" and b.semantics == "all"
    p1, p2 = b.part("M1").motif, b.part("M2").motif
    assert p1.node_ids == {"P", "M1.n1", "M1.n2"} and p2.node_ids == {"P", "M2.n1", "M2.n2", "M2.n3"}
    assert p1.anchor == "M1.n1" and p2.anchor == "M2.n1"
    assert {e.key for e in p2.edges} == {("P", "M2.n1"), ("P", "M2.n2"), ("P", "M2.n3"), ("M2.n3", "M2.n1")}
    assert p2.edge("M2.n3", "M2.n1").rel == "followed_by"
    non_p = [i for p in b.parts for i in p.motif.node_ids if i != "P"]
    assert len(non_p) == len(set(non_p))
    assert p1.node("M1.n2").polarity == "absent" and p1.edge("P", "M1.n2") is not None


def test_bundle_of_one_keeps_ids_and_hash():
    b = parse_bundle({"bundle_id": "B", "motifs": [_named("M1")]}, None)
    m = parse_motif(_named("M1"), None)
    assert b.is_single and b.semantics == "all" and b.anchor_part == "M1"
    assert b.single_motif == m and motif_hash(b.single_motif) == motif_hash(m)


def test_bundle_requires_anchor_motif_when_multi():
    raw = _bundle(_named("M1"), _named("M2")); raw.pop("anchor_motif")
    with pytest.raises(MotifError, match="anchor_motif"): parse_bundle(raw, None)
    with pytest.raises(MotifError, match="anchor_motif"):
        parse_bundle(_bundle(_named("M1"), _named("M2"), anchor_motif="M9"), None)


def test_bundle_semantics_missing_is_none_and_bad_value_rejected():
    raw = _bundle(_named("M1"), _named("M2")); raw.pop("semantics")
    assert parse_bundle(raw, None).semantics is None
    with pytest.raises(MotifError, match="semantics"):
        parse_bundle(_bundle(_named("M1"), _named("M2"), semantics="both"), None)


def test_agg_prefix_is_no_longer_reserved():
    """Aggregate parts were removed with motif aggregation, so ``agg:`` is an ordinary motif id."""
    b = parse_bundle(_bundle(_named("M1"), _named('agg:["x"]')), None)
    assert {p.part_id for p in b.parts} == {"M1", 'agg:["x"]'}


def test_bundle_rejects_duplicate_motif_ids():
    with pytest.raises(MotifError, match="duplicate"):
        parse_bundle(_bundle(_named("M1"), _named("M1")), None)


def test_bundle_rejects_mismatched_patient_nodes():
    m2 = _named("M2"); m2["nodes"][0]["label"] = "someone else"
    with pytest.raises(MotifError, match="patient node"):
        parse_bundle(_bundle(_named("M1"), m2), None)


def test_bundle_subject_parsed():
    b = parse_bundle(_bundle(_named("M1"), _named("M2"), subject={"sex": "F", "age_days": 21000}), None)
    assert (b.subject.sex, b.subject.age_days) == ("F", 21000)
    with pytest.raises(MotifError, match="subject"):
        parse_bundle(_bundle(_named("M1"), _named("M2"), subject={"sex": "F", "age": 1}), None)


@pytest.mark.parametrize("bad", ["2026-13-01", "2026-1-1", "2026-01-01T00:00"])
@pytest.mark.parametrize("where", ["node", "edge"])
def test_dates_must_be_iso_dates(bad, where):
    d = base()
    (d["nodes"][1] if where == "node" else d["edges"][0])["dates"] = {"onset": bad}
    with pytest.raises(MotifError, match=r"dates\['onset'\]") as ei:
        parse_motif(d, None)
    assert bad in str(ei.value)


def test_dates_parse_on_nodes_and_edges():
    d = base(); d["nodes"][1]["dates"] = {"onset": "2026-01-02"}; d["edges"][0]["dates"] = {"recorded": "2026-01-03"}
    m = parse_motif(d, None)
    assert m.node("n1").dates == {"onset": "2026-01-02"} and m.edge("P", "n1").dates == {"recorded": "2026-01-03"}


def test_test_identity_and_reference_range_parse():
    d = base()
    t = {"system": "http://loinc.org", "code": "1742-6", "specimen": "serum"}
    d["nodes"][1].update(test=t, reference_range={
        "interval": [7, 56], "unit": "U/L", "kind": "reference", "test": t,
        "applies_to": {"sex": "M", "age_min_days": 6570}, "source": "lab-report", "source_ref": "doc-9#p2"})
    n = parse_motif(d, None).node("n1")
    assert (n.test.system, n.test.code, n.test.method, n.test.specimen) == ("http://loinc.org", "1742-6", None, "serum")
    rr = n.reference_range
    assert (rr.interval.lo, rr.interval.hi, rr.interval.lo_closed, rr.interval.hi_closed, rr.interval.unit) == \
        (7, 56, True, True, "U/L")
    assert rr.kind == "reference" and rr.test == n.test and (rr.source, rr.source_ref) == ("lab-report", "doc-9#p2")
    assert (rr.applies_to.sex, rr.applies_to.age_min_days, rr.applies_to.age_max_days) == ("M", 6570, None)


@pytest.mark.parametrize("mutate,msg", [
    (lambda n: n.update(test={"system": "s"}), "test"),
    (lambda n: n.update(test={"system": "s", "code": "c", "bogus": 1}), "bogus"),
    (lambda n: n.update(reference_range={"interval": [1, 2], "unit": "U/L", "kind": "reference",
                                         "test": {"system": "s", "code": "c"}, "source": "x"}), "reference_range"),
])
def test_bad_test_or_reference_range_rejected(mutate, msg):
    d = base(); mutate(d["nodes"][1])
    with pytest.raises(MotifError, match=msg): parse_motif(d, None)


def test_absent_node_with_dates_rejected():
    d = base(); d["nodes"][2]["dates"] = {"onset": "2026-01-02"}
    with pytest.raises(MotifError, match="absent"): parse_motif(d, None)


def test_single_motif_file_loads_as_bundles_of_one(tmp_path):
    for payload in ([_named("M1"), _named("M2")], {"_comment": "x", "motifs": [_named("M1"), _named("M2")]}):
        p = tmp_path / "m.json"; p.write_text(json.dumps(payload))
        bs = load_bundles(p, None)
        assert [b.bundle_id for b in bs] == ["M1", "M2"] and all(b.is_single for b in bs)
        assert [b.single_motif for b in bs] == load_motifs(p, None)
        assert bs[0] == MotifBundle.of(load_motifs(p, None)[0])


def test_bundle_file_loads(tmp_path):
    p = tmp_path / "b.json"
    p.write_text(json.dumps({"bundles": [_bundle(_named("M1"), _named("M2")),
                                         {"bundle_id": "B2", "motifs": [_named("M3")]}]}))
    a, b = load_bundles(p, None)
    assert (a.bundle_id, len(a.parts), b.bundle_id, b.is_single) == ("B1", 2, "B2", True)
    p.write_text(json.dumps({"bundles": [_bundle(_named("M1")), _bundle(_named("M1"))]}))
    with pytest.raises(MotifError, match="duplicate bundle"): load_bundles(p, None)


def test_ids_differing_only_by_case_are_duplicates(tmp_path):
    """Ids name output directories: "b1" and "B1" would share one on a case-insensitive filesystem."""
    p = tmp_path / "b.json"
    second = _bundle(_named("M2"), bundle_id="b1", anchor_motif="M2")
    p.write_text(json.dumps({"bundles": [_bundle(_named("M1")), second]}))
    with pytest.raises(MotifError, match=r"duplicate bundle id\(s\) \['B1', 'b1'\]"): load_bundles(p, None)
    p.write_text(json.dumps([_named("M1"), _named("m1")]))   # motif-list file: bundle id = motif id
    with pytest.raises(MotifError, match=r"\['M1', 'm1'\]"): load_bundles(p, None)
