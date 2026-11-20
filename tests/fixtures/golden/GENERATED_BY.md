# Golden lattice outputs — provenance

`*_lift` generated **once, from unmodified HEAD**, before any Task 1 source edit (five-operators plan, Task 1,
Step 2), and permanent. `fake_full`/`real_full` were **replaced in Task 2 (operators changed)**, exactly once; see
"Task 2 replacement" below. Never regenerate these files to make a failing comparison pass; a diff is a regression.

- HEAD commit: `d4501560ec47c75c4150a71dadd29a249c2ef2a8` (`git rev-parse HEAD`, branch `feature/semantic-generalization`)
- Generated on: 2026-11-11, standalone (`PYTHONPATH=. uv run python generate_golden.py . prov.json`), not under pytest
- The only non-HEAD file used: `tests/support/fake_snomed.py` (the Step 1 test helper; works on HEAD unchanged).
  Its `FAKE_M1`/`FAKE_M2` and concept constants were checked equal to HEAD's `tests/conftest.py`
  `_FAKE_M1`/`_FAKE_M2`/constants, and its IS-A map equals HEAD's `_ISA` plus `STRUCT: {SUBST}`.
- Floor policy: `SnomedBoundaryPolicy` for every case (asserted `isinstance(ctx.floors, SnomedBoundaryPolicy)`).

| Case | Motifs | Context | Operators (patched `semgen.lattice.ALL_OPERATORS`) | HEAD call |
|---|---|---|---|---|
| `fake_full/<M1,M2>` | fake M1, M2 | `fake_hierarchy()` + `fake_boundary_policy(h)` | HEAD: `[concept_lift, attribute_removal, range_coarsening]` — **replaced in Task 2 (operators changed)**: `[concept_lift, normative_bucketing, attribute_deletion, attribute_aggregation]` | HEAD: `enumerate_lattice(m, ctx, 4, 10**9)`; Task 2: `Budget(max_depth=4, max_states=10**9)` |
| `fake_lift/<M1,M2>` | fake M1, M2 | same | `[concept_lift]` | same |
| `real_full/<M1..M4>` | `data/motifs/synthetic_motifs.json` | real RF2 + `SnomedBoundaryPolicy` | HEAD: `[concept_lift, attribute_removal, range_coarsening]` — **replaced in Task 2 (operators changed)**: `[concept_lift, normative_bucketing, attribute_deletion, attribute_aggregation]` | HEAD: `enumerate_lattice(m, ctx, 2, 10**9)`; Task 2: `Budget(max_depth=2, max_states=10**9)` |
| `real_lift/<M1..M4>` | same | same | `[concept_lift]` | same |

`head/fake_full` and `head/real_full` are byte copies of the HEAD-generated `*_full` files, kept as historical
artifacts (Task 2 replaces `fake_full`/`real_full` once; `head/` is not executed after Task 2).

## Deviation from the brief: the `sys.modules` assertion

The brief asks the script to assert that `semgen.floors`, `semgen.phecodex` and `semgen.icd10map` are not in
`sys.modules` after it runs. On unmodified HEAD that is unsatisfiable: `src/semgen/snomed_floor.py` and
`src/semgen/operators/base.py` import `FloorDecision` from `semgen.floors`, which imports `semgen.phecodex`,
`semgen.icd10map` and `semgen.sources`. The script instead replaces every PhecodeX entry point
(`PhecodeFloorPolicy.__init__`/`check_lift`, `PhecodeX.__init__`, `Icd10Map.__init__`, `load_icd10_map`) with a
tripwire that raises, so the run proves no PhecodeX policy, table or ICD-10 map was constructed or consulted; it
also asserts `tests.conftest` and `pytest` were never imported.

## Provenance recorded by the Task 1 script

