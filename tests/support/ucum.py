"""Test-only UCUM essence: a ``Ucum`` over the given atoms (synthetic, no prefixes), for A1 tests that must not
depend on the uncommitted essence file under data/external/. Never imported by ``src/``."""
from semgen.ucum import Ucum


def test_ucum(*atoms: str) -> Ucum:
    return Ucum(version="test", sha256="0" * 64, atoms=frozenset(atoms), metric=frozenset(), prefixes=frozenset())


test_ucum.__test__ = False   # not a pytest test
