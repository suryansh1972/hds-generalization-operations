"""CLI: ``python -m semgen run --motifs PATH --config PATH --out DIR``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from semgen.config import ConfigError
from semgen.context import build_context
from semgen.export import run_header, write_lattice
from semgen.lattice import GeneralizationOrderError, PolicyViolation, enumerate_lattice
from semgen.motif_io import MotifError, load_motifs
from semgen.snomed import FsnError
from semgen.sources import REPO_ROOT, SourceError


def _nonneg_int(v: str) -> int:
    try:
        n = int(v)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{v!r} is not an integer") from None
    if n < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {n}")
    return n


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m semgen")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="enumerate and export the generalization lattice of each motif")
    run.add_argument("--motifs", type=Path, required=True)
    run.add_argument("--config", type=Path, default=REPO_ROOT / "config" / "generalization.yaml")
    run.add_argument("--rf2", type=Path, default=None)
    run.add_argument("--phecodex", type=Path, default=None)
    run.add_argument("--floor-policy", choices=("snomed_boundary", "phecodex"), default=None,
                     help="override floor_policy.mode from the config")
    run.add_argument("--depth", type=_nonneg_int, default=None)
    run.add_argument("--out", type=Path, required=True)
    return ap


def _run(args: argparse.Namespace) -> int:
    ctx = build_context(args.config, args.rf2, args.phecodex, args.floor_policy)
    depth = ctx.config.max_depth if args.depth is None else args.depth
    header = run_header(ctx, args.config, depth)
    motifs = load_motifs(args.motifs, ctx.hierarchy)
    ids = [m.motif_id for m in motifs]
    dups = sorted({i for i in ids if ids.count(i) > 1})
    if dups:
        raise MotifError(f"duplicate motif ids in {args.motifs}: {', '.join(dups)}")
    for m in motifs:
        lat = enumerate_lattice(m, ctx, depth)
        write_lattice(lat, m.motif_id, args.out, header)
        print(f"{m.motif_id} depth={depth} candidates={len(lat.candidates)} "
              f"edges={len(lat.edges)} blocked={len(lat.blocked)} status={lat.status}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args)
    except (ConfigError, SourceError, MotifError, FileNotFoundError, FsnError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except (PolicyViolation, GeneralizationOrderError) as e:
        print(f"internal invariant violated: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