```json
{
  "config_sha256": "15f1fbb497b25c6e60d336c378f38ad629aeedb3f28ae3efdda7b01c2dad1687",
  "counts": {
    "fake_full/M1": {
      "candidates": 162,
      "edges": 452,
      "status": "depth_limited"
    },
    "fake_full/M2": {
      "candidates": 67,
      "edges": 163,
      "status": "depth_limited"
    },
    "fake_lift/M1": {
      "candidates": 5,
      "edges": 5,
      "status": "exhausted"
    },
    "fake_lift/M2": {
      "candidates": 17,
      "edges": 30,
      "status": "depth_limited"
    },
    "real_full/M1": {
      "candidates": 34,
      "edges": 54,
      "status": "depth_limited"
    },
    "real_full/M2": {
      "candidates": 23,
      "edges": 31,
      "status": "depth_limited"
    },
    "real_full/M3": {
      "candidates": 33,
      "edges": 41,
      "status": "depth_limited"
    },
    "real_full/M4": {
      "candidates": 20,
      "edges": 28,
      "status": "depth_limited"
    },
    "real_lift/M1": {
      "candidates": 6,
      "edges": 6,
      "status": "depth_limited"
    },
    "real_lift/M2": {
      "candidates": 13,
      "edges": 14,
      "status": "depth_limited"
    },
    "real_lift/M3": {
      "candidates": 33,
      "edges": 41,
      "status": "depth_limited"
    },
    "real_lift/M4": {
      "candidates": 10,
      "edges": 11,
      "status": "depth_limited"
    }
  },
  "fake_provenance": {
    "characteristic_type": "inferred",
    "excluded_ancestor_roots": [
      {
        "concept_id": "900000000000000002",
        "fsn": "Substance categorized by structure (substance)",
        "reason": "Structural chemical grouping is not an accepted drug generalization boundary"
      }
    ],
    "max_descendants": 2500,
    "mode": "snomed_boundary",
    "semantic_tag_rule": "parent must keep the child's FSN semantic tag",
    "snomed_edition": "TEST",
    "snomed_release": "TEST",
    "status": "DRAFT \u2014 computational heuristic, not clinically validated"
  },
  "fake_release": "TEST",
  "files": [
    "tests/fixtures/golden/fake_full/M1/candidates.jsonl",
    "tests/fixtures/golden/fake_full/M1/edges.jsonl",
    "tests/fixtures/golden/fake_full/M2/candidates.jsonl",
    "tests/fixtures/golden/fake_full/M2/edges.jsonl",
    "tests/fixtures/golden/fake_lift/M1/candidates.jsonl",
    "tests/fixtures/golden/fake_lift/M1/edges.jsonl",
    "tests/fixtures/golden/fake_lift/M2/candidates.jsonl",
    "tests/fixtures/golden/fake_lift/M2/edges.jsonl",
    "tests/fixtures/golden/real_full/M1/candidates.jsonl",
    "tests/fixtures/golden/real_full/M1/edges.jsonl",
    "tests/fixtures/golden/real_full/M2/candidates.jsonl",
    "tests/fixtures/golden/real_full/M2/edges.jsonl",
    "tests/fixtures/golden/real_full/M3/candidates.jsonl",
    "tests/fixtures/golden/real_full/M3/edges.jsonl",
    "tests/fixtures/golden/real_full/M4/candidates.jsonl",
    "tests/fixtures/golden/real_full/M4/edges.jsonl",
    "tests/fixtures/golden/real_lift/M1/candidates.jsonl",
    "tests/fixtures/golden/real_lift/M1/edges.jsonl",
    "tests/fixtures/golden/real_lift/M2/candidates.jsonl",
    "tests/fixtures/golden/real_lift/M2/edges.jsonl",
    "tests/fixtures/golden/real_lift/M3/candidates.jsonl",
    "tests/fixtures/golden/real_lift/M3/edges.jsonl",
    "tests/fixtures/golden/real_lift/M4/candidates.jsonl",
    "tests/fixtures/golden/real_lift/M4/edges.jsonl"
  ],
  "head": "d4501560ec47c75c4150a71dadd29a249c2ef2a8",
  "real_edition": "International",
  "real_provenance": {
    "characteristic_type": "inferred",
    "excluded_ancestor_roots": [
      {
        "concept_id": "312413002",
        "fsn": "Substance categorized by structure (substance)",
        "reason": "Structural chemical grouping is not an accepted drug generalization boundary"
      }
    ],
    "max_descendants": 2500,
    "mode": "snomed_boundary",
    "semantic_tag_rule": "parent must keep the child's FSN semantic tag",
    "snomed_edition": "International",
    "snomed_release": "20260201",
    "status": "DRAFT \u2014 computational heuristic, not clinically validated"
  },
  "real_release": "20260201",
  "real_rf2_dir": "$SEMGEN_RF2_DIR (SnomedCT_InternationalRF2_PRODUCTION_20260201T120000Z/Snapshot/Terminology)",
  "snomed_boundary_config": {
    "characteristic_type": "inferred",
    "excluded_ancestor_roots": [
      {
        "fsn": "Substance categorized by structure (substance)",
        "reason": "Structural chemical grouping is not an accepted drug generalization boundary"
      }
    ],
    "max_descendants": 2500
  }
}
```

