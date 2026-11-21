import hashlib
from pathlib import Path

import pytest
import yaml

from semgen.config import ConfigError, config_sha256, load_config
from semgen.settings import default_config_path  # noqa: E402

CFG = str(default_config_path())


def _raw() -> dict:
    """The packaged config as a dict, with the attribute-definitions path absolute (for configs written to tmp)."""
    d = yaml.safe_load(open(CFG))
    d["attribute_definitions"]["path"] = str(Path(CFG).parent / d["attribute_definitions"]["path"])
    return d


def test_loads_and_is_draft():
    """Rewritten (Task 1): was also max_depth == 4; depth is no longer a config value (explicit Budget instead)."""
    c = load_config(CFG)
    assert c.status.startswith("DRAFT")


# Task 2 deleted the ladder tests with the ladders (range_coarsening is gone, D3): test_lvef_ladder_walk,
# test_alt_ladder_walk_and_boundary, test_value_outside_every_rung_has_no_move, test_unit_mismatch_has_no_move,
# and the "laminar"/"unit" cases of test_invalid_configs_fail_at_load. Bucketing bounds come from pinned sources.


def test_mayo_block_loaded():
    """The packaged config pins the Mayo DB by sha256 only; its location is external (SEMGEN_MAYO_DB)."""
    m = load_config(CFG).mayo
    assert m.sha256 == "3edbad893eaca3825a3f161cf7c0b60df4026ff17f32ebf14d3c3a7fa4b4a107"
    assert m.path is None and m.test_map is None


def test_relative_paths_resolve_against_the_config_file(tmp_path):
    d = yaml.safe_load(open(CFG))
    (tmp_path / "defs.yaml").write_bytes((Path(CFG).parent / "attribute_definitions.yaml").read_bytes())
    d["attribute_definitions"]["path"] = "defs.yaml"
    d["mayo"].update(path="db/refrange.sqlite", test_map="map.csv")
    d["ucum"]["path"] = "ucum.xml"
    (tmp_path / "sub").mkdir()
    p = tmp_path / "sub" / ".." / "c.yaml"
    p.write_text(yaml.safe_dump(d))
    c = load_config(p)
    assert c.mayo.path == str(tmp_path / "db" / "refrange.sqlite") and c.mayo.test_map == str(tmp_path / "map.csv")
    assert c.ucum.path == str(tmp_path / "ucum.xml")


def test_default_config_is_packaged():
    assert load_config() == load_config(CFG)


def test_unflagged_attr_is_concept_dependent():
    c = load_config(CFG)
    assert c.attr_is_concept_dependent("cumulative_dose") and not c.attr_is_concept_dependent("age_at_dx")
    assert c.attr_is_concept_dependent("never_seen_attr")


def test_no_floor_list_anywhere():
    assert "floors" not in yaml.safe_load(open(CFG))
    assert not hasattr(load_config(CFG), "floors")


def test_no_sctid_in_config():
    import re
    for line in open(CFG).read().splitlines():
        if "applies_to_concepts" in line or "sha256" in line:
            continue
        assert not re.search(r"\b\d{6,18}\b", line), line


def test_config_sha256():
    h = config_sha256(CFG)
    assert len(h) == 64 and h == config_sha256(CFG)
    assert h == hashlib.sha256(open(CFG, "rb").read()).hexdigest()


@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d.pop("attribute_definitions"), "attribute_definitions"),
    (lambda d: d.pop("mayo"), "mayo"),
    (lambda d: d["mayo"].update(sha256="ABC"), "mayo sha256"),
    (lambda d: d["mayo"].pop("sha256"), "mayo"),
    (lambda d: d["mayo"].update(extra=1), "mayo"),
    (lambda d: d["attribute_definitions"].update(path="config/nope.yaml"), "cannot read"),
    (lambda d: d["attribute_definitions"].update(sha256="ABC"), "64 lowercase hex"),
    (lambda d: d["negation_policy"].update({"allow_drop_absent": True}), "not supported"),
    (lambda d: d.update(protected_roles=["patient"]), "protected_roles"),
    (lambda d: d.update(status="FINAL"), "DRAFT"),
])
def test_invalid_configs_fail_at_load(tmp_path, mutate, msg):
    d = _raw(); mutate(d); p = tmp_path / "c.yaml"; p.write_text(yaml.safe_dump(d))
    with pytest.raises(ConfigError, match=msg): load_config(p)


