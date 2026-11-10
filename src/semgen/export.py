"""Deterministic JSONL export of a lattice plus its run header (no timestamps)."""
from __future__ import annotations

import json
import re
from importlib.metadata import version
from pathlib import Path

from semgen.canonical import canonical_json
from semgen.config import config_sha256
from semgen.lattice import Lattice
from semgen.motif_io import MotifError
from semgen.operators.base import GenContext


def run_header(ctx: GenContext, config_path: str | Path, max_depth: int) -> dict:
    prov = ctx.floors.provenance
    hdr = {
        "snomed_release": ctx.hierarchy.release,
        "snomed_edition": ctx.hierarchy.edition,
        "config_sha256": config_sha256(config_path),
        "config_status": ctx.config.status,
        "lvef_convention": ctx.config.lvef_convention,
        "temporal_semantics": "certain",
        "absent_semantics": "closed-world: no recorded fact that is the concept or any descendant",
        "max_depth": max_depth,
        "semgen_version": version("semgen"),
        "floor_policy": prov,
        "max_candidates": ctx.config.max_candidates,
    }
    if prov.get("mode") == "phecodex":
        src = ctx.config.floor_source
        hdr.update({
            "floor_source": prov["floor_source"],
            "phecode_level": prov["phecode_level"],
            "icd10_map_refset": prov["icd10_map_refset"],
            "icd10_map_release": prov["icd10_map_release"],
            "phecodex_commit": src.commit,
            "phecodex_sha256": dict(src.files),
            "ccsr_check": "unavailable",
            "source_licences": {"phecodex": src.licence},
        })
    return hdr


def _line(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n"


def _write(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write_lattice(lat: Lattice, motif_id: str, out_dir: Path, header: dict) -> dict[str, Path]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", motif_id) or motif_id in {".", ".."}:
        raise MotifError(f"unsafe motif_id {motif_id!r}: must match [A-Za-z0-9_.-]+ and not be '.' or '..'")
    d = Path(out_dir) / motif_id
    if not d.resolve().is_relative_to(Path(out_dir).resolve()) or d.resolve() == Path(out_dir).resolve():
        raise MotifError(f"motif_id {motif_id!r} escapes the output directory")
    d.mkdir(parents=True, exist_ok=True)
    cands = sorted(lat.candidates.values(), key=lambda c: (c.depth, c.hash))
    cand_rows = [{"hash": c.hash, "depth": c.depth, "origin": c.origin, "motif": json.loads(canonical_json(c.motif))} for c in cands]
    edge_rows = sorted(({"parent": e.parent, "child": e.child, "changes": [c.to_json() for c in e.changes]}
                        for e in lat.edges), key=lambda r: (r["parent"], r["child"]))
    blocked_rows = sorted(
        ({"from": frm, "op": b.op, "target": b.target, "reason": b.reason, "detail": b.detail}
         for frm, b in lat.blocked),
        key=lambda r: (r["from"], r["op"], r["target"], r["reason"], json.dumps(r["detail"], sort_keys=True)))
    paths = {k: d / n for k, n in (("run_header", "run_header.json"), ("candidates", "candidates.jsonl"),
                                    ("edges", "edges.jsonl"), ("blocked", "blocked.jsonl"),
                                    ("termination", "termination.json"))}
    term = {"status": lat.status, "complete": lat.status == "exhausted", "max_depth": header.get("max_depth"),
            "max_candidates": header.get("max_candidates"), "unexpanded_frontier": lat.unexpanded,
            "candidates": len(lat.candidates)}
    term["axes"] = {n: {"status": a.status, "reached": list(a.reached), "stopped_by": list(a.stopped_by)}
                    for n, a in lat.axes.items()}
    _write(paths["run_header"], json.dumps(header, sort_keys=True, indent=2) + "\n")
    _write(paths["candidates"], "".join(_line(r) for r in cand_rows))
    _write(paths["edges"], "".join(_line(r) for r in edge_rows))
    _write(paths["blocked"], "".join(_line(r) for r in blocked_rows))
    _write(paths["termination"], json.dumps(term, sort_keys=True, indent=2) + "\n")
    return paths
