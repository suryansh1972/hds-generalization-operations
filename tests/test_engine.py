"""The public library interface: ``SemgenEngine``, ``GeneralizationResult`` and the injectable ``OperatorSet``.

Synthetic data only (the fake hierarchy and the tiny fixture RF2 release); no licensed data is needed.
"""
import copy
import dataclasses
import json
from pathlib import Path

import pytest

import semgen
from semgen import Budget, OperatorResult, PolicyViolation, SemgenEngine, Settings
from semgen.config import ConfigError, load_config
from semgen.export import run_header, write_lattice
from semgen.interfaces import ChangeRecord, GenContext, Move
from semgen.lattice import enumerate_lattice
from semgen.motif_io import MotifError, parse_motif
from semgen.operators import ALL_OPERATORS, BUNDLE_OPERATORS, concept_lift, default_operators
from tests.support.fake_snomed import BRCA, FAKE_M1, FAKE_M2, fake_boundary_policy, fake_hierarchy

FIXTURE_RF2 = Path(__file__).resolve().parent / "fixtures" / "rf2"


@pytest.fixture
def engine():
    h = fake_hierarchy()
    return SemgenEngine(GenContext(h, load_config(), fake_boundary_policy(h)))


def test_public_names_are_importable():
    for name in semgen.__all__:
        assert hasattr(semgen, name), name
    assert isinstance(semgen.__version__, str)


def test_generalize_equals_the_lattice_engine(engine, tmp_path):
    """The engine is a thin layer: same lattice, same bytes on disk as the lower-level calls."""
    m1 = parse_motif(copy.deepcopy(FAKE_M1), None)
    res = engine.generalize(copy.deepcopy(FAKE_M1), Budget(max_depth=2))
    lat = enumerate_lattice(m1, engine.context, Budget(max_depth=2))
    assert res.bundle_id == "M1" and list(res.lattice.candidates) == list(lat.candidates)
    assert res.lattice.edges == lat.edges and res.lattice.blocked == lat.blocked
    a = res.write(tmp_path / "a")
    b = write_lattice(lat, "M1", tmp_path / "b", run_header(engine.context, None, Budget(max_depth=2)))
    for k in a:
        assert a[k].read_bytes() == b[k].read_bytes(), k
    data = res.to_json()
    assert {"run_header", "candidates", "edges", "blocked", "termination"} <= set(data)
    assert json.loads(json.dumps(data)) == data                      # JSON-safe
    assert res.summary()["candidates"] == len(data["candidates"]) == len(lat.candidates)


def test_generalize_accepts_motif_bundle_and_dict(engine):
    m = parse_motif(copy.deepcopy(FAKE_M2), None)
    hashes = {tuple(engine.generalize(x, Budget(max_depth=1)).lattice.candidates)
              for x in (m, semgen.MotifBundle.of(m), copy.deepcopy(FAKE_M2))}
    assert len(hashes) == 1
    with pytest.raises(MotifError):
        engine.generalize(42)


def test_parse_shapes(engine):
    one = engine.parse(copy.deepcopy(FAKE_M1))
    many = engine.parse({"motifs": [copy.deepcopy(FAKE_M1), copy.deepcopy(FAKE_M2)]})
    bundle = engine.parse({"bundle_id": "B", "semantics": "all", "anchor_motif": "M1",
                           "motifs": [copy.deepcopy(FAKE_M1)]})
    assert [b.bundle_id for b in one] == ["M1"] and [b.bundle_id for b in many] == ["M1", "M2"]
    assert bundle[0].bundle_id == "B"
    with pytest.raises(MotifError):
        engine.parse({"nope": 1})


def test_verify_is_the_independent_order_proof(engine):
    m = copy.deepcopy(FAKE_M1)
    res = engine.generalize(m, Budget(max_depth=1), climb=False)
    for c in res.lattice.candidates.values():
        assert engine.verify(m, c.motif)["ok"]
    narrower = next(c.motif for c in res.lattice.candidates.values() if c.depth == 1)
    back = engine.verify(narrower, m)                               # the root is not more general than its child
    assert back["ok"] is False and back["reason"]


def test_lift_inspection(engine):
    step = engine.check_lift(BRCA, sorted(engine.context.hierarchy.parents(BRCA))[0])
    assert {"accepted", "transition", "verification", "fingerprint"} <= set(step)
    assert step["verification"]["status"] in {"verified", "failed"}
    ex = engine.inspect_lift(BRCA)
    assert ex["origin"] == BRCA and all(c["verification"]["status"] == "verified" for c in ex["candidates"])
    assert engine.concept(BRCA)["active"] and engine.concept("nope")["active"] is False


def test_provenance_has_operators_and_no_paths(engine):
    p = engine.provenance()
    assert p["operators"]["motif"] == ["concept_lift", "normative_bucketing", "attribute_deletion",
                                       "attribute_aggregation"]
    assert p["operators"]["bundle"] == ["motif_deletion"]
    text = json.dumps(p)
    assert str(Path.home()) not in text and str(Path(__file__).resolve().parents[1]) not in text
    assert "budget" not in p and p["sources_available"] == {"mayo": False, "ucum": False}


