"""Small IS-A graph with converging paths, a blocked branch, an inactive parent and a child, for traversal tests."""
from semgen.floors import FloorDecision
from semgen.model import Motif
from semgen.motif_io import parse_motif
from semgen.snomed import ROOT_ID, Hierarchy

_ISA = {
    "SPEC": {"P1", "P2", "INACTIVE"}, "P1": {"G"}, "P2": {"G", "BLOCKED"}, "BLOCKED": {"ABOVE_BLOCKED"},
    "G": {"C1"}, "C1": {"C2"}, "C2": {"C3"}, "C3": {"C4"}, "C4": {"C5"}, "C5": {ROOT_ID},
    "ABOVE_BLOCKED": {ROOT_ID}, "KID": {"SPEC"}, ROOT_ID: set(),
}


def graph_hierarchy() -> Hierarchy:
    ids = set(_ISA) | {p for ps in _ISA.values() for p in ps}
    return Hierarchy.from_maps(_ISA, {c: f"{c} (disorder)" for c in ids - {"INACTIVE"}}, ids - {"INACTIVE"})


class AllowExcept:
    def __init__(self, blocked: set[str]) -> None:
        self.blocked = set(blocked)

    def check_lift(self, child: str, parent: str) -> FloorDecision:
        if parent in self.blocked:
            return FloorDecision(False, "outside_floor", {"parent": parent})
        return FloorDecision(True, None, {})

    def anchors(self, c: str) -> frozenset[str]:
        return frozenset()

    @property
    def provenance(self) -> dict:
        return {"mode": "test"}


def one_disorder_motif(code: str) -> Motif:
    return parse_motif({
        "motif_id": "ONE", "anchor": "n1",
        "nodes": [{"id": "P", "type": "Patient", "role": "patient"},
                  {"id": "n1", "type": "Disorder", "code": code, "polarity": "present", "role": "anchor"}],
        "edges": [{"s": "P", "t": "n1", "rel": "has_condition", "prov": "asserted"}]}, None)
