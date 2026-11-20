"""semgen: deterministic symbolic generalization of clinical graph motifs over SNOMED CT.

Public interface::

    from semgen import Budget, SemgenEngine

    engine = SemgenEngine.from_config(rf2_dir="/path/to/SnomedCT_InternationalRF2_...")
    result = engine.generalize(motif_dict, Budget(max_depth=2))
    result.write("runs/")

Extend the operator set without touching semgen's code (every move is still guarded and order-proven)::

    engine = engine.with_operators(engine.operators.with_operator(my_operator))
"""
from semgen.bundle import CohortDefinition, MotifBundle, MotifPart, Subject
from semgen.config import ConfigError, GenConfig, load_config
from semgen.engine import GeneralizationResult, SemgenEngine
from semgen.export import semgen_version
from semgen.interfaces import (
    Blocked,
    BundleMove,
    BundleOperatorResult,
    ChangeRecord,
    GenContext,
    Move,
    OperatorResult,
    OperatorSet,
)
from semgen.lattice import Budget, GeneralizationOrderError, Lattice, PolicyViolation
from semgen.model import Edge, Motif, Node
from semgen.motif_io import MotifError
from semgen.operators import default_operators
from semgen.settings import Settings

__version__ = semgen_version()

__all__ = [
    "Blocked", "Budget", "BundleMove", "BundleOperatorResult", "ChangeRecord", "CohortDefinition", "ConfigError",
    "Edge", "GenConfig", "GenContext", "GeneralizationOrderError", "GeneralizationResult", "Lattice", "Motif",
    "MotifBundle", "MotifError", "MotifPart", "Move", "Node", "OperatorResult", "OperatorSet", "PolicyViolation",
    "SemgenEngine", "Settings", "Subject", "__version__", "default_operators", "load_config",
]
