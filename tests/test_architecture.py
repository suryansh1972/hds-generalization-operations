"""Structural guarantees: no import cycles, a core that works without Litestar, no personal paths, packaged config."""
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "semgen"
MODULES = sorted(".".join(p.relative_to(SRC.parent).with_suffix("").parts).removesuffix(".__init__")
                 for p in SRC.rglob("*.py"))
CORE = [m for m in MODULES if not m.startswith("semgen.api")]


def _py(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO)


@pytest.mark.parametrize("module", MODULES)
def test_every_module_imports_first(module):
    """Each module imported first in a fresh interpreter: a circular import fails here."""
    if module.startswith("semgen.api"):
        pytest.importorskip("litestar")
    r = _py(f"import {module}")
    assert r.returncode == 0, r.stderr


def test_core_works_without_litestar():
    """Block litestar/uvicorn and import every core module plus the CLI; ``semgen.api`` fails with a clear hint."""
    code = ("import sys\n"
            "for m in ('litestar', 'uvicorn'): sys.modules[m] = None\n"
            + "".join(f"import {m}\n" for m in CORE) +
            "import semgen.api\n"
            "try:\n    semgen.api.create_app\nexcept ImportError as e:\n    assert 'semgen[api]' in str(e); print('ok')\n")
    r = _py(code)
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr


def test_core_does_not_import_the_web_framework():
    r = _py("import sys, semgen, semgen.cli, semgen.engine\n"
            "print(sorted(m for m in sys.modules if m.split('.')[0] in {'litestar', 'uvicorn'}))")
    assert r.returncode == 0 and r.stdout.strip() == "[]", r.stdout + r.stderr


def test_no_module_level_mutable_operator_registry():
    import semgen.lattice as L
    import semgen.operators as ops
    assert isinstance(ops.ALL_OPERATORS, tuple) and isinstance(ops.BUNDLE_OPERATORS, tuple)
    assert not hasattr(L, "ALL_OPERATORS") and not hasattr(L, "BUNDLE_OPERATORS")


PERSONAL = re.compile(r"/Users/[A-Za-z]|/home/[a-z][a-z0-9_-]*/|C:\\\\Users\\\\")
TEXT = {".py", ".md", ".toml", ".yaml", ".yml", ".json", ".jsonl", ".txt", ".cfg", ".ini", ".csv", ".example"}


def _published_files() -> list[Path]:
    """Files git would publish (tracked or untracked-but-not-ignored); falls back to a walk outside a git checkout."""
    r = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                       capture_output=True, cwd=REPO)
    if r.returncode != 0:
        return [p for p in REPO.rglob("*") if p.is_file() and ".venv" not in p.parts and ".git" not in p.parts]
    return [REPO / f for f in r.stdout.decode().split("\0") if f and (REPO / f).is_file()]


def test_no_personal_paths_in_published_files():
    hits = []
    for p in _published_files():
        if p.suffix in TEXT or p.name in {".gitignore", ".env.example"}:
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if PERSONAL.search(line):
                    hits.append(f"{p.relative_to(REPO)}:{i}")
    assert not hits, hits


def test_restricted_data_is_not_published():
    """No MIMIC record, RF2 release file, parsed-release cache, local env file or Mayo DB would be published."""
    bad = []
    for p in _published_files():
        rel = p.relative_to(REPO).as_posix()
        name = p.name
        if rel.startswith("tests/fixtures/rf2/"):
            continue                                             # synthetic 3-file release (fake ids)
        if name in {".gitkeep", "README.md"}:
            continue                                             # placeholders documenting where local data goes
        data_file = p.suffix in {".json", ".jsonl", ".gz", ".csv", ".parquet", ".txt", ".xml"}
        if (re.match(r"(sct2|der2|xsct2|xder2)_.*\.txt$", name) or name.endswith((".pkl", ".sqlite", ".db"))
                or ("mimic" in name.lower() and data_file) or name == ".env"
                or rel.startswith(("data/cache/", "data/external/"))
                or rel.startswith("tests/fixtures/golden/real_") or rel.startswith("tests/fixtures/golden/head/real_")):
            bad.append(rel)
    assert not bad, bad


def test_packaged_config_loads_and_needs_no_checkout():
    from semgen.config import load_config
    from semgen.settings import default_config_path
    p = default_config_path()
    assert p.is_file() and p.parent.name == "resources" and (p.parent / "attribute_definitions.yaml").is_file()
    cfg = load_config()
    assert cfg.mayo.path is None and cfg.ucum is not None and cfg.ucum.path is None
    assert (SRC / "py.typed").is_file()
