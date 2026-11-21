"""Floor review report: one row per concept_lift decision, derived from the engine itself (DRAFT, POC only)."""
from __future__ import annotations

import sys

from semgen.interfaces import GenContext
from semgen.model import Motif
from semgen.operators.concept_lift import concept_lift

COLUMNS = ("motif_id", "node", "code", "fsn", "decision", "parent", "parent_fsn")


def floor_report(motifs: list[Motif], ctx: GenContext) -> list[dict]:
    h = ctx.hierarchy
    rows: list[dict] = []
    for m in motifs:
        res = concept_lift(m, ctx)
        entries = [(mv.change.target, mv.change.before, "allowed", mv.change.after) for mv in res.moves]
        entries += [(b.target, b.detail.get("code"), b.reason, b.detail.get("parent")) for b in res.blocked]
        for node, code, decision, parent in entries:
            rows.append({
                "motif_id": m.motif_id, "node": node, "code": code, "fsn": h.fsn(code),
                "decision": decision, "parent": parent,
                "parent_fsn": h.fsn(parent) if parent is not None else None})
    rows.sort(key=lambda r: (r["motif_id"], r["node"], r["parent"] or "", r["decision"]))
    return rows


def rows_to_tsv(rows: list[dict]) -> str:
    def cell(v) -> str:
        return "" if v is None else str(v).replace("\t", " ").replace("\n", " ")
    lines = ["\t".join(COLUMNS)] + ["\t".join(cell(r[c]) for c in COLUMNS) for r in rows]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """``python -m semgen.floor_report`` = ``semgen floor-report``."""
    import argparse

    from semgen.cli import main as cli_main
    ap = argparse.ArgumentParser(prog="python -m semgen.floor_report",
                                 description="TSV review of every concept_lift floor decision.")
    ap.add_argument("--motifs", required=True)
    ap.add_argument("--config", default=None)
    ap.add_argument("--rf2", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    fwd = ["floor-report", "--motifs", args.motifs]
    for k in ("config", "rf2", "out"):
        if getattr(args, k) is not None:
            fwd += [f"--{k}", getattr(args, k)]
    return cli_main(fwd)


if __name__ == "__main__":
    sys.exit(main())
