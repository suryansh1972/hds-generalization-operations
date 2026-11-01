import pytest

from semgen.icd10map import load_icd10_map
from semgen.snomed import default_rf2_dir

TERM = "tests/fixtures/icd10map/Terminology"
RULES = ("TRUE", "OTHERWISE TRUE")
REFSET = "447562003"


@pytest.fixture
def m():
    return load_icd10_map(TERM, REFSET, RULES)


def test_true_row(m):
    assert m.targets("1001") == {"A01.1"}


def test_otherwise_true_row(m):
    assert m.targets("1002") == {"B02.2"}


def test_ifa_ignored(m):
    assert m.targets("1003") == set()


def test_empty_target_gives_none(m):
    assert m.targets("1004") == set()


def test_inactive_ignored(m):
    assert m.targets("1005") == set()


def test_other_refset_ignored(m):
    assert m.targets("1006") == set()


def test_all_map_groups_count(m):
    assert m.targets("1007") == {"F07.1", "F07.2"}


def test_unknown_concept_and_metadata(m):
    assert m.targets("nope") == frozenset()
    assert m.release == "20990101" and m.refset_id == REFSET


def test_rules_restrict(m):
    assert load_icd10_map(TERM, REFSET, ("TRUE",)).targets("1002") == set()


def test_missing_map_dir(tmp_path):
    (tmp_path / "Terminology").mkdir()
    with pytest.raises(FileNotFoundError, match="ExtendedMapSnapshot"):
        load_icd10_map(tmp_path / "Terminology", REFSET, RULES)


@pytest.mark.snomed
def test_real_targets(real_icd_map):
    assert real_icd_map.targets("44054006") == {"E11.9"}
    assert real_icd_map.targets("405749004") == set()
    assert real_icd_map.targets("69896004") == {"M06.99"}
    assert real_icd_map.release == "20260201"