## Task 1 script (full text)

```python
"""One-off golden generator for Task 1 (run from the repo root against unmodified HEAD, NOT under pytest).

    PYTHONPATH=. uv run python generate_golden.py <repo_root> <provenance_json_out>

Writes tests/fixtures/golden/<case>/<motif>/{candidates,edges}.jsonl via HEAD's write_lattice.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import semgen.lattice as lattice_mod
from semgen.config import load_config
from semgen.export import write_lattice
from semgen.lattice import enumerate_lattice
from semgen.motif_io import load_motifs, parse_motif
from semgen.operators.attribute_removal import attribute_removal
from semgen.operators.base import GenContext
from semgen.operators.concept_lift import concept_lift
from semgen.operators.range_coarsening import range_coarsening
from semgen.snomed import default_rf2_dir, load_rf2
from semgen.snomed_floor import SnomedBoundaryPolicy
from tests.support.fake_snomed import CONFIG_PATH, FAKE_M1, FAKE_M2, FAKE_RELEASE, fake_boundary_policy, fake_hierarchy

# At HEAD snomed_floor.py imports FloorDecision from semgen.floors, which pulls in semgen.phecodex and
# semgen.icd10map, so those modules ARE in sys.modules here (the brief's "not in sys.modules" assertion is
# unsatisfiable on unmodified HEAD). Instead every PhecodeX entry point is replaced by a tripwire, so any use
# of the PhecodeX policy, the PhecodeX tables or the ICD-10 map during generation aborts the run.
import semgen.floors as _floors  # noqa: E402
import semgen.icd10map as _icd  # noqa: E402
import semgen.phecodex as _px  # noqa: E402


def _tripwire(*_a, **_k):
    raise AssertionError("PhecodeX code path used during golden generation")


_floors.PhecodeFloorPolicy.__init__ = _tripwire
_floors.PhecodeFloorPolicy.check_lift = _tripwire
_px.PhecodeX.__init__ = _tripwire
_icd.Icd10Map.__init__ = _tripwire
_icd.load_icd10_map = _tripwire

repo = Path(sys.argv[1]).resolve()
prov_out = Path(sys.argv[2])
golden = repo / "tests" / "fixtures" / "golden"
FULL = [concept_lift, attribute_removal, range_coarsening]
LIFT = [concept_lift]

cfg = load_config(CONFIG_PATH)
fh = fake_hierarchy()
fctx = GenContext(fh, cfg, fake_boundary_policy(fh))
rf2 = default_rf2_dir()
rh = load_rf2(rf2)
rctx = GenContext(rh, cfg, SnomedBoundaryPolicy(rh, cfg.floor_policy.snomed_boundary))
for c in (fctx, rctx):
    assert isinstance(c.floors, SnomedBoundaryPolicy), type(c.floors)

fake_motifs = [parse_motif(copy.deepcopy(FAKE_M1), None), parse_motif(copy.deepcopy(FAKE_M2), None)]
real_motifs = load_motifs(repo / "data" / "motifs" / "synthetic_motifs.json", rh)
assert [m.motif_id for m in real_motifs] == ["M1", "M2", "M3", "M4"]

cases = [("fake_full", fake_motifs, fctx, FULL, 4), ("fake_lift", fake_motifs, fctx, LIFT, 4),
         ("real_full", real_motifs, rctx, FULL, 2), ("real_lift", real_motifs, rctx, LIFT, 2)]
written = []
counts = {}
for case, motifs, ctx, ops, depth in cases:
    lattice_mod.ALL_OPERATORS = ops   # neighbors() reads the module-level name
    for m in motifs:
        lat = enumerate_lattice(m, ctx, depth, 10**9)
        with tempfile.TemporaryDirectory() as tmp:
            write_lattice(lat, m.motif_id, Path(tmp), {})
            dst = golden / case / m.motif_id
            dst.mkdir(parents=True, exist_ok=True)
            for name in ("candidates.jsonl", "edges.jsonl"):
                shutil.copyfile(Path(tmp) / m.motif_id / name, dst / name)
                written.append(str((dst / name).relative_to(repo)))
        counts[f"{case}/{m.motif_id}"] = {"candidates": len(lat.candidates), "edges": len(lat.edges),
                                          "status": lat.status}

assert len(written) == 24, len(written)
assert len((golden / "fake_lift" / "M1" / "candidates.jsonl").read_text().splitlines()) > 1, "no lifts occurred"
assert "tests.conftest" not in sys.modules and "pytest" not in sys.modules

prov = {
    "head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True,
                           check=True).stdout.strip(),
    "config_sha256": hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest(),
    "snomed_boundary_config": cfg.floor_policy.snomed_boundary.model_dump(mode="json"),
    "fake_provenance": fctx.floors.provenance,
    "fake_release": FAKE_RELEASE,
    "real_provenance": rctx.floors.provenance,
    "real_release": rh.release, "real_edition": rh.edition, "real_rf2_dir": str(rf2),
    "counts": counts, "files": written,
}
prov_out.write_text(json.dumps(prov, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(counts, indent=1))
```

