"""Deterministic JSONL export of a lattice plus its run header (no timestamps, no machine-specific paths)."""
from __future__ import annotations

import json
import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from semgen.config import config_sha256
from semgen.interfaces import GenContext
from semgen.lattice import Budget, Lattice, candidate_row, json_line
from semgen.motif_io import MotifError


def semgen_version() -> str:
    try:
        return version("semgen")
    except PackageNotFoundError:   # imported from a source tree without being installed
        return "0+unknown"


def _mayo_header(ctx: GenContext) -> dict:
    """The Mayo source by content (sha256), never by its machine-specific path (C3)."""
    src = ctx.refranges
    if src is None:
        return {"sha256": ctx.config.mayo.sha256, "available": False, "test_map_sha256": None}
    return {"sha256": src.sha256, "available": True, "test_map_sha256": src.test_map_sha256}


def run_header(ctx: GenContext, config_path: str | Path | None, budget: Budget) -> dict:
    """Provenance of a run: release, config and attribute-definition hashes, budget, version, concept-lift and
    source fingerprints. Content hashes only, never machine-specific paths. ``config_path`` None = packaged config."""
    return {
        "snomed_release": ctx.hierarchy.release,
        "snomed_edition": ctx.hierarchy.edition,
        "config_sha256": config_sha256(config_path),
        "config_status": ctx.config.status,
        "temporal_semantics": "certain",
        "absent_semantics": "closed-world: no recorded fact that is the concept or any descendant",
        "budget": budget.to_json(),
        "attribute_definitions_sha256": ctx.config.attribute_definitions_sha256,
        "semgen_version": semgen_version(),
        "floor_policy": ctx.floors.provenance,
        "sources": {"mayo": _mayo_header(ctx)},
    }


def kept_candidates(lat: Lattice, depth: int | None) -> set[str]:
    """Hashes of the candidates an output filtered to ``depth`` keeps (all of them for None)."""
    return {h for h, c in lat.candidates.items() if depth is None or c.depth <= depth}


def _write(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def output_dir(out_dir: Path, bundle_id: str) -> Path:
    """The output directory ``out_dir/<bundle_id>`` of one run, validated without touching the file system:
    the id must match ``[A-Za-z0-9_.-]+``, not be ``.`` or ``..``, and stay inside ``out_dir`` (else MotifError).
    Call it before anything is created for the run."""
    if not isinstance(bundle_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", bundle_id) or bundle_id in {".", ".."}:
        raise MotifError(f"unsafe id {bundle_id!r}: must match [A-Za-z0-9_.-]+ and not be '.' or '..'")
    d = Path(out_dir) / bundle_id
    if not d.resolve().is_relative_to(Path(out_dir).resolve()) or d.resolve() == Path(out_dir).resolve():
        raise MotifError(f"id {bundle_id!r} escapes the output directory")
    return d


def lattice_rows(lat: Lattice, header: dict, depth: int | None = None) -> dict:
    """The exported artifacts of a lattice as JSON-safe data (what ``write_lattice`` writes): ``candidates``,
    ``edges`` and ``blocked`` row lists filtered to ``depth``, and the ``termination`` record of the whole search.
    Candidate rows carry ``motif`` for a bundle of one and ``bundle`` otherwise."""
    kept = kept_candidates(lat, depth)
    cands = sorted((lat.candidates[h] for h in kept), key=lambda c: (c.depth, c.hash))
    edge_rows = sorted(({"parent": e.parent, "child": e.child, "changes": [c.to_json() for c in e.changes]}
                        for e in lat.edges if e.parent in kept and e.child in kept),
                       key=lambda r: (r["parent"], r["child"]))
    blocked_rows = sorted(
        ({"from": frm, "op": b.op, "target": b.target, "reason": b.reason, "detail": b.detail}
         for frm, b in lat.blocked if depth is None or frm in kept),
        key=lambda r: (r["from"], r["op"], r["target"], r["reason"], json.dumps(r["detail"], sort_keys=True)))
    term = {"status": lat.status, "complete": lat.status == "exhausted", "budget": header.get("budget"),
            "budget_hit": list(lat.budget_hit), "refused": lat.refused, "unexpanded_frontier": lat.unexpanded,
            "candidates": len(lat.candidates), "state_space_estimate": lat.state_space_estimate}
    term["axes"] = {n: {"status": a.status, "reached": list(a.reached), "stopped_by": list(a.stopped_by)}
                    for n, a in lat.axes.items()}
    return {"candidates": [candidate_row(c) for c in cands], "edges": edge_rows, "blocked": blocked_rows,
            "termination": term}


def write_lattice(lat: Lattice, bundle_id: str, out_dir: Path, header: dict, depth: int | None = None) -> dict[str, Path]:
    """Write the lattice files to ``out_dir/<bundle_id>`` (the motif id for a bundle of one); ``depth`` keeps only
    candidates at depth <= N in candidates.jsonl, the edges between them in edges.jsonl and the blocked moves from
    them in blocked.jsonl. termination.json always describes the whole search (see ``lattice_rows``)."""
    d = output_dir(out_dir, bundle_id)
    d.mkdir(parents=True, exist_ok=True)
    rows = lattice_rows(lat, header, depth)
    paths = {k: d / n for k, n in (("run_header", "run_header.json"), ("candidates", "candidates.jsonl"),
                                    ("edges", "edges.jsonl"), ("blocked", "blocked.jsonl"),
                                    ("termination", "termination.json"))}
    _write(paths["run_header"], json.dumps(header, sort_keys=True, indent=2) + "\n")
    _write(paths["candidates"], "".join(json_line(r) for r in rows["candidates"]))
    _write(paths["edges"], "".join(json_line(r) for r in rows["edges"]))
    _write(paths["blocked"], "".join(json_line(r) for r in rows["blocked"]))
    _write(paths["termination"], json.dumps(rows["termination"], sort_keys=True, indent=2) + "\n")
    return paths
