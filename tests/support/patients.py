"""Synthetic patients for the containment tests, built by small edits of the root motif.

Patients are Motifs with point values and no absent nodes.
"""
from __future__ import annotations

from semgen.model import Edge, Interval, Motif, Node
from tests.conftest import DAUNO, RA, T1DM


def as_patient(root: Motif) -> Motif:
    absent = {n.id for n in root.nodes if n.polarity == "absent"}
    return root.without(absent, set())


def _upd(m: Motif, nid: str, **kw) -> Motif:
    return m.replace_node(m.node(nid).model_copy(update=kw))


def m1_patients(root: Motif) -> dict[str, Motif]:
    exact = as_patient(root)
    no_drug = exact.without({"n2"}, set())    # n4, n5 are kept as orphans
    win = exact.edge("n2", "n3").model_copy(update={"window": Interval.point(60, "d")})
    return {
        "exact": exact,
        "daunorubicin": _upd(exact, "n2", code=DAUNO),
        "lvef_45": _upd(exact, "n3", value=Interval.point(45, "%")),
        "outcome_day_60": exact.replace_edge(win),
        "no_context_edges": exact.without({"n4", "n5"}, set()),
        "extra_condition": exact.model_copy(update={
            "nodes": exact.nodes + (Node(id="n9", type="Disorder", role="modifier", code=RA),),
            "edges": exact.edges + (Edge(s="P", t="n9", rel="has_condition", prov="asserted"),)}),
        "no_drug": no_drug,
        "age_72": _upd(exact, "n1", attrs={"age_at_dx": Interval.point(72, "a")}),
    }


def m2_patients(root: Motif) -> dict[str, Motif]:
    exact = as_patient(root)
    win = exact.edge("n3", "n5").model_copy(update={"window": Interval.point(400, "d")})
    return {
        "exact": exact,
        "has_t1dm": exact.model_copy(update={
            "nodes": exact.nodes + (Node(id="n9", type="Disorder", role="modifier", code=T1DM),),
            "edges": exact.edges + (Edge(s="P", t="n9", rel="has_condition", prov="asserted"),)}),
        "egfr_70": _upd(exact, "n5", value=Interval.point(70, "mL/min/1.73m2")),
        "day_400": exact.replace_edge(win),
    }