## Task 2 replacement of `fake_full` / `real_full` (operators changed)

Replaced in Task 2 (operators changed): `attribute_removal` and `range_coarsening` were deleted (D3) and the
per-motif operator list became `[concept_lift, normative_bucketing, attribute_deletion, attribute_aggregation]`.
Only `fake_full/*` and `real_full/*` were written, once. The `*_lift` files were **not** regenerated: the script
recomputed them and asserted byte identity (and they were sha256-checked before/after), and `head/` was not
touched. Run headers are not part of the golden files.

- Base: HEAD `d4501560ec47c75c4150a71dadd29a249c2ef2a8` plus the uncommitted Task 1 + Task 2 working tree (no commits, per user).
- Generated on: 2026-11-11, standalone, not under pytest:
  `PYTHONPATH=. uv run python generate_golden_full_task2.py . prov_task2.json` (run from the repo root; the
  script lived in the session scratchpad and is reproduced in full below).
- Contexts: `GenContext(h, cfg, policy)` with `refranges=None`, `subject=None` (bare motifs). No Mayo data was
  read; no valued node in these motifs has a test identity, so bucketing and A1 make no moves here (blocked
  rows are not part of the golden files).
- The test `tests/test_golden.py` patches `semgen.lattice.ALL_OPERATORS` with the same list for `*_full`.

### Provenance recorded by the Task 2 script

