"""Small IS-A graph with converging paths, a blocked branch, an inactive parent and a child, for traversal tests.

Synthetic concept model: every concept below TOP has one grouped finding-site relationship, TOP names the only
MRCM domain, so the real evaluator accepts every step below TOP and rejects reaching it (top-level concept).
``AllowExcept`` additionally rejects chosen parents (a test hook on the generator; the verifier still runs)."""
from semgen.concept_model import ConceptModel, Mrcm, MrcmDomain
from semgen.lift import FloorDecision, SnomedLift
from semgen.model import Motif
from semgen.motif_io import parse_motif
from semgen.snomed import ROOT_ID, Hierarchy

_ISA = {
    "SPEC": {"P1", "P2", "INACTIVE"}, "P1": {"G"}, "P2": {"G", "BLOCKED"}, "BLOCKED": {"ABOVE_BLOCKED"},
    "G": {"C1"}, "C1": {"C2"}, "C2": {"C3"}, "C3": {"C4"}, "C4": {"C5"}, "C5": {"TOP"},
    "ABOVE_BLOCKED": {"TOP"}, "TOP": {ROOT_ID}, "SITE": {ROOT_ID}, "KID": {"SPEC"}, ROOT_ID: set(),
}


def graph_hierarchy() -> Hierarchy:
    ids = set(_ISA) | {p for ps in _ISA.values() for p in ps}
    return Hierarchy.from_maps(_ISA, {c: f"{c} (disorder)" for c in ids - {"INACTIVE"}}, ids - {"INACTIVE"})


def graph_concept_model(h: Hierarchy | None = None) -> ConceptModel:
    h = h or graph_hierarchy()
    below = frozenset(c for c in h.descendants("TOP") if h.is_active(c) and c != "SITE")
    mrcm = Mrcm((MrcmDomain("TOP", "<< TOP", "<<", "TOP", None),), frozenset({("FS", "TOP")}), {"source": "test"},
                {"FS": (("<<", "SITE"),)})
    concepts = frozenset(h._active)
    return ConceptModel(mrcm, {c: (("FS", "SITE", "1"),) for c in below}, {"source": "test"}, primitive=concepts,
                        owl_axiom=concepts, owl_available=True)


class AllowExcept:
    """The real evaluator over the graph, with ``blocked`` parents additionally rejected."""

    def __init__(self, blocked: set[str], h: Hierarchy | None = None) -> None:
        self.blocked = set(blocked)
        h = h or graph_hierarchy()
        self.lift = SnomedLift(h, graph_concept_model(h))
        self.concept_model, self.fingerprint = self.lift.concept_model, self.lift.fingerprint

    def check_lift(self, child: str, parent: str, **_context) -> FloorDecision:
        if parent in self.blocked:
            return FloorDecision(False, "defining_attribute_dropped", {"parent": parent})
        return self.lift.check_lift(child, parent)

    @property
    def provenance(self) -> dict:
        return {"mode": "test"}


def one_disorder_motif(code: str) -> Motif:
    return parse_motif({
        "motif_id": "ONE", "anchor": "n1",
        "nodes": [{"id": "P", "type": "Patient", "role": "patient"},
                  {"id": "n1", "type": "Disorder", "code": code, "polarity": "present", "role": "anchor"}],
        "edges": [{"s": "P", "t": "n1", "rel": "has_condition", "prov": "asserted"}]}, None)
