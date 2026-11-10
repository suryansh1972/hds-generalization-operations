"""Pinned, sha256-verified fetch of the PhecodeX source files (DRAFT, POC only)."""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable

from semgen.config import ConfigError, FloorSourceConfig, load_config

REPO_ROOT = Path(__file__).resolve().parents[2]
URL = "https://raw.githubusercontent.com/PheWAS/phecodeX/{commit}/{file}"


class SourceError(Exception):
    """Raised when a pinned source file is missing, tampered with or fails to download."""


def default_phecodex_dir(src: FloorSourceConfig) -> Path:
    env = os.environ.get("SEMGEN_PHECODEX_DIR")
    return Path(env) if env else REPO_ROOT / "data" / "external" / "phecodex" / src.commit


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _status(dir_: Path, name: str, expected: str) -> str:
    """'ok', 'missing' or 'mismatch'."""
    p = dir_ / name
    if not p.is_file():
        return "missing"
    return "ok" if _sha256(p) == expected else "mismatch"


def verify_phecodex(dir_: Path, src: FloorSourceConfig) -> None:
    for name in sorted(src.files):
        st = _status(Path(dir_), name, src.files[name])
        if st == "missing":
            raise SourceError(f"PhecodeX file {name} is missing from {dir_}")
        if st == "mismatch":
            raise SourceError(
                f"PhecodeX file {name} in {dir_} has sha256 {_sha256(Path(dir_) / name)}, "
                f"expected {src.files[name]}")


def fetch_phecodex(dir_: Path, src: FloorSourceConfig,
                   opener: Callable = urllib.request.urlopen,
                   report: Callable[[str, str], None] | None = None) -> None:
    dir_ = Path(dir_)
    dir_.mkdir(parents=True, exist_ok=True)
    for name in sorted(src.files):
        expected = src.files[name]
        if _status(dir_, name, expected) == "ok":
            if report: report(name, "ok (already present)")
            continue
        url = URL.format(commit=src.commit, file=name)
        try:
            with opener(url, timeout=60) as resp:
                data = resp.read()
        except OSError as e:
            raise SourceError(f"cannot download PhecodeX file {name} from {url}: {e}") from e
        got = hashlib.sha256(data).hexdigest()
        if got != expected:
            raise SourceError(f"PhecodeX file {name} downloaded from {url} has sha256 {got}, "
                              f"expected {expected}; not written")
        fd, tmp = tempfile.mkstemp(dir=dir_, prefix=f".{name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.chmod(tmp, 0o644)
            os.replace(tmp, dir_ / name)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        if report: report(name, "downloaded")
    verify_phecodex(dir_, src)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m semgen.sources")
    sub = ap.add_subparsers(dest="cmd")
    f = sub.add_parser("fetch", help="download and verify the pinned PhecodeX files")
    f.add_argument("--dir", type=Path, default=None)
    args = ap.parse_args(argv)
    if args.cmd != "fetch":
        ap.print_usage(sys.stderr)
        return 2
    try:
        src = load_config(REPO_ROOT / "config" / "generalization.yaml").floor_source
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if src is None:
        print("error: no floor_source configured (floor_policy mode snomed_boundary needs no PhecodeX files)",
              file=sys.stderr)
        return 1
    d = args.dir or default_phecodex_dir(src)
    try:
        fetch_phecodex(d, src, report=lambda n, s: print(f"{n}: {s}"))
    except SourceError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"verified {len(src.files)} files in {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