```json
{
  "attribute_definitions_sha256": "569342e730807649cb1e278880c26db499a07c8a6e62a212eb0136b3b9a08826",
  "config_sha256": "b51d373f98df329d8d27ed4849faaed79479ed5f693520c2f250d80f18e4d5cc",
  "counts": {
    "fake_full/M1": {
      "candidates": 94,
      "edges": 262,
      "ops": [
        "attribute_deletion",
        "concept_lift"
      ],
      "status": "budget_limited"
    },
    "fake_full/M2": {
      "candidates": 121,
      "edges": 342,
      "ops": [
        "attribute_deletion",
        "concept_lift"
      ],
      "status": "budget_limited"
    },
    "fake_lift/M1": {
      "candidates": 5,
      "edges": 5,
      "ops": [
        "concept_lift"
      ],
      "status": "exhausted"
    },
    "fake_lift/M2": {
      "candidates": 17,
      "edges": 30,
      "ops": [
        "concept_lift"
      ],
      "status": "budget_limited"
    },
    "real_full/M1": {
      "candidates": 30,
      "edges": 49,
      "ops": [
        "attribute_deletion",
        "concept_lift"
      ],
      "status": "budget_limited"
    },
    "real_full/M2": {
      "candidates": 33,
      "edges": 51,
      "ops": [
        "attribute_deletion",
        "concept_lift"
      ],
      "status": "budget_limited"
    },
    "real_full/M3": {
      "candidates": 48,
      "edges": 70,
      "ops": [
        "attribute_deletion",
        "concept_lift"
      ],
      "status": "budget_limited"
    },
    "real_full/M4": {
      "candidates": 30,
      "edges": 48,
      "ops": [
        "attribute_deletion",
        "concept_lift"
      ],
      "status": "budget_limited"
    },
    "real_lift/M1": {
      "candidates": 6,
      "edges": 6,
      "ops": [
        "concept_lift"
      ],
      "status": "budget_limited"
    },
    "real_lift/M2": {
      "candidates": 13,
      "edges": 14,
      "ops": [
        "concept_lift"
      ],
      "status": "budget_limited"
    },
    "real_lift/M3": {
      "candidates": 33,
      "edges": 41,
      "ops": [
        "concept_lift"
      ],
      "status": "budget_limited"
    },
    "real_lift/M4": {
      "candidates": 10,
      "edges": 11,
      "ops": [
        "concept_lift"
      ],
      "status": "budget_limited"
    }
  },
  "fake_provenance": {
    "characteristic_type": "inferred",
    "excluded_ancestor_roots": [
      {
        "concept_id": "900000000000000002",
        "fsn": "Substance categorized by structure (substance)",
        "reason": "Structural chemical grouping is not an accepted drug generalization boundary"
      }
    ],
    "max_descendants": 2500,
    "mode": "snomed_boundary",
    "semantic_tag_rule": "parent must keep the child's FSN semantic tag",
    "snomed_edition": "TEST",
    "snomed_release": "TEST",
    "status": "DRAFT \u2014 computational heuristic, not clinically validated"
  },
  "fake_release": "TEST",
  "head": "d4501560ec47c75c4150a71dadd29a249c2ef2a8",
  "lift_checked_byte_identical": [
    "tests/fixtures/golden/fake_lift/M1/candidates.jsonl",
    "tests/fixtures/golden/fake_lift/M1/edges.jsonl",
    "tests/fixtures/golden/fake_lift/M2/candidates.jsonl",
    "tests/fixtures/golden/fake_lift/M2/edges.jsonl",
    "tests/fixtures/golden/real_lift/M1/candidates.jsonl",
    "tests/fixtures/golden/real_lift/M1/edges.jsonl",
    "tests/fixtures/golden/real_lift/M2/candidates.jsonl",
    "tests/fixtures/golden/real_lift/M2/edges.jsonl",
    "tests/fixtures/golden/real_lift/M3/candidates.jsonl",
    "tests/fixtures/golden/real_lift/M3/edges.jsonl",
    "tests/fixtures/golden/real_lift/M4/candidates.jsonl",
    "tests/fixtures/golden/real_lift/M4/edges.jsonl"
  ],
  "mayo": "not consulted: refranges=None in both contexts; every valued node lacks a test identity",
  "operators_full": [
    "concept_lift",
    "normative_bucketing",
    "attribute_deletion",
    "attribute_aggregation"
  ],
  "real_edition": "International",
  "real_provenance": {
    "characteristic_type": "inferred",
    "excluded_ancestor_roots": [
      {
        "concept_id": "312413002",
        "fsn": "Substance categorized by structure (substance)",
        "reason": "Structural chemical grouping is not an accepted drug generalization boundary"
      }
    ],
    "max_descendants": 2500,
    "mode": "snomed_boundary",
    "semantic_tag_rule": "parent must keep the child's FSN semantic tag",
    "snomed_edition": "International",
    "snomed_release": "20260201",
    "status": "DRAFT \u2014 computational heuristic, not clinically validated"
  },
  "real_release": "20260201",
  "real_rf2_dir": "$SEMGEN_RF2_DIR (SnomedCT_InternationalRF2_PRODUCTION_20260201T120000Z/Snapshot/Terminology)",
  "snomed_boundary_config": {
    "characteristic_type": "inferred",
    "excluded_ancestor_roots": [
      {
        "fsn": "Substance categorized by structure (substance)",
        "reason": "Structural chemical grouping is not an accepted drug generalization boundary"
      }
    ],
    "max_descendants": 2500
  },
  "tree": "HEAD plus the uncommitted Task 1 and Task 2 working-tree changes (no commits, per user)",
  "written": [
    "tests/fixtures/golden/fake_full/M1/candidates.jsonl",
    "tests/fixtures/golden/fake_full/M1/edges.jsonl",
    "tests/fixtures/golden/fake_full/M2/candidates.jsonl",
    "tests/fixtures/golden/fake_full/M2/edges.jsonl",
    "tests/fixtures/golden/real_full/M1/candidates.jsonl",
    "tests/fixtures/golden/real_full/M1/edges.jsonl",
    "tests/fixtures/golden/real_full/M2/candidates.jsonl",
    "tests/fixtures/golden/real_full/M2/edges.jsonl",
    "tests/fixtures/golden/real_full/M3/candidates.jsonl",
    "tests/fixtures/golden/real_full/M3/edges.jsonl",
    "tests/fixtures/golden/real_full/M4/candidates.jsonl",
    "tests/fixtures/golden/real_full/M4/edges.jsonl"
  ]
}
```

