import pytest

from semgen.model import Edge, Interval, Motif, Node


def iv(lo, hi, lc=True, hc=True, u="%"): return Interval(lo=lo, hi=hi, lo_closed=lc, hi_closed=hc, unit=u)

def test_point_inside_half_open():
    assert iv(0, 40, hc=False).contains_point(38)
    assert not iv(0, 40, hc=False).contains_point(40)
def test_equal_endpoint_inclusivity():
    assert not iv(0, 40, hc=False).contains(iv(0, 40))          # [0,40) does not contain [0,40]
    assert iv(0, 40).contains(iv(0, 40, hc=False))              # [0,40] contains [0,40)
def test_unbounded():
    assert iv(65, None).contains(iv(65, 80, hc=False))
    assert not iv(65, 80, hc=False).contains(iv(65, None))
def test_unit_mismatch_never_contains():
    assert not iv(0, 50, u="%").contains(iv(38, 38, u="xULN"))
def test_strictly_contains():
    assert iv(0, 50, hc=False).strictly_contains(iv(0, 40, hc=False))
    assert not iv(0, 40, hc=False).strictly_contains(iv(0, 40, hc=False))
def _motif():
    return Motif(motif_id="X", anchor="n1",
              nodes=(Node(id="P", type="Patient", role="patient"), Node(id="n1", type="Disorder", role="anchor", code="1")),
              edges=(Edge(s="P", t="n1", rel="has_condition", prov="asserted"),))
def test_motif_is_frozen_and_replace_returns_new():
    m = _motif()
    m2 = m.replace_node(m.node("n1").model_copy(update={"code": "2"}))
    assert m.node("n1").code == "1" and m2.node("n1").code == "2"
    with pytest.raises(Exception): m.node("n1").code = "3"
    assert m.edge("P", "n1").key == ("P", "n1") and m.edge("n1", "P") is None

# --- controller rulings R1-R4 ---
def test_attrs_read_only_equal_and_dumps_plain_dict():
    a = iv(1, 2)
    n = Node(id="a", type="T", role="r", attrs={"x": a})
    with pytest.raises(TypeError): n.attrs["y"] = a
    assert n.attrs == {"x": a}
    assert type(n.model_dump()["attrs"]) is dict
    assert type(n.model_dump(mode="json")["attrs"]) is dict
    assert Node(id="a", type="T", role="r").attrs == {}
def test_model_copy_revalidates():
    n = Node(id="a", type="T", role="r")
    with pytest.raises(Exception): n.model_copy(update={"polarity": "bogus"})
    n2 = n.model_copy(update={"attrs": {"x": iv(1, 2)}})
    with pytest.raises(TypeError): n2.attrs["z"] = iv(1, 2)
def test_lists_coerced_to_tuples():
    m = _motif()
    m2 = Motif(motif_id="X", anchor="n1", nodes=list(m.nodes), edges=list(m.edges))
    assert isinstance(m2.nodes, tuple) and isinstance(m2.edges, tuple) and m2 == m
def test_without_drops_dangling_edges_and_ignores_unknown():
    m = _motif()
    m2 = m.without({"n1", "zzz"}, {("q", "q")})
    assert m2.node_ids == {"P"} and m2.edges == ()
    assert len(m.nodes) == 2 and len(m.edges) == 1
    assert m.without(set(), {("P", "n1")}).edges == ()
def test_replace_keeps_position_and_raises_on_missing():
    m = _motif()
    e = m.edges[0].model_copy(update={"prov": "derived"})
    assert m.replace_edge(e).edge("P", "n1").prov == "derived"
    assert m.replace_node(m.node("P").model_copy(update={"label": "x"})).nodes[0].label == "x"
    with pytest.raises(KeyError): m.node("nope")
    with pytest.raises(KeyError): m.replace_node(Node(id="nope", type="T", role="r"))
    with pytest.raises(KeyError): m.replace_edge(Edge(s="n1", t="P", rel="r", prov="asserted"))
def test_unbounded_sides_normalised_open():
    assert iv(65, None) == iv(65, None, hc=False)
    assert iv(None, 5).lo_closed is False
    assert iv(None, None).to_json() == {"lo": None, "hi": None, "lo_closed": False, "hi_closed": False, "unit": "%"}
def test_invalid_intervals_rejected():
    with pytest.raises(Exception): iv(5, 1)
    with pytest.raises(Exception): iv(5, 5, hc=False)
    with pytest.raises(Exception): Interval(lo=1, hi=2)
    assert Interval.point(3, "%").contains_point(3)
    assert Interval.closed(0.5, 1.5, "%").to_json()["lo"] == 0.5
def test_unbounded_containment():
    assert iv(None, 5).contains(iv(None, 3))
    assert not iv(0, 5).contains(iv(None, 3))
    assert iv(None, None).contains(iv(0, 3))

def test_hash_eq_contract_attrs_order():
    a, b = iv(1, 2), iv(3, 4)
    n1 = Node(id="a", type="T", role="r", attrs={"x": a, "y": b})
    n2 = Node(id="a", type="T", role="r", attrs={"y": b, "x": a})
    assert n1 == n2 and hash(n1) == hash(n2)
