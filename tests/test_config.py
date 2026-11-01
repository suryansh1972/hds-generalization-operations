import hashlib

import pytest
import yaml

from semgen.config import ConfigError, config_sha256, load_config
from semgen.model import Interval

from pathlib import Path

CFG = str(Path(__file__).resolve().parents[1] / "config" / "generalization.yaml")


def test_loads_and_is_draft():
    c = load_config(CFG)
    assert c.status.startswith("DRAFT") and c.max_depth == 4


def test_lvef_ladder_walk():
    lad = load_config(CFG).value_ladder_for("250908004")
    walk, cur = [], Interval.point(38, "%")
    while (cur := lad.next_rung(cur)) is not None: walk.append((cur.lo, cur.hi, cur.hi_closed))
    assert walk == [(0, 40, False), (0, 50, False), (0, 55, False)]


def test_alt_ladder_walk_and_boundary():
    lad = load_config(CFG).value_ladder_for("364571000119101")
    assert lad.next_rung(Interval.point(3.0, "xULN")).hi == 3            # 3.0 is in (1,3]
    walk, cur = [], Interval.point(3.6, "xULN")
    while (cur := lad.next_rung(cur)) is not None: walk.append((cur.lo, cur.hi))
    assert walk == [(3, 5), (3, None), (1, None)]


def test_time_ladder_walk():
    lad, walk, cur = load_config(CFG).time_ladder, [], Interval.point(23, "d")
    while (cur := lad.next_rung(cur)) is not None: walk.append((cur.lo, cur.hi))
    assert walk == [(0, 30), (0, 90), (0, 365), (0, None)]


def test_value_outside_every_rung_has_no_move():
    assert load_config(CFG).value_ladder_for("250908004").next_rung(Interval.point(120, "%")) is None


def test_unit_mismatch_has_no_move():
    assert load_config(CFG).value_ladder_for("250908004").next_rung(Interval.point(38, "xULN")) is None


def test_unflagged_attr_is_concept_dependent():
    c = load_config(CFG)
    assert c.attr_is_concept_dependent("cumulative_dose") and not c.attr_is_concept_dependent("age_at_dx")
    assert c.attr_is_concept_dependent("never_seen_attr")


def test_relation_leq():
    r = load_config(CFG).relations
    assert r.leq("administered_drug", "exposed_to_drug") and r.leq("has_condition", "has_condition")
    assert not r.leq("exposed_to_drug", "administered_drug")


def test_no_floor_list_anywhere():
    assert "floors" not in yaml.safe_load(open(CFG))
    assert not hasattr(load_config(CFG), "floors")


def test_no_sctid_in_config():
    import re
    for line in open(CFG).read().splitlines():
        if "applies_to_concepts" in line or "icd10_map_refset" in line:
            continue
        assert not re.search(r"\b\d{6,18}\b", line), line


def test_config_sha256():
    h = config_sha256(CFG)
    assert len(h) == 64 and h == config_sha256(CFG)
    assert h == hashlib.sha256(open(CFG, "rb").read()).hexdigest()


@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d["value_ladders"]["lvef"]["rungs"].append([35, 45]), "laminar"),
    (lambda d: d["time_ladder"]["rungs"].append([-5, 30]), "negative"),
    (lambda d: d["relation_parents"].update({"exposed_to_drug": "administered_drug"}), "cycle"),
    (lambda d: d["value_ladders"]["lvef"]["rungs"].append({"lo": 0, "hi": 5, "unit": "mg"}), "unit"),
    (lambda d: d["floor_source"].update({"map_rules": []}), "floor_source"),
    (lambda d: d["floor_source"].update({"icd10_map_refset": "44756x003"}), "floor_source"),
    (lambda d: d["negation_policy"].update({"allow_drop_absent": True}), "not supported"),
    (lambda d: d.update(protected_roles=["patient"]), "protected_roles"),
    (lambda d: d.update(status="FINAL"), "DRAFT"),
])
def test_invalid_configs_fail_at_load(tmp_path, mutate, msg):
    d = yaml.safe_load(open(CFG)); mutate(d); p = tmp_path / "c.yaml"; p.write_text(yaml.safe_dump(d))
    with pytest.raises(ConfigError, match=msg): load_config(p)
