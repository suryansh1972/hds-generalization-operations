import pytest

from semgen.snomed import FsnError, Hierarchy, load_rf2
from tests.conftest import *  # noqa: F401,F403  (constants)

FIX = str(__import__("pathlib").Path(__file__).resolve().parent / "fixtures" / "rf2")


def test_inferred_active_isa_only(tmp_path):
    h = load_rf2(FIX, cache_dir=tmp_path)
    assert h.parents("C") == {"B"} and h.parents("D") == {"138875005"}
    assert h.release == "20990101"


def test_fsn_resolution_uses_active_concepts_only(tmp_path):
    h = load_rf2(FIX, cache_dir=tmp_path)
    assert h.resolve_fsn("Dup (disorder)") == "D" and h.resolve_fsn("Bee (disorder)") == "B"
    with pytest.raises(FsnError, match="Bee"):
        h.resolve_fsn("Bee")  # synonym, not FSN


def test_cache_roundtrip(tmp_path):
    a = load_rf2(FIX, cache_dir=tmp_path)
    b = load_rf2(FIX, cache_dir=tmp_path)
    assert a.parents("C") == b.parents("C") and any(tmp_path.glob("snomed_20990101*.pkl"))
    assert len(list(tmp_path.glob("*.pkl"))) == 1


def test_cache_not_shared_across_directories(tmp_path):
    import shutil

    other = tmp_path / "other"
    shutil.copytree(FIX, other)
    (other / "sct2_Relationship_Snapshot_INT_20990101.txt").write_text(
        (other / "sct2_Relationship_Snapshot_INT_20990101.txt").read_text().replace("\tB\t138875005", "\tB\tC", 1)
    )
    cache = tmp_path / "cache"
    a = load_rf2(FIX, cache_dir=cache)
    b = load_rf2(other, cache_dir=cache)
    assert a.parents("B") != b.parents("B")
    assert len(list(cache.glob("*.pkl"))) == 2


def test_stale_glob_ignores_stated_files(tmp_path):
    import shutil

    d = tmp_path / "t"
    shutil.copytree(FIX, d)
    (d / "sct2_StatedRelationship_Snapshot_INT_20990101.txt").write_text("junk")
    (d / "sct2_RelationshipConcreteValues_Snapshot_INT_20990101.txt").write_text("junk")
    assert load_rf2(d, cache_dir=tmp_path / "c").parents("C") == {"B"}


def test_unknowns_and_depth(tmp_path):
    h = load_rf2(FIX, cache_dir=tmp_path)
    assert h.parents("zzz") == frozenset() and h.ancestors("zzz") == frozenset()
    assert h.is_descendant_or_self("zzz", "zzz") and not h.is_active("zzz")
    assert h.is_active("B") and not h.is_active("E")
    assert h.fsn("B") == "Bee (disorder)" and h.fsn("C") is None
    assert h.depth("138875005") == 0 and h.depth("C") == 2
    with pytest.raises(ValueError):
        h.depth("zzz")
    assert h.edition == "International"


def test_direction_helpers(fake_h):
    assert fake_h.is_descendant_or_self(BRCA, MALIG)
    assert not fake_h.is_descendant_or_self(MALIG, BRCA)
    assert fake_h.is_descendant_or_self(MALIG, MALIG)
    assert MALIG in fake_h.ancestors(BRCA) and BRCA not in fake_h.ancestors(BRCA)
    assert BRCA in fake_h.ancestors_or_self(BRCA)
    assert not fake_h.is_descendant_or_self(NEO_BREAST, MALIG)
    assert fake_h.depth(BRCA) == 3 and fake_h.depth(ROOT) == 0
    with pytest.raises(ValueError):
        fake_h.depth(RA_OLD_PARENT)


@pytest.mark.snomed
def test_real_direction(real_h):
    assert real_h.is_descendant_or_self(BRCA, MALIG) and not real_h.is_descendant_or_self(MALIG, BRCA)
    assert real_h.is_descendant_or_self(T2DM, DM)
    for c in ("709044004", "233703007", RA, T2DM):
        assert not real_h.is_descendant_or_self(c, MALIG)
    assert real_h.parents(BRCA) == {NEO_BREAST, MAL_THORAX}
    assert real_h.parents("703228009") == {"254637007"}
    assert real_h.resolve_fsn("Left ventricular ejection fraction (observable entity)") == LVEF
    assert real_h.release == "20260201" and real_h.edition == "International"


def test_descendants_or_self(fake_h):
    assert fake_h.descendants_or_self(DM) == {DM, T1DM, T2DM}
    assert fake_h.descendants_or_self(MALIG) == {MALIG, MAL_THORAX, BRCA}
    assert fake_h.descendants_or_self("zzz") == {"zzz"}


def test_descendants_pickle_roundtrip(fake_h):
    import pickle

    fake_h.descendants_or_self(DM)
    h2 = pickle.loads(pickle.dumps(fake_h))
    assert h2._children is None and h2._desc_memo == {}
    assert h2.descendants_or_self(DM) == {DM, T1DM, T2DM}


@pytest.mark.snomed
def test_real_descendants_or_self(real_h):
    assert len(real_h.descendants_or_self("254637007")) == 36


def test_non_isa_row_ignored(tmp_path):
    assert load_rf2(FIX, cache_dir=tmp_path).parents("C") == {"B"}


def test_parents_and_children_are_opposite_directions(fake_h):
    assert MAL_THORAX in fake_h.parents(BRCA) and BRCA in fake_h.children(MAL_THORAX)
    assert fake_h.children(BRCA) == frozenset() and BRCA not in fake_h.parents(MAL_THORAX)


def test_descendants_is_strict(fake_h):
    assert DM not in fake_h.descendants(DM) and fake_h.descendants(DM) == {T1DM, T2DM}


def test_descendant_count_diamond_counts_once():
    h = Hierarchy.from_maps({"L": {"A", "B"}, "A": {"T"}, "B": {"T"}, "T": set()}, {}, {"L", "A", "B", "T"})
    assert h.descendant_count("T") == 3 and h.descendant_count("A") == 1


def test_descendant_count_ignores_inactive():
    h = Hierarchy.from_maps({"X": {"T"}, "Y": {"T"}, "T": set()}, {}, {"X", "T"})
    assert h.descendant_count("T") == 1


def test_semantic_tag():
    h = Hierarchy.from_maps({}, {"A": "Foo (bar baz)", "B": "No tag"}, {"A", "B"})
    assert h.semantic_tag("A") == "bar baz" and h.semantic_tag("B") is None and h.semantic_tag("zzz") is None


def test_old_cache_is_rebuilt(tmp_path, monkeypatch):
    load_rf2(FIX, cache_dir=tmp_path)
    monkeypatch.setattr("semgen.snomed.CACHE_VERSION", "test-other")
    load_rf2(FIX, cache_dir=tmp_path)
    assert len(list(tmp_path.glob("*.pkl"))) == 2


def test_characteristic_type_recorded(tmp_path):
    assert load_rf2(FIX, cache_dir=tmp_path).characteristic_type == "inferred"