def test_model_copy_deep_works():
    n = Node(id="a", type="T", role="r", attrs={"x": iv(1, 2)})
    assert n.model_copy(deep=True) == n
    n2 = n.model_copy(update={"code": "9"}, deep=True)
    assert n2.code == "9" and n2.attrs == n.attrs
    with pytest.raises(TypeError): n2.attrs["z"] = iv(1, 2)


# --- Task 1: new fields ---
def _obs(dates):
    from semgen.model import Observation
    return Observation(value=Interval.point(1, "%"), dates=dates, source_node="n1")


def test_mapping_fields_immutable():
    src = {"onset": "2026-01-02"}
    built = [
        (Node(id="a", type="T", role="r", dates=src), "dates"),
        (Node(id="a", type="T", role="r", attrs={"x": iv(1, 2)}), "attrs"),
        (Edge(s="P", t="a", rel="r", prov="asserted", dates=src), "dates"),
        (_obs(src), "dates"),
    ]
    src_attrs = {"x": iv(1, 2)}
    built.append((Node(id="a", type="T", role="r", attrs=src_attrs), "attrs"))
    for obj, name in built:
        mp = getattr(obj, name)
        with pytest.raises(TypeError):
            mp["new"] = mp[next(iter(mp))]
        with pytest.raises(TypeError):
            del mp[next(iter(mp))]
    before = [dict(getattr(o, n)) for o, n in built]
    src["onset"] = "1999-09-09"; src["extra"] = "2000-01-01"; src_attrs["y"] = iv(3, 4)
    assert [dict(getattr(o, n)) for o, n in built] == before


def test_hash_and_canonical_stable_after_source_dict_mutation():
    from semgen.canonical import canonical_json, motif_hash
    nd, ed = {"onset": "2026-01-02", "end": "2026-02-03"}, {"seen": "2026-03-04"}
    def build(ndates, edates):
        return Motif(motif_id="X", anchor="n1",
                     nodes=(Node(id="P", type="Patient", role="patient"),
                            Node(id="n1", type="Disorder", role="anchor", code="1", dates=ndates)),
                     edges=(Edge(s="P", t="n1", rel="has_condition", prov="asserted", dates=edates),))
    m = build(nd, ed)
    h, cj = motif_hash(m), canonical_json(m)
    nd["onset"] = "1999-01-01"; ed.clear()
    assert (motif_hash(m), canonical_json(m)) == (h, cj)
    other = build({"end": "2026-02-03", "onset": "2026-01-02"}, {"seen": "2026-03-04"})
    assert (motif_hash(other), canonical_json(other)) == (h, cj)
    assert hash(m.node("n1")) == hash(other.node("n1")) and hash(m.edges[0]) == hash(other.edges[0])


def test_new_fields_default_and_leave_canonical_unchanged():
    from semgen.canonical import canonical_json
    m = _motif()
    n = m.node("n1")
    assert (n.dates, n.test, n.reference_range, n.observations) == ({}, None, None, ())
    assert m.edges[0].dates == {}
    assert canonical_json(m) == ('{"anchor":"n1","edges":[{"bpn_score":null,"prov":"asserted","rel":"has_condition",'
                                 '"s":"P","t":"n1","window":null}],"nodes":[{"attrs":{},"code":null,"id":"P",'
                                 '"polarity":"present","role":"patient","type":"Patient","value":null},{"attrs":{},'
                                 '"code":"1","id":"n1","polarity":"present","role":"anchor","type":"Disorder",'
                                 '"value":null}]}')


def test_new_fields_enter_canonical_when_set():
    from semgen.canonical import canonical_json
    from semgen.model import AppliesTo, ReferenceRange, TestIdentity
    t = TestIdentity(system="http://loinc.org", code="1742-6")
    rr = ReferenceRange(interval=iv(0, 40, u="U/L"), kind="reference", test=t, applies_to=AppliesTo(sex="F"),
                        source="lab", source_ref="r1")
    m = _motif()
    n = m.node("n1").model_copy(update={"dates": {"onset": "2026-01-02"}, "test": t, "reference_range": rr})
    got = canonical_json(m.replace_node(n))
    assert '"dates":{"onset":"2026-01-02"}' in got and '"test":{"code":"1742-6"' in got
    assert '"reference_range":{"applies_to":{"age_max_days":null,"age_min_days":null,"sex":"F"}' in got
    obs = n.model_copy(update={"test": None, "reference_range": None, "dates": {},
                               "observations": (_obs({"d": "2026-01-01"}),)})
    assert '"observations":[{"dates":{"d":"2026-01-01"},"source_node":"n1","source_record":null,"value":' \
        in canonical_json(m.replace_node(obs))


def test_bad_iso_date_rejected_by_model():
    for bad in ("2026-13-01", "2026-1-1", "2026-01-01T00:00"):
        with pytest.raises(Exception, match="dates"):
            Node(id="a", type="T", role="r", dates={"onset": bad})
    assert Node(id="a", type="T", role="r", dates={"onset": "2024-02-29"}).dates["onset"] == "2024-02-29"


def test_test_identity_is_not_collected_and_frozen():
    from semgen.model import TestIdentity
    t = TestIdentity(system="s", code="c")
    assert TestIdentity.__test__ is False and (t.method, t.specimen) == (None, None)
    with pytest.raises(Exception):
        t.code = "d"