# --- floor_policy ---------------------------------------------------------------
def _load_mut(tmp_path, mutate):
    d = _raw(); mutate(d); p = tmp_path / "c.yaml"; p.write_text(yaml.safe_dump(d))
    return load_config(p)


def test_floor_policy_is_not_configurable(tmp_path):
    """SNOMED-only concept lift has no clinical configuration: a floor_policy block is a ConfigError."""
    import yaml
    raw = _raw()
    raw["floor_policy"] = {"mode": "snomed_boundary"}
    f = tmp_path / "c.yaml"
    f.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError, match="floor_policy"):
        load_config(f)


def test_attribute_definitions_loaded_and_pinned():
    c = load_config(CFG)
    assert {k: v.about for k, v in c.attribute_definitions.items()} == {"age_at_dx": "patient",
                                                                         "cumulative_dose": "node_concept"}
    defs = Path(CFG).parent / "attribute_definitions.yaml"
    assert c.attribute_definitions_sha256 == hashlib.sha256(defs.read_bytes()).hexdigest()


def test_attribute_definitions_sha_mismatch_is_config_error(tmp_path):
    with pytest.raises(ConfigError, match="sha256"):
        _load_mut(tmp_path, lambda d: d["attribute_definitions"].update(sha256="0" * 64))


@pytest.mark.parametrize("body,msg", [("attributes:\n  x: {about: everyone}\n", "attribute"),
                                      ("attributes:\n  x: {about: patient, extra: 1}\n", "attribute"),
                                      ("nope: 1\n", "attributes")])
def test_bad_attribute_definitions_file_is_config_error(tmp_path, body, msg):
    f = tmp_path / "defs.yaml"; f.write_text(body)
    sha = hashlib.sha256(f.read_bytes()).hexdigest()
    with pytest.raises(ConfigError, match=msg):
        _load_mut(tmp_path, lambda d: d.update(attribute_definitions={"path": str(f), "sha256": sha}))


def test_unlisted_attribute_is_concept_dependent():
    c = load_config(CFG)
    assert not c.attr_is_concept_dependent("age_at_dx")
    assert c.attr_is_concept_dependent("cumulative_dose") and c.attr_is_concept_dependent("never_seen_attr")


def test_removed_config_fields_are_gone():
    c = load_config(CFG)
    for name in ("floor_source", "attribute_flags", "time_ladder", "relations", "max_depth", "max_candidates",
                 "value_ladders", "attr_ladders", "lvef_convention"):
        assert not hasattr(c, name), name
    raw = yaml.safe_load(open(CFG))
    assert not {"floor_source", "attribute_flags", "time_ladder", "relation_parents", "max_depth",
                "max_candidates", "value_ladders", "attr_ladders", "lvef_convention"} & set(raw)
    import semgen.config
    assert not hasattr(semgen.config, "Ladder")


@pytest.mark.parametrize("key, why", [("optimuskg", "cohort definition alone"), ("panel_sources", "A2")])
def test_retired_source_keys_are_config_errors(tmp_path, key, why):
    """The OptimusKG relation source (relevance gate) and A2 panel sources were removed; a stale key is an error,
    never silently ignored."""
    raw = _raw()
    raw[key] = [] if key == "panel_sources" else {"path": "x"}
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError, match=why):
        load_config(p)
    assert not hasattr(load_config(CFG), key)
