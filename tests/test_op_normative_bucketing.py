"""Normative range bucketing (design §7.1). Ranges, maps and the M4 ALT value are SYNTHETIC."""
import dataclasses
import tempfile
from pathlib import Path

import pytest

from semgen.bundle import Subject
from semgen.model import Edge, Interval, Motif, Node, ReferenceRange, TestIdentity
from semgen.operators import ALL_OPERATORS
from semgen.operators.normative_bucketing import normative_bucketing
from semgen.order import check_order
from semgen.refrange import MayoSource, buckets
from tests.support import mayo_fixture

TEST = TestIdentity(system="urn:synthetic:lab", code="SALT", method="kinetic", specimen="Serum")
MAP_ROW = {"system": TEST.system, "code": TEST.code, "mnemonic": "SALT", "analyte": "Synthetic ALT",
           "specimen": "Serum", "page_ref": "p. 1", "reviewed_by": "synthetic"}
ROW = {"mnemonic": "SALT", "analyte": "Synthetic ALT", "low": 7.0, "low_op": ">=", "high": 56.0, "high_op": "<=",
       "unit": "U/L", "pdf_page": 3, "raw": "7-56 U/L"}
SUBJECT = Subject(sex="male", age_days=20000)


def m4(value=145.0, unit="U/L", test=TEST, rr=None) -> Motif:
    """Synthetic M4 shape (RA, methotrexate, ALT); codes are placeholders, bucketing never reads them."""
    nodes = (Node(id="P", type="Patient", role="patient"),
             Node(id="n1", type="Disorder", role="anchor", code="RA"),
             Node(id="n2", type="Substance", role="exposure", code="MTX"),
             Node(id="n3", type="Observable", role="outcome", code="ALT", value=Interval.point(value, unit),
                  test=test, reference_range=rr))
    edges = (Edge(s="P", t="n1", rel="has_condition", prov="asserted"),
             Edge(s="P", t="n2", rel="administered_drug", prov="asserted"),
             Edge(s="P", t="n3", rel="has_measurement", prov="asserted"),
             Edge(s="n2", t="n3", rel="followed_by", prov="asserted", window=Interval.point(90, "d")))
    return Motif(motif_id="M4", anchor="n1", nodes=nodes, edges=edges)


def attached(interval=Interval.closed(7, 56, "U/L")) -> ReferenceRange:
    return ReferenceRange(interval=interval, kind="reference", test=TEST, source="synthetic-lab-report",
                          source_ref="obs/145#range")


def with_mayo(ctx, tmp_path, rows, subject=SUBJECT):
    d = Path(tempfile.mkdtemp(dir=tmp_path))
    db = mayo_fixture.build(d, rows)
    src = MayoSource.open(db, mayo_fixture.sha256(db), mayo_fixture.write_map(d, [MAP_ROW]))
    return dataclasses.replace(ctx, refranges=src, subject=subject)


def bucket_of(ctx, motif):
    (mv,) = normative_bucketing(motif, ctx).moves
    return mv.change.evidence["bucket"], mv.child.node("n3").value


def test_registered_after_concept_lift():
    names = [op.__name__ for op in ALL_OPERATORS]
    assert names == ["concept_lift", "normative_bucketing", "attribute_deletion", "attribute_aggregation"]


def test_buckets_complementary_closure():
    r = Interval.closed(7, 56, "U/L")
    assert buckets(r) == [("below_reference_interval", Interval(lo=None, hi=7, hi_closed=False, unit="U/L")),
                          ("within_reference_interval", r),
                          ("above_reference_interval", Interval(lo=56, lo_closed=False, hi=None, unit="U/L"))]
    open_r = Interval(lo=7, hi=56, lo_closed=False, hi_closed=False, unit="U/L")
    assert buckets(open_r)[0][1].hi_closed and buckets(open_r)[2][1].lo_closed


def test_bucket_boundaries(ctx, tmp_path):
    """Review Focus 2: a value exactly on a bound lands in exactly one bucket, on the side the operator says."""
    closed = with_mayo(ctx, tmp_path, [ROW])                                   # >= 7, <= 56
    assert bucket_of(closed, m4(56))[0] == "within_reference_interval"
    assert bucket_of(closed, m4(56.01))[0] == "above_reference_interval"
    assert bucket_of(closed, m4(7))[0] == "within_reference_interval"
    assert bucket_of(closed, m4(6.99))[0] == "below_reference_interval"
    hi_open = with_mayo(ctx, tmp_path, [{**ROW, "high_op": "<"}])              # < 56
    assert bucket_of(hi_open, m4(56)) == ("above_reference_interval", Interval(lo=56, hi=None, unit="U/L"))
    assert bucket_of(hi_open, m4(55.99))[0] == "within_reference_interval"
    lo_open = with_mayo(ctx, tmp_path, [{**ROW, "low_op": ">"}])               # > 7
    assert bucket_of(lo_open, m4(7)) == ("below_reference_interval", Interval(lo=None, hi=7, unit="U/L"))
    for r in (Interval.closed(7, 56, "U/L"), Interval(lo=7, hi=56, lo_closed=False, hi_closed=False, unit="U/L")):
        for x in (7, 56, 6.99, 56.01, 30):
            assert sum(b.contains_point(x) for _, b in buckets(r)) == 1, (r, x)


