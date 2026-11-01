import copy
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
