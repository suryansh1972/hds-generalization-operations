import json
import math

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from semgen.canonical import canonical_json, motif_hash
from semgen.model import Interval


def test_hash_is_short_hex(fake_m1):
    h = motif_hash(fake_m1)
    assert len(h) == 16 and int(h, 16) >= 0


def test_label_does_not_change_hash(fake_m1):
    n = fake_m1.node("n1")
    assert motif_hash(fake_m1.replace_node(n.model_copy(update={"label": "x"}))) == motif_hash(fake_m1)


def test_code_change_changes_hash(fake_m1):
    n = fake_m1.node("n1")
    assert motif_hash(fake_m1.replace_node(n.model_copy(update={"code": "1"}))) != motif_hash(fake_m1)


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(st.permutations(range(6)), st.permutations(range(6)))
def test_order_independent(fake_m1, pn, pe):
    m = fake_m1.model_copy(update={"nodes": tuple(fake_m1.nodes[i] for i in pn),
                                   "edges": tuple(fake_m1.edges[i] for i in pe)})
    assert canonical_json(m) == canonical_json(fake_m1)


def test_int_and_float_hash_same(fake_m1):
    n = fake_m1.node("n1")
    a = n.model_copy(update={"value": Interval(lo=38, hi=40, unit="C")})
    b = n.model_copy(update={"value": Interval(lo=38.0, hi=40.0, unit="C")})
    assert motif_hash(fake_m1.replace_node(a)) == motif_hash(fake_m1.replace_node(b))
    assert '"lo":38.0' in canonical_json(fake_m1.replace_node(a))


def test_negative_zero_normalised(fake_m1):
    n = fake_m1.node("n1")
    a = n.model_copy(update={"value": Interval(lo=-0.0, hi=1.0, unit="C")})
    b = n.model_copy(update={"value": Interval(lo=0.0, hi=1.0, unit="C")})
    assert motif_hash(fake_m1.replace_node(a)) == motif_hash(fake_m1.replace_node(b))
    assert "-0.0" not in canonical_json(fake_m1.replace_node(a))


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_raises(fake_m1, bad):
    e = fake_m1.edges[0]
    m = fake_m1.replace_edge(e.model_copy(update={"bpn_score": bad}))
    with pytest.raises(ValueError):
        canonical_json(m)


def test_attrs_insertion_order_irrelevant(fake_m1):
    n = fake_m1.node("n1")
    i1, i2 = Interval(lo=1, hi=2, unit="u"), Interval(lo=3, hi=4, unit="u")
    a = n.model_copy(update={"attrs": {"a": i1, "b": i2}})
    b = n.model_copy(update={"attrs": {"b": i2, "a": i1}})
    assert canonical_json(fake_m1.replace_node(a)) == canonical_json(fake_m1.replace_node(b))


def test_motif_id_excluded(fake_m1):
    assert motif_hash(fake_m1.model_copy(update={"motif_id": "other"})) == motif_hash(fake_m1)


def test_canonical_json_schema(fake_m1):
    obj = json.loads(canonical_json(fake_m1))
    assert set(obj) == {"anchor", "nodes", "edges"}
    for n in obj["nodes"]:
        assert set(n) == {"id", "type", "role", "code", "polarity", "value", "attrs"}
    for e in obj["edges"]:
        assert set(e) == {"s", "t", "rel", "prov", "window", "bpn_score"}


def test_field_changes_change_hash(fake_m1):
    base = motif_hash(fake_m1)
    n = fake_m1.node("n1")
    e = fake_m1.edges[0]
    variants = [
        fake_m1.replace_node(n.model_copy(update={"value": Interval(lo=1, hi=2, unit="u")})),
        fake_m1.replace_node(n.model_copy(update={"polarity": "absent"})),
        fake_m1.replace_edge(e.model_copy(update={"window": Interval(lo=0, hi=5, unit="d")})),
        fake_m1.replace_edge(e.model_copy(update={"rel": e.rel + "_x"})),
        fake_m1.replace_edge(e.model_copy(update={"prov": "context" if e.prov != "context" else "derived"})),
    ]
    hashes = {motif_hash(v) for v in variants}
    assert base not in hashes and len(hashes) == len(variants)
