import json

import pytest

import semgen.bundle as bundle_mod
from semgen.bundle import MotifBundle, MotifPart, Subject, bundle_canonical_json, bundle_hash
from semgen.canonical import motif_hash


def _two(m1, m2, **kw):
    args = {"bundle_id": "B", "semantics": "all", "anchor_part": "M1",
            "parts": (MotifPart(part_id="M1", motif=m1), MotifPart(part_id="M2", motif=m2))} | kw
    return MotifBundle(**args)


def test_of_single_hash_equals_motif_hash(fake_m1, fake_m2):
    for m in (fake_m1, fake_m2):
        b = MotifBundle.of(m)
        assert bundle_hash(b) == motif_hash(m)
        assert b.is_single and b.single_motif == m and b.semantics == "all" and b.anchor_part == m.motif_id
        assert b.part(m.motif_id).motif == m


def test_single_motif_raises_unless_single(fake_m1, fake_m2):
    with pytest.raises(ValueError):
        _ = _two(fake_m1, fake_m2).single_motif
    with pytest.raises(KeyError):
        MotifBundle.of(fake_m1).part("nope")


def test_multi_part_hash_ignores_bundle_id_and_subject(fake_m1, fake_m2):
    a = _two(fake_m1, fake_m2)
    b = _two(fake_m1, fake_m2, bundle_id="OTHER", subject=Subject(sex="F", age_days=20000))
    assert bundle_hash(a) == bundle_hash(b) and bundle_canonical_json(a) == bundle_canonical_json(b)
    assert bundle_hash(a) != motif_hash(fake_m1)


def test_multi_part_hash_order_independent(fake_m1, fake_m2):
    a = _two(fake_m1, fake_m2)
    b = a.model_copy(update={"parts": tuple(reversed(a.parts))})
    assert bundle_hash(a) == bundle_hash(b)


def test_multi_part_hash_sees_anchor_part(fake_m1, fake_m2):
    assert bundle_hash(_two(fake_m1, fake_m2)) != bundle_hash(_two(fake_m1, fake_m2, anchor_part="M2"))


def test_no_aggregate_representation(fake_m1, fake_m2):
    """Motif aggregation was removed: there is no aggregate part, and OR alternatives are an "any" bundle of plain
    parts whose canonical form lists each part's motif."""
    for name in ("AggregatePart", "aggregate_part_id", "AGG_PREFIX"):
        assert not hasattr(bundle_mod, name)
    b = _two(fake_m1, fake_m2, semantics="any")
    assert [sorted(p) for p in json.loads(bundle_canonical_json(b))["parts"]] == [["motif", "part_id"]] * 2


def test_bundle_rejects_unknown_anchor_and_duplicate_parts(fake_m1, fake_m2):
    with pytest.raises(ValueError):
        _two(fake_m1, fake_m2, anchor_part="M9")
    with pytest.raises(ValueError):
        MotifBundle(bundle_id="B", semantics="all", anchor_part="M1",
                    parts=(MotifPart(part_id="M1", motif=fake_m1), MotifPart(part_id="M1", motif=fake_m1)))


def test_semantics_none_allowed_and_hashed_distinctly(fake_m1, fake_m2):
    none, all_, any_ = (_two(fake_m1, fake_m2, semantics=s) for s in (None, "all", "any"))
    assert none.semantics is None
    assert len({bundle_hash(none), bundle_hash(all_), bundle_hash(any_)}) == 3