def test_m4_alt_145_u_per_l_buckets_high(ctx):
    motif = m4(145, rr=attached())
    res = normative_bucketing(motif, dataclasses.replace(ctx, subject=SUBJECT))
    (mv,) = res.moves
    ch = mv.change
    assert (ch.op, ch.target, ch.field, ch.meaning, ch.rule_id) == (
        "normative_bucketing", "n3", "value", "generalized", "bucket.reference_interval")
    assert ch.evidence["bucket"] == "above_reference_interval" and ch.source["kind"] == "result"
    assert mv.child.node("n3").value == Interval(lo=56, lo_closed=False, hi=None, unit="U/L")
    assert ch.before == Interval.point(145, "U/L").to_json() and ch.after == mv.child.node("n3").value.to_json()
    assert check_order(motif, mv.child, ctx).ok and not check_order(mv.child, motif, ctx).ok


def test_one_sided_range_two_buckets(ctx, tmp_path):
    upper = with_mayo(ctx, tmp_path, [{**ROW, "low": None, "low_op": None, "high": 40.0, "high_op": "<"}])
    assert [n for n, _ in buckets(Interval(lo=None, hi=40, hi_closed=False, unit="U/L"))] == ["within_reference_interval", "above_reference_interval"]
    assert [n for n, _ in buckets(Interval(lo=7, hi=None, unit="U/L"))] == ["below_reference_interval", "within_reference_interval"]
    assert bucket_of(upper, m4(12)) == ("within_reference_interval", Interval(lo=None, hi=40, hi_closed=False, unit="U/L"))
    assert bucket_of(upper, m4(40)) == ("above_reference_interval", Interval(lo=40, hi=None, unit="U/L"))


def test_change_record_source_fields(ctx, tmp_path):
    c = with_mayo(ctx, tmp_path, [ROW])
    (mv,) = normative_bucketing(m4(145), c).moves
    ch = mv.change
    assert ch.source == {"kind": "mayo", "sha256": c.refranges.sha256, "range_id": "SALT-1", "pdf_page": 3,
                         "raw": "7-56 U/L", "mapping_row": MAP_ROW, "test_map_sha256": c.refranges.test_map_sha256}
    assert ch.evidence == {"bucket": "above_reference_interval", "interval_kind": "reference_interval", "reference_interval": Interval.closed(7, 56, "U/L").to_json(),
                           "selection": ["test_map: urn:synthetic:lab|SALT -> SALT / Synthetic ALT",
                                         "category = reference", "confidence = high", "condition empty",
                                         "numeric bounds", "unit equal"],
                           "unit_conversion": None}
    assert ch.to_json()["rule_id"] == "bucket.reference_interval" and "meaning" not in ch.to_json()


def test_only_present_point_values(ctx):
    c = dataclasses.replace(ctx, subject=SUBJECT)
    base = m4(rr=attached())
    for update in ({"value": Interval.closed(50, 60, "U/L")}, {"polarity": "absent"}):
        res = normative_bucketing(base.replace_node(base.node("n3").model_copy(update=update)), c)
        assert res.moves == [] and res.blocked == [], update


def test_blocked_rows_name_the_node(ctx):
    res = normative_bucketing(m4(test=None), ctx)
    assert [(b.op, b.target, b.reason) for b in res.blocked] == [("normative_bucketing", "n3", "no_test_identity")]
    res = normative_bucketing(m4(), ctx)                  # test identity, no Mayo source in the context
    assert [b.reason for b in res.blocked] == ["mayo_unavailable"]


@pytest.mark.snomed
def test_real_motifs_unbucketable(real_motifs, real_ctx):
    valued = 0
    for m in real_motifs:
        res = normative_bucketing(m, real_ctx)
        assert res.moves == []
        nodes = {n.id for n in m.nodes if n.value is not None and n.polarity == "present"}
        valued += len(nodes)
        assert {b.target for b in res.blocked} == nodes
        assert {b.reason for b in res.blocked} <= {"no_test_identity", "mayo_unavailable"}
    assert valued == 3      # M1 LVEF, M2 eGFR, M4 ALT
