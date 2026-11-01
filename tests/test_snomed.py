import pytest

from semgen.snomed import FsnError, check_floors, load_rf2
from tests.conftest import *  # noqa: F401,F403  (constants)

FIX = "tests/fixtures/rf2"


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


def test_check_floors_rejects_unknown(fake_h, tmp_path):
    from semgen.config import ConfigError, load_config

    c = load_config("config/generalization.yaml")
    check_floors(c, fake_h)
    with pytest.raises(ConfigError, match="floor"):
        check_floors(c.model_copy(update={"floors": ("123",)}), fake_h)
    with pytest.raises(ConfigError, match="floor"):
        check_floors(c.model_copy(update={"floors": (RA_OLD_PARENT,)}), fake_h)


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
