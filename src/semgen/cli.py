"""Command line interface (``semgen`` / ``python -m semgen``), a thin layer over ``semgen.engine.SemgenEngine``.

    semgen run --motifs PATH --out DIR [--config PATH] [--rf2 DIR] [budget options]
    semgen validate --motifs PATH [--rf2 DIR]
    semgen lift CODE [--parent CODE] [--rf2 DIR]
    semgen floor-report --motifs PATH [--out FILE]
    semgen serve [--host H] [--port P]            (needs the ``api`` extra)

Every location option falls back to its ``SEMGEN_*`` environment variable (``semgen.settings``).
Exit codes: 0 ok, 1 input/config error, 2 usage error, 3 internal invariant violated.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from semgen.config import ConfigError
from semgen.engine import SemgenEngine
from semgen.export import kept_candidates, output_dir
from semgen.lattice import Budget, GeneralizationOrderError, PolicyViolation
from semgen.motif_io import MotifError
from semgen.settings import Settings
from semgen.snomed import FsnError

DEPTH_NOTE = ("note: --depth only filters output; the search is bounded by "
              "--max-depth-budget/--max-states/--time-budget (none given: unbounded)")


def _nonneg_int(v: str) -> int:
    try:
        n = int(v)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{v!r} is not an integer") from None
    if n < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {n}")
    return n


def _pos_int(v: str) -> int:
    try:
        n = int(v)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{v!r} is not an integer") from None
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {n}")
    return n


def _nonneg_float(v: str) -> float:
    try:
        x = float(v)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{v!r} is not a number") from None
    if not x >= 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {v}")
    return x


def _locations(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", type=Path, default=None, help="config YAML (default: SEMGEN_CONFIG or packaged)")
    p.add_argument("--rf2", type=Path, default=None, help="SNOMED CT RF2 release (default: SEMGEN_RF2_DIR)")


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="semgen", description="Deterministic symbolic generalization of clinical "
                                                            "graph motifs over SNOMED CT.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="enumerate and export the generalization lattice of each bundle (or motif)")
    run.add_argument("--motifs", type=Path, required=True,
                     help="a motif list (each motif a bundle of one) or a {\"bundles\": [...]} file")
    _locations(run)
    run.add_argument("--depth", type=_nonneg_int, default=None,
                     help="output filter only: write candidates at depth <= N, the edges between them and the "
                          "blocked moves from them (the summary line counts the same)")
    run.add_argument("--max-states", type=_pos_int, default=None, help="search budget: states stored, root included")
    run.add_argument("--max-depth-budget", type=_nonneg_int, default=None,
                     help="search budget: states at this depth are stored but not expanded")
    run.add_argument("--time-budget", type=_nonneg_float, default=None,
                     help="search budget in seconds (a run it stops is not byte-reproducible)")
    run.add_argument("--progress", action="store_true",
                     help="also stream each accepted candidate, in BFS order, to OUT/<bundle_id>/progress.jsonl")
    run.add_argument("--out", type=Path, required=True)

    val = sub.add_parser("validate", help="parse and validate a motif or bundle file against the release")
    val.add_argument("--motifs", type=Path, required=True)
    _locations(val)

    lift = sub.add_parser("lift", help="inspect concept lift from a SNOMED CT concept (JSON on stdout)")
    lift.add_argument("code")
    lift.add_argument("--parent", default=None, help="check only the single step CODE -> PARENT")
    lift.add_argument("--max-transitions", type=_pos_int, default=None)
    _locations(lift)

    fr = sub.add_parser("floor-report", help="TSV review of every concept_lift decision")
    fr.add_argument("--motifs", type=Path, required=True)
    fr.add_argument("--out", type=Path, default=None)
    _locations(fr)

    srv = sub.add_parser("serve", help="run the HTTP API (requires: pip install 'semgen[api]')")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8000)
    _locations(srv)
    return ap


def _engine(args: argparse.Namespace) -> SemgenEngine:
    return SemgenEngine.from_config(args.config, args.rf2, settings=Settings.from_env())


def _run(args: argparse.Namespace) -> int:
    engine = _engine(args)
    budget = Budget(max_states=args.max_states, max_depth=args.max_depth_budget, seconds=args.time_budget)
    if args.depth is not None and args.max_depth_budget is None:
        print(DEPTH_NOTE, file=sys.stderr)
    bundles = engine.load(args.motifs)   # a motif list: each motif is a bundle of one
    dirs = {b.bundle_id: output_dir(args.out, b.bundle_id) for b in bundles}   # every id checked before any write
    shown = "all" if args.depth is None else args.depth
    for b in bundles:
        progress = None
        if args.progress:
            dirs[b.bundle_id].mkdir(parents=True, exist_ok=True)
            progress = dirs[b.bundle_id] / "progress.jsonl"
        res = engine.generalize(b, budget, progress=progress)
        res.write(args.out, args.depth)
        lat = res.lattice
        kept = kept_candidates(lat, args.depth)
        n_edges = sum(1 for e in lat.edges if e.parent in kept and e.child in kept)
        n_blocked = sum(1 for frm, _ in lat.blocked if args.depth is None or frm in kept)
        print(f"{b.bundle_id} depth={shown} candidates={len(kept)} "
              f"edges={n_edges} blocked={n_blocked} status={lat.status}")
    return 0


def _validate(args: argparse.Namespace) -> int:
    for b in _engine(args).load(args.motifs):
        print(f"{b.bundle_id} ok parts={len(b.parts)} semantics={b.semantics}")
    return 0


def _lift(args: argparse.Namespace) -> int:
    engine = _engine(args)
    out = (engine.check_lift(args.code, args.parent) if args.parent is not None
           else engine.inspect_lift(args.code, args.max_transitions))
    json.dump(out, sys.stdout, sort_keys=True, indent=2)
    sys.stdout.write("\n")
    return 0


def _floor_report(args: argparse.Namespace) -> int:
    from semgen.floor_report import floor_report, rows_to_tsv
    from semgen.motif_io import load_motifs
    engine = _engine(args)
    motifs = load_motifs(args.motifs, engine.context.hierarchy)
    text = rows_to_tsv(floor_report(motifs, engine.context))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


def _serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn

        from semgen.api import create_app
    except ImportError:
        print("error: the HTTP API needs the 'api' extra: pip install 'semgen[api]'", file=sys.stderr)
        return 1
    settings = Settings.from_env(config_path=args.config, rf2_dir=args.rf2)
    uvicorn.run(create_app(settings=settings), host=args.host, port=args.port)
    return 0


COMMANDS = {"run": _run, "validate": _validate, "lift": _lift, "floor-report": _floor_report, "serve": _serve}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return COMMANDS[args.cmd](args)
    except (ConfigError, MotifError, FileNotFoundError, FsnError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except (PolicyViolation, GeneralizationOrderError) as e:
        print(f"internal invariant violated: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