### Task 2 script (full text)

```python
"""One-off Task 2 golden generator: REPLACES fake_full/real_full once (operators changed); NOT under pytest.

    PYTHONPATH=. uv run python <this script> <repo_root> <provenance_json_out>

Writes tests/fixtures/golden/{fake_full,real_full}/<motif>/{candidates,edges}.jsonl with the Task 2 per-motif
operator list. The *_lift files are only READ: the script recomputes them and asserts they are byte-identical.
tests/fixtures/golden/head/ is not touched.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import semgen.lattice as lattice_mod
from semgen.config import load_config
from semgen.export import write_lattice
from semgen.lattice import Budget, enumerate_lattice
from semgen.motif_io import load_motifs, parse_motif
from semgen.operators import ALL_OPERATORS
from semgen.operators.attribute_aggregation import attribute_aggregation
from semgen.operators.attribute_deletion import attribute_deletion
from semgen.operators.base import GenContext
from semgen.operators.concept_lift import concept_lift
from semgen.operators.normative_bucketing import normative_bucketing
from semgen.snomed import default_rf2_dir, load_rf2
from semgen.snomed_floor import SnomedBoundaryPolicy
from tests.support.fake_snomed import CONFIG_PATH, FAKE_M1, FAKE_M2, FAKE_RELEASE, fake_boundary_policy, fake_hierarchy

repo = Path(sys.argv[1]).resolve()
prov_out = Path(sys.argv[2])
golden = repo / "tests" / "fixtures" / "golden"
FULL = [concept_lift, normative_bucketing, attribute_deletion, attribute_aggregation]
LIFT = [concept_lift]
assert FULL == ALL_OPERATORS, "the *_full list must be the production per-motif operator list"

cfg = load_config(CONFIG_PATH)
fh = fake_hierarchy()
fctx = GenContext(fh, cfg, fake_boundary_policy(fh))          # refranges=None, subject=None (bare motifs)
rf2 = default_rf2_dir()
rh = load_rf2(rf2)
rctx = GenContext(rh, cfg, SnomedBoundaryPolicy(rh, cfg.floor_policy.snomed_boundary))
for c in (fctx, rctx):
    assert isinstance(c.floors, SnomedBoundaryPolicy), type(c.floors)
    assert c.refranges is None and c.subject is None

fake_motifs = [parse_motif(copy.deepcopy(FAKE_M1), None), parse_motif(copy.deepcopy(FAKE_M2), None)]
real_motifs = load_motifs(repo / "data" / "motifs" / "synthetic_motifs.json", rh)
assert [m.motif_id for m in real_motifs] == ["M1", "M2", "M3", "M4"]

cases = [("fake_full", fake_motifs, fctx, FULL, 4), ("fake_lift", fake_motifs, fctx, LIFT, 4),
         ("real_full", real_motifs, rctx, FULL, 2), ("real_lift", real_motifs, rctx, LIFT, 2)]
written, checked, counts = [], [], {}
for case, motifs, ctx, ops, depth in cases:
    lattice_mod.ALL_OPERATORS = ops   # neighbors() reads the module-level name
    for m in motifs:
        lat = enumerate_lattice(m, ctx, Budget(max_depth=depth, max_states=10**9))
        with tempfile.TemporaryDirectory() as tmp:
            write_lattice(lat, m.motif_id, Path(tmp), {})
            dst = golden / case / m.motif_id
            for name in ("candidates.jsonl", "edges.jsonl"):
                new = (Path(tmp) / m.motif_id / name).read_bytes()
                rel = str((dst / name).relative_to(repo))
                if case.endswith("_lift"):
                    assert (dst / name).read_bytes() == new, f"{rel} drifted: a regression, not regenerated"
                    checked.append(rel)
                else:
                    dst.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(Path(tmp) / m.motif_id / name, dst / name)
                    written.append(rel)
        counts[f"{case}/{m.motif_id}"] = {"candidates": len(lat.candidates), "edges": len(lat.edges),
                                          "status": lat.status,
                                          "ops": sorted({c.op for e in lat.edges for c in e.changes})}

assert len(written) == 12 and len(checked) == 12, (len(written), len(checked))
assert "tests.conftest" not in sys.modules and "pytest" not in sys.modules
for gone in ("semgen.floors", "semgen.phecodex", "semgen.icd10map", "semgen.sources",
             "semgen.operators.attribute_removal", "semgen.operators.range_coarsening"):
    assert gone not in sys.modules, gone

prov = {
    "head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True,
                           check=True).stdout.strip(),
    "tree": "HEAD plus the uncommitted Task 1 and Task 2 working-tree changes (no commits, per user)",
    "operators_full": [op.__name__ for op in FULL],
    "config_sha256": hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest(),
    "attribute_definitions_sha256": cfg.attribute_definitions_sha256,
    "snomed_boundary_config": cfg.floor_policy.snomed_boundary.model_dump(mode="json"),
    "fake_provenance": fctx.floors.provenance,
    "fake_release": FAKE_RELEASE,
    "real_provenance": rctx.floors.provenance,
    "real_release": rh.release, "real_edition": rh.edition, "real_rf2_dir": str(rf2),
    "mayo": "not consulted: refranges=None in both contexts; every valued node lacks a test identity",
    "counts": counts, "written": written, "lift_checked_byte_identical": checked,
}
prov_out.write_text(json.dumps(prov, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(counts, indent=1))
```

