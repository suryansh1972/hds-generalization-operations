import hashlib
from pathlib import Path

import pytest
import yaml

from semgen.config import ConfigError, FloorSourceConfig, load_config
from semgen.sources import REPO_ROOT, SourceError, default_phecodex_dir, fetch_phecodex, verify_phecodex

CFG = "config/generalization.yaml"
COMMIT = "a" * 40
BLOBS = {"a.csv": b"phecode,code\n1,2\n", "b.csv": b"x,y\n", "c.csv": b"z\n"}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _src(blobs=BLOBS) -> FloorSourceConfig:
    return FloorSourceConfig(kind="phecodex", commit=COMMIT, files={k: _sha(v) for k, v in blobs.items()})


class _Resp:
    def __init__(self, data: bytes): self._d = data
    def read(self) -> bytes: return self._d
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Opener:
    def __init__(self, blobs): self.blobs, self.calls = blobs, []
    def __call__(self, url, timeout=None):
        self.calls.append((url, timeout))
        return _Resp(self.blobs[url.rsplit("/", 1)[1]])


def test_floor_source_loaded():
    s = load_config(CFG).floor_source
    assert s.kind == "phecodex" and s.commit == "6c5c6f787651c06351fe5a7c558a0a05c7a2f8a7"
    assert s.files["phecodeX_R_map_ICD_10_WHO.csv"] == "ba2cf94fdef67d7ea8fae63f12d38d4a5c389f579c257f189d05fc033e39c52a"
    assert s.phecode_level == "first_decimal" and s.icd10_map_refset == "447562003"
    assert s.map_rules == ("TRUE", "OTHERWISE TRUE") and s.licence == "unconfirmed"


def test_fetch_writes_and_verifies(tmp_path):
    op = _Opener(BLOBS)
    d = tmp_path / "new" / "dir"
    fetch_phecodex(d, _src(), opener=op)
    for k, v in BLOBS.items():
        assert (d / k).read_bytes() == v
    assert [u.rsplit("/", 1)[1] for u, _ in op.calls] == sorted(BLOBS)
    assert op.calls[0][0] == f"https://raw.githubusercontent.com/PheWAS/phecodeX/{COMMIT}/a.csv"
    assert all(t == 60 for _, t in op.calls)
    assert not [p for p in d.iterdir() if p.name not in BLOBS]


def test_fetch_skips_valid_existing(tmp_path):
    for k, v in BLOBS.items():
        (tmp_path / k).write_bytes(v)
    def boom(*a, **k): raise AssertionError("opener called")
    fetch_phecodex(tmp_path, _src(), opener=boom)


def test_tampered_download_raises_and_not_written(tmp_path):
    bad = dict(BLOBS, **{"b.csv": b"tampered"})
    with pytest.raises(SourceError, match="b.csv"):
        fetch_phecodex(tmp_path, _src(), opener=_Opener(bad))
    assert not (tmp_path / "b.csv").exists()


def test_tampered_file_raises_naming_file(tmp_path):
    for k, v in BLOBS.items():
        (tmp_path / k).write_bytes(v)
    (tmp_path / "c.csv").write_bytes(b"changed")
    with pytest.raises(SourceError, match="c.csv"):
        verify_phecodex(tmp_path, _src())


def test_invalid_existing_is_redownloaded(tmp_path):
    (tmp_path / "a.csv").write_bytes(b"junk")
    fetch_phecodex(tmp_path, _src(), opener=_Opener(BLOBS))
    assert (tmp_path / "a.csv").read_bytes() == BLOBS["a.csv"]


def test_missing_file_raises(tmp_path):
    with pytest.raises(SourceError, match="a.csv"):
        verify_phecodex(tmp_path, _src())


def test_default_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.delenv("SEMGEN_PHECODEX_DIR", raising=False)
    assert default_phecodex_dir(_src()) == REPO_ROOT / "data/external/phecodex" / COMMIT
    monkeypatch.setenv("SEMGEN_PHECODEX_DIR", str(tmp_path))
    assert default_phecodex_dir(_src()) == tmp_path


def _cfg_with(tmp_path, mutate):
    raw = yaml.safe_load(Path(CFG).read_text())
    mutate(raw["floor_source"])
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(raw))
    return p


@pytest.mark.parametrize("mutate", [
    lambda f: f.update(phecode_level="second"),
    lambda f: f.update(kind="other"),
    lambda f: f.update(commit="A" * 40),
    lambda f: f.update(commit="abc"),
    lambda f: f.update(files={"x.csv": "F" * 64}),
    lambda f: f.update(files={"x.csv": "abc"}),
    lambda f: f.update(files={}),
])
def test_bad_floor_source_rejected(tmp_path, mutate):
    with pytest.raises(ConfigError, match="floor_source"):
        load_config(_cfg_with(tmp_path, mutate))


def test_cli_no_subcommand_exits_2():
    import subprocess, sys
    r = subprocess.run([sys.executable, "-m", "semgen.sources"], capture_output=True, text=True)
    assert r.returncode == 2 and "usage" in (r.stdout + r.stderr).lower()
