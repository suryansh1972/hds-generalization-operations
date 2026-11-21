# semgen

**semgen makes clinical patterns more general, and proves every step.**

You give it a small graph describing a kind of patient (a *motif*), for example *"a patient with type 2 diabetes,
taking metformin, with an eGFR of 42"*. semgen produces every version of that pattern that is **provably more
general**, using SNOMED CT as the concept hierarchy:

```
type 2 diabetes  ──►  diabetes mellitus  ──►  …          concept lift along SNOMED CT IS-A
eGFR 42          ──►  eGFR below reference interval      bucketing against a pinned reference range
dated facts      ──►  undated facts                      deleting constraints the cohort allows
```

The results form a **lattice**: the original pattern at the root, broader patterns above it, and every edge one
generalization step with its evidence. Each candidate is checked by an independent proof that it matches every
patient the original matches, so nothing unproven reaches the output. The same input always gives byte-identical
output.

Use it as a **command-line tool**, a **Python library**, or an **HTTP API**.

> All clinical configuration is **DRAFT, not clinically approved**. semgen generates and checks patterns; it does
> no support counting, utility scoring or disclosure control.

---

## Contents

1. [Requirements](#1-requirements)
2. [Setup](#2-setup)
3. [Quick start](#3-quick-start)
4. [Writing input motifs](#4-writing-input-motifs)
5. [Command line](#5-command-line)
6. [Python library](#6-python-library)
7. [HTTP API](#7-http-api)
8. [Adding custom operators](#8-adding-custom-operators)
9. [Settings reference](#9-settings-reference)
10. [Running the tests](#10-running-the-tests)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Requirements

| | |
|---|---|
| Python | 3.12 or newer |
| SNOMED CT | an **International Edition RF2 release** (licensed, see [step 2.2](#22-get-a-snomed-ct-release)) |
| Disk / memory | room for the unzipped release plus a cache of a few hundred MB; enough RAM to hold a full release |
| Optional | [uv](https://docs.astral.sh/uv/), recommended for development |

## 2. Setup

### 2.1 Install semgen

```bash
git clone https://github.com/suryansh1972/hds-generalization-operations.git
cd hds-generalization-operations
```

Then pick one:

```bash
# A) with uv (recommended): creates .venv with everything, including the API and test tools
uv sync --group dev
source .venv/bin/activate

# B) with pip
python -m venv .venv && source .venv/bin/activate
pip install .            # library + `semgen` command
pip install ".[api]"     # ... plus the HTTP API (Litestar, uvicorn)
```

Check that it worked:

```bash
semgen --help
```

### 2.2 Get a SNOMED CT release

semgen needs a SNOMED CT **International Edition RF2** release. It is licensed data, so it is **not** included in
this repository.

1. Get a licence and download the release from [SNOMED International MLDS](https://mlds.ihtsdotools.org/) or your
   country's National Release Centre (free in member countries).
2. Unzip it anywhere **outside** this repository, for example
   `~/data/SnomedCT_InternationalRF2_PRODUCTION_20260201T120000Z/`.

semgen reads the `Snapshot/Terminology` files and the MRCM refsets in `Snapshot/Refset/Metadata`.

### 2.3 Tell semgen where the release is

Copy the example settings file and set the path:

```bash
cp .env.example .env
```

```bash
# .env
SEMGEN_RF2_DIR=~/data/SnomedCT_InternationalRF2_PRODUCTION_20260201T120000Z
```

Load it into your shell. semgen reads environment variables; it does not read `.env` by itself:

```bash
set -a; source .env; set +a
```

`SEMGEN_RF2_DIR` may point at the release folder, its `Snapshot` folder, or `Snapshot/Terminology`. You can also
pass `--rf2 PATH` to any command instead.

### 2.4 Optional evidence files

Two operators need extra reference data. Without it they **block** (and report why); everything else still works.

| Variable | File | Enables |
|---|---|---|
| `SEMGEN_UCUM_ESSENCE` | `ucum-essence.xml` (UCUM essence 1.9) | merging repeated lab results (unit validation) |
| `SEMGEN_MAYO_DB` | Mayo `refrange.sqlite` | bucketing values against reference ranges |
| `SEMGEN_MAYO_TEST_MAP` | reviewed Mayo test-map CSV | mapping lab tests to Mayo ranges |

Each file is pinned by SHA-256 in the config, so a different version is rejected with a clear error.

### 2.5 First run

The first command that loads the release parses it and caches the result in `~/.cache/semgen`. This is slow once;
later runs start quickly.

```bash
semgen lift 44054006          # explore the generalizations of "Type 2 diabetes mellitus"
```

If this prints JSON, setup is complete.

## 3. Quick start

Generalize the four example motifs that ship with the repository:

```bash
semgen run --motifs data/motifs/synthetic_motifs.json --out runs/example --max-depth-budget 2
```

semgen prints one line per motif:

```
M1 depth=all candidates=… edges=… blocked=… status=…
```

Each motif then has a folder `runs/example/<motif_id>/`:

| File | What's in it |
|---|---|
| `candidates.jsonl` | every generalized pattern: `hash`, `depth` (steps from the original), the pattern itself |
| `edges.jsonl` | every step `parent → child`: what changed and the evidence for it |
| `blocked.jsonl` | every step that was **not** allowed, and why (e.g. `carries_value`, `mayo_unavailable`) |
| `termination.json` | whether the search finished (`exhausted`) or stopped at a budget (`budget_limited`) |
| `run_header.json` | provenance: SNOMED CT release, config and data hashes, budget, semgen version |

`exhausted` means every generalization was found. `budget_limited` means the search stopped at your budget and more
may exist.

## 4. Writing input motifs

A motif is JSON: one **patient** node `P`, clinical nodes connected to it, and one node marked as the **anchor**
(the condition the pattern is about).

```json
{
  "motif_id": "DM1",
  "anchor": "n1",
  "nodes": [
    {"id": "P",  "type": "Patient",    "role": "patient"},
    {"id": "n1", "type": "Disorder",   "code": "44054006",  "polarity": "present", "role": "anchor"},
    {"id": "n2", "type": "Disorder",   "code": "46635009",  "polarity": "absent",  "role": "modifier"},
    {"id": "n3", "type": "Substance",  "code": "372567009", "polarity": "present", "role": "exposure"},
    {"id": "n4", "type": "Observable", "code": "80274001",  "polarity": "present", "role": "outcome",
     "value": {"interval": [42, 42], "unit": "mL/min/{1.73_m2}"}}
  ],
  "edges": [
    {"s": "P",  "t": "n1", "rel": "has_condition",     "prov": "asserted"},
    {"s": "P",  "t": "n2", "rel": "has_condition",     "prov": "asserted"},
    {"s": "P",  "t": "n3", "rel": "administered_drug", "prov": "asserted"},
    {"s": "P",  "t": "n4", "rel": "has_measurement",   "prov": "asserted"},
    {"s": "n3", "t": "n4", "rel": "followed_by",       "prov": "asserted",
     "time": {"window": [180, 180], "unit": "d"}}
  ]
}
```

| Field | Meaning |
|---|---|
| `code` | a SNOMED CT concept id; or leave it out and give `label` as the exact FSN, and semgen looks the code up |
| `polarity` | `present`, or `absent` for "the patient does **not** have this" (absent facts are never changed) |
| `role` | `patient`, `anchor`, `exposure`, `outcome`, `modifier`, or `context` (knowledge-graph enrichment, never generalized) |
| `value` | a measurement `{"interval": [lo, hi], "unit": "..."}`; a point value has `lo == hi` |
| `attrs`, `dates` | extra constraints, e.g. `{"age_at_dx": {"interval": [67, 67], "unit": "a"}}`, `{"onset": "2020-01-01"}` |
| `prov` (edges) | `asserted` (a clinical fact) or `context` (a knowledge-graph link, with an optional `bpn_score`) |

A file can hold **one motif**, a **list** of motifs, `{"motifs": [...]}`, or **bundles**: several motifs of the same
patient combined with `"semantics": "all"` (AND) or `"any"` (OR). Every motif of a bundle shares the patient: a
patient graph has exactly one Patient fact, and each motif's `P` node is matched at that same fact (so an AND bundle is
never satisfied by different motifs matching different patients).

```json
{"bundles": [{
  "bundle_id": "B1", "semantics": "all", "anchor_motif": "DM1",
  "subject": {"sex": "female", "age_days": 20000},
  "cohort_definition": {"id": "c1", "version": "1", "source": "study protocol",
                        "constraints": [{"motif": "DM1", "target": "n4", "field": "value",
                                         "necessity": "relaxable"}]},
  "motifs": [ {"motif_id": "DM1", "...": "..."}, {"motif_id": "DM2", "...": "..."} ]
}]}
```

- `subject` is needed for sex- or age-specific reference ranges.
- `cohort_definition` says which constraints may be **deleted** (`relaxable`) and which must stay (`required`).
  Fields are `value`, `attrs.<name>` or `dates.<name>`. Anything not declared is never deleted.

Check a file before running it:

```bash
semgen validate --motifs my_motifs.json
```

## 5. Command line

```bash
semgen run          --motifs FILE --out DIR [budget options] [--depth N] [--progress]
semgen validate     --motifs FILE
semgen lift CODE    [--parent CODE] [--max-transitions N]
semgen floor-report --motifs FILE [--out report.tsv]
semgen serve        [--host 127.0.0.1] [--port 8000]
```

Every command accepts `--rf2 PATH` and `--config PATH` (defaults: `SEMGEN_RF2_DIR` and the packaged config).
`python -m semgen …` works the same way.

### `run`: generalize motifs

Without a budget the search is unbounded, and large motifs can take a long time. Set one:

| Option | Effect |
|---|---|
| `--max-depth-budget N` | do not expand beyond N steps from the original (the most useful one) |
| `--max-states N` | store at most N patterns |
| `--time-budget SECONDS` | stop after this long (the output is then not byte-reproducible) |
| `--depth N` | only **write** candidates up to depth N (does not limit the search) |
| `--progress` | stream candidates to `progress.jsonl` while running |

### `lift`: inspect one SNOMED CT concept

```bash
semgen lift 44054006                    # every allowed ancestor, every rule decision, where each branch stops
semgen lift 44054006 --parent 73211009  # one step only, with the rules' evidence and an independent re-check
```

### `floor-report`

A TSV of every concept-lift decision for the concepts in your motifs, for review.

**Exit codes:** `0` ok · `1` bad input, config or missing data · `2` wrong command-line usage · `3` internal
invariant violated (please report it).

## 6. Python library

```python
from semgen import Budget, SemgenEngine

# Load once. Reads the SEMGEN_* variables; or pass rf2_dir=..., config_path=...
engine = SemgenEngine.from_settings()

motif = {...}                                   # a motif dict as in section 4 (or a list / bundle file's content)

engine.parse(motif)                             # validate; raises MotifError with a clear message
result = engine.generalize(motif, Budget(max_depth=2))

result.status                                   # "exhausted" or "budget_limited"
result.summary()                                # {"candidates": ..., "edges": ..., "blocked": ..., ...}
data = result.to_json()                         # candidates, edges, blocked steps, termination, run header
result.write("runs/")                           # the same files `semgen run` writes

for row in data["candidates"]:
    print(row["depth"], row["hash"])
```

Other operations:

```python
engine.verify(specific_motif, general_motif)    # is general_motif provably more general? -> {"ok": ..., "reason": ...}
engine.check_lift("44054006", "73211009")       # one concept step with its evidence
engine.inspect_lift("44054006")                 # all allowed ancestors of a concept
engine.concept("44054006")                      # active? name? parents?
engine.provenance()                             # release, config hashes, operators in use
```

`Budget(max_states=..., max_depth=..., seconds=...)`: any limit you leave out is unbounded. One engine can be shared
by many threads, so build it once when your application starts.

## 7. HTTP API

Install the `api` extra (`pip install ".[api]"`; `uv sync --group dev` already includes it), then start the server:

```bash
semgen serve --port 8000
```

The server starts at once and loads SNOMED CT in the background. `GET /ready` returns `200` when it is ready.
Interactive docs: **http://localhost:8000/schema/swagger**.

### Example session

```bash
# 1. wait until ready
curl -s localhost:8000/ready

# 2. validate input
curl -s localhost:8000/v1/validate -H 'content-type: application/json' \
     -d "{\"input\": $(cat my_motif.json)}"

# 3. generalize, waiting up to 30 s for the answer
curl -s 'localhost:8000/v1/generalize?wait=30' -H 'content-type: application/json' \
     -d "{\"input\": $(cat my_motif.json), \"budget\": {\"max_depth\": 2}}"
#    -> {"job_id": "3f2c…", "status": "succeeded", "summary": {...}}

# 4. fetch the full result (optionally only up to a depth)
curl -s localhost:8000/v1/jobs/<job_id>/result
curl -s 'localhost:8000/v1/jobs/<job_id>/result?depth=1'

# 5. inspect a concept
curl -s localhost:8000/v1/concepts/44054006/lift
```

Without `?wait`, `/v1/generalize` answers `202` with a `job_id` straight away; poll `GET /v1/jobs/<job_id>` until
`status` is `succeeded` or `failed`.

### Endpoints

| Method and path | What it does |
|---|---|
| `GET /health` | the server is up |
| `GET /ready` | `200` when SNOMED CT is loaded; `503` while loading or if loading failed (with the error) |
| `POST /v1/validate` | validate motifs or bundles: `{"input": ...}` |
| `POST /v1/generalize` | start a run: `{"input": <one motif or bundle>, "budget": {...}, "climb": true}` |
| `GET /v1/jobs` · `GET /v1/jobs/<id>` | all jobs / one job's status and summary |
| `GET /v1/jobs/<id>/result` | the full lattice; `?depth=N` to filter |
| `POST /v1/verify` | `{"specific": ..., "general": ...}`: is `general` provably more general? |
| `GET /v1/concepts/<code>` | concept details |
| `GET /v1/concepts/<code>/lift` | all allowed generalizations of a concept |
| `GET /v1/concepts/<code>/lift/<parent>` | one step with its evidence |
| `GET /v1/config` · `GET /v1/provenance` | active configuration, limits, data hashes |

### Good to know

- **Every API run has a budget.** Requests are capped at the server limits (default 20 000 states and 120 s); a
  request without a budget gets those limits.
- **Results are kept in memory** until the server restarts (beyond 100 finished jobs, the oldest are dropped).
- **There is no authentication.** Run it on a trusted network or behind your own gateway.
- **To embed the app** in your own ASGI server:

  ```python
  from semgen.api import ApiLimits, create_app

  app = create_app(limits=ApiLimits(max_states=50_000, seconds=300, workers=2))
  # then: uvicorn mymodule:app
  ```

## 8. Adding custom operators

An *operator* proposes generalization steps. You can add your own without changing semgen: write a function
`(motif, ctx) -> OperatorResult` and add it to the engine's operator set.

```python
from semgen import ChangeRecord, Move, OperatorResult

def widen_point_values(motif, ctx):
    """Replace a point value v by the interval [0.9 v, 1.1 v] (a hypothetical example operator)."""
    moves = []
    for n in sorted(motif.nodes, key=lambda n: n.id):
        v = n.value
        if n.polarity == "present" and v is not None and v.lo is not None and v.lo == v.hi and v.lo > 0:
            wide = v.model_copy(update={"lo": v.lo * 0.9, "hi": v.hi * 1.1})
            child = motif.replace_node(n.model_copy(update={"value": wide}))
            moves.append(Move(child, ChangeRecord("widen_point_values", n.id, "value",
                                                  v.to_json(), wide.to_json(), {"factor": 0.1})))
    return OperatorResult(moves)

ops = engine.operators.with_operator(widen_point_values)        # or .with_operator(op, before="attribute_deletion")
custom = engine.with_operators(ops)                             # same loaded release, new operator set
```

```python
custom.generalize(motif, Budget(max_depth=2))
engine.with_operators(engine.operators.only("concept_lift"))    # run only some built-in operators
engine.operators.names                                          # what is in the set
```

**Safety:** every step from any operator, yours included, is still checked by the policy guard and the independent
proof. A step that is not provably more general raises an error instead of entering the results.

Built-in operators: `concept_lift`, `normative_bucketing`, `attribute_deletion` and `attribute_aggregation`
(per motif), and `motif_deletion` (per bundle).

## 9. Settings reference

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `SEMGEN_RF2_DIR` | **yes** (or `--rf2`) | none | SNOMED CT RF2 release folder |
| `SEMGEN_CACHE_DIR` | no | `~/.cache/semgen` | where the parsed release is cached |
| `SEMGEN_CONFIG` | no | the packaged config | an alternative generalization config YAML |
| `SEMGEN_UCUM_ESSENCE` | no | none | UCUM essence file (lab-result merging) |
| `SEMGEN_MAYO_DB` | no | none | Mayo reference-range database (value bucketing) |
| `SEMGEN_MAYO_TEST_MAP` | no | none | Mayo test-map CSV |

In Python you can pass the same settings explicitly:

```python
from semgen import SemgenEngine, Settings

engine = SemgenEngine.from_settings(Settings(rf2_dir="/data/snomed", cache_dir="/tmp/semgen-cache"))
```

**Never commit** SNOMED CT files, caches, reference databases or patient data. `.gitignore` already excludes them.

## 10. Running the tests

```bash
uv run pytest                    # everything that can run on this machine
uv run pytest -m "not snomed"    # synthetic data only: fast, no SNOMED CT needed (this is what CI runs)
uv run pytest -rs                # also show why tests were skipped
```

Tests that need the real SNOMED CT release run only when `SEMGEN_RF2_DIR` is set; otherwise they are skipped.

Lint, type check and build:

```bash
uv run ruff check src tests
uv run mypy
uv build                         # wheel and sdist into dist/
```

## 11. Troubleshooting

| Problem | Fix |
|---|---|
| `error: no SNOMED CT RF2 release configured` | set `SEMGEN_RF2_DIR` ([step 2.3](#23-tell-semgen-where-the-release-is)) or pass `--rf2` |
| `expected exactly one sct2_Concept_Snapshot_*.txt` | `SEMGEN_RF2_DIR` points at the wrong folder; use the unzipped release folder |
| The first run is slow | normal: the release is parsed once and cached, later runs are fast |
| `... has sha256 ..., expected ...` | the UCUM or Mayo file is a different version from the one the config pins |
| Every bucketing step is blocked `mayo_unavailable` | set `SEMGEN_MAYO_DB` (optional, see [step 2.4](#24-optional-evidence-files)) |
| A run never finishes | add a budget, e.g. `--max-depth-budget 2` |
| `semgen serve` says it needs the `api` extra | `pip install ".[api]"` |
| `/ready` returns `503` with `failed` | read its `error` field; usually the RF2 path is wrong |
| `unknown_concept` in `blocked.jsonl` | the code is not an active concept in your SNOMED CT release |