# --- operator set ------------------------------------------------------------------------------------------------
def test_builtin_registry_is_immutable():
    assert isinstance(ALL_OPERATORS, tuple) and isinstance(BUNDLE_OPERATORS, tuple)
    ops = default_operators()
    assert ops is default_operators() and ops.motif == ALL_OPERATORS and ops.bundle == BUNDLE_OPERATORS
    with pytest.raises(dataclasses.FrozenInstanceError):
        ops.motif = ()   # type: ignore[misc]


def test_operator_set_building():
    ops = default_operators()
    def extra(m, c): return OperatorResult()
    added = ops.with_operator(extra, before="attribute_deletion")
    assert added.names[:4] == ("concept_lift", "normative_bucketing", "extra", "attribute_deletion")
    assert ops.names == default_operators().names                    # the original is untouched
    assert ops.only("concept_lift").names == ("concept_lift",)
    assert ops.without("motif_deletion").bundle == ()
    with pytest.raises(ValueError, match="already"):
        added.with_operator(extra)
    with pytest.raises(ValueError, match="unknown"):
        ops.without("nope")
    with pytest.raises(ValueError, match="before"):
        ops.with_operator(extra, before="nope")


def test_custom_operator_runs_and_is_guarded(engine):
    """A user-supplied operator is called by the lattice, and its moves still go through the guard and proofs."""
    calls = []

    def anchor_dropper(m, ctx):
        calls.append(m.motif_id)
        child = m.without({m.anchor}, {e.key for e in m.edges if m.anchor in e.key})
        return OperatorResult([Move(child, ChangeRecord("anchor_dropper", m.anchor, "node", None, None, {}))])
    anchor_dropper.op_name = "anchor_dropper"

    bad = engine.with_operators(engine.operators.with_operator(anchor_dropper))
    with pytest.raises(PolicyViolation, match="protected_node_removed"):
        bad.generalize(copy.deepcopy(FAKE_M1), Budget(max_depth=1))
    assert calls == ["M1"]
    assert engine.operators == default_operators()                    # with_operators returned a new engine


def test_lift_only_operator_set_disables_other_moves(engine):
    lift_only = engine.with_operators(engine.operators.only("concept_lift"))
    changes = {c.op for e in lift_only.generalize(copy.deepcopy(FAKE_M1), Budget(max_depth=2)).lattice.edges
               for c in e.changes}
    assert changes == {"concept_lift"}
    no_lift = engine.with_operators(engine.operators.without("concept_lift"))
    lat = no_lift.generalize(copy.deepcopy(FAKE_M1), Budget(max_depth=2)).lattice
    assert lat.axes == {} and all(c.op != "concept_lift" for e in lat.edges for c in e.changes)
    assert concept_lift not in no_lift.operators.motif


# --- construction from files -------------------------------------------------------------------------------------
def test_from_config_with_fixture_release(tmp_path):
    s = Settings(rf2_dir=FIXTURE_RF2, cache_dir=tmp_path / "cache")
    e = SemgenEngine.from_config(settings=s)
    assert e.release == {"edition": "International", "release": "20990101"}
    assert (tmp_path / "cache").is_dir()                              # the cache went where it was told
    assert e.header()["config_sha256"] == semgen.config.config_sha256()


def test_from_config_without_release_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="SEMGEN_RF2_DIR"):
        SemgenEngine.from_config(settings=Settings(cache_dir=tmp_path))


def test_settings_from_env(tmp_path):
    env = {"SEMGEN_RF2_DIR": str(tmp_path / "rf2"), "SEMGEN_MAYO_DB": str(tmp_path / "m.sqlite"),
           "XDG_CACHE_HOME": str(tmp_path / "xdg")}
    s = Settings.from_env(env)
    assert s.rf2_dir == tmp_path / "rf2" and s.mayo_db == tmp_path / "m.sqlite"
    assert s.cache_dir == tmp_path / "xdg" / "semgen" and s.ucum_essence is None
    assert Settings.from_env(env, rf2_dir=tmp_path / "x").rf2_dir == tmp_path / "x"
    assert Settings.from_env({"SEMGEN_CACHE_DIR": str(tmp_path / "c")}).cache_dir == tmp_path / "c"
    d = s.describe()
    assert d["rf2_dir"] == {"configured": True, "exists": False} and d["config_path"]["exists"]
    assert str(tmp_path) not in json.dumps(d)                        # no paths leak into diagnostics


def test_rf2_dir_accepts_release_root(tmp_path):
    from semgen.snomed import terminology_dir
    term = tmp_path / "Release" / "Snapshot" / "Terminology"
    term.mkdir(parents=True)
    assert terminology_dir(tmp_path / "Release") == term
    assert terminology_dir(tmp_path / "Release" / "Snapshot") == term
    assert terminology_dir(term) == term


def test_readme_custom_operator_example(engine):
    """The custom-operator example in README.md works as documented and its moves pass the guard and proofs."""
    import re
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    block = re.search(r"```python\n(from semgen import ChangeRecord, Move, OperatorResult\n.*?)```", readme, re.S)
    assert block, "README example not found"
    ns = {"engine": engine}
    exec(block.group(1), ns)                                          # noqa: S102 - our own documentation
    res = ns["custom"].generalize(copy.deepcopy(FAKE_M1), Budget(max_depth=1), climb=False)
    widened = [c for e in res.lattice.edges for c in e.changes if c.op == "widen_point_values"]
    assert widened and all(engine.verify(FAKE_M1, res.lattice.candidates[e.child].motif)["ok"]
                           for e in res.lattice.edges if any(c.op == "widen_point_values" for c in e.changes))
