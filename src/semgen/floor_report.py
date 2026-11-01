"""Floor review report: one row per concept_lift decision, derived from the engine itself (DRAFT, POC only)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from semgen.config import ConfigError
from semgen.context import build_context
from semgen.model import Motif
from semgen.motif_io import MotifError, load_motifs
from semgen.operators.base import GenContext
from semgen.operators.concept_lift import concept_lift
from semgen.sources import REPO_ROOT, SourceError

COLUMNS = ("motif_id", "node", "code", "fsn", "decision", "parent", "parent_fsn", "anchors",
           "blocking_descendant", "blocking_fsn", "anchor")


def _anchors(ctx: GenContext, code: str, decision: str) -> str:
    if decision in {"allowed", "outside_floor", "inactive_parent", "unmapped"}:   # floor was actually consulted
        return ";".join(sorted(ctx.floors.anchors(code)))
    return ""


def floor_report(motifs: list[Motif], ctx: GenContext) -> list[dict]:
    h = ctx.hierarchy
    rows: list[dict] = []
    for m in motifs:
        res = concept_lift(m, ctx)
        entries = [(mv.change.target, mv.change.before, "allowed", mv.change.after, {}) for mv in res.moves]
        entries += [(b.target, b.detail.get("code"), b.reason, b.detail.get("parent"), b.detail) for b in res.blocked]
        for node, code, decision, parent, detail in entries:
            rows.append({
                "motif_id": m.motif_id, "node": node, "code": code, "fsn": h.fsn(code),
                "decision": decision, "parent": parent,
                "parent_fsn": h.fsn(parent) if parent is not None else None,
                "anchors": _anchors(ctx, code, decision),
                "blocking_descendant": detail.get("blocking_descendant"),
                "blocking_fsn": detail.get("blocking_fsn"), "anchor": detail.get("anchor")})
    rows.sort(key=lambda r: (r["motif_id"], r["node"], r["parent"] or "", r["decision"]))
    return rows


def rows_to_tsv(rows: list[dict]) -> str:
    def cell(v) -> str:
        return "" if v is None else str(v).replace("\t", " ").replace("\n", " ")
    lines = ["\t".join(COLUMNS)] + ["\t".join(cell(r[c]) for c in COLUMNS) for r in rows]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m semgen.floor_report",
                                 description="TSV review of every concept_lift floor decision.")
    ap.add_argument("--motifs", type=Path, required=True)
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config" / "generalization.yaml")
    ap.add_argument("--rf2", type=Path, default=None)
    ap.add_argument("--phecodex", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    try:
        ctx = build_context(args.config, args.rf2, args.phecodex)
        text = rows_to_tsv(floor_report(load_motifs(args.motifs, ctx.hierarchy), ctx))
    except (SourceError, FileNotFoundError, ConfigError, MotifError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