## Rev 4 replacement of `*_full` (17 Nov 2026, user-approved)

`fake_full/` and `real_full/` were replaced **once more**, for design rev 4 (relevance-gated attribute deletion, A2/A3,
reference-interval bucket names). `*_lift` were **not** touched and still compare byte-identically. Generated
standalone with exactly `test_golden.py`'s calls (`OPS["full"]`, same contexts and budgets, `write_lattice`), from
the rev 4 working tree. The previous files are kept outside the repository by the session that replaced them.

Expected difference, and the only one: these contexts declare no cohort definition, so every attribute-deletion
candidate is `relevance_unknown` (blocked) and the lattices contain concept-lift moves only. No A2 move (no panel
source configured) and no A3 move (no two P-attached, non-anchor nodes with distinct codes) occurs in these motifs.

| Case | candidates before → after |
|---|---|
| fake_full/M1 | 94 → 5 |
| fake_full/M2 | 121 → 17 |
| real_full/M1 | 30 → 6 |
| real_full/M2 | 33 → 13 |
| real_full/M3 | 48 → 33 |
| real_full/M4 | 30 → 10 |

## SNOMED-only concept lift replacement (2026-11-20)

`fake_full`, `fake_lift`, `real_full`, `real_lift` were **regenerated once** when concept lift was rebuilt to decide
every step from the SNOMED CT release alone (`semgen.lift`, replacing `snomed_boundary` / `dynamic_boundary`). The
methodology change is intended: the old goldens encode the removed breadth-ceiling floor. Generated with exactly the
`tests/test_golden.py` code path (`_fake()` / `_real()`, same operators and budgets, `write_lattice`); fake cases use
`tests/support/fake_snomed.py` with its synthetic concept model and the added `FIND` top-level concept. `head/` is
unchanged. From here on, a diff is again a regression.
