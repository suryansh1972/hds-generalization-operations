# semgen

semgen takes a small clinical graph pattern (a **motif**: a patient node, coded clinical facts, values, dates,
edges) and enumerates every *provably more general* version of it as a lattice, using SNOMED CT as the concept
hierarchy. Every candidate is checked by an independent order proof (it matches every patient the original
matches) and a policy guard; nothing unproven reaches the output, and the same inputs give byte-identical output.

semgen does **no support counting, no utility scoring and no disclosure control**, and it makes **no BioPathNet
calls**. It generates, checks and exports generalized motifs. All clinical configuration is **DRAFT — not
clinically approved**.

It is usable three ways, all over the same engine:

| | |
|---|---|
| Python library | `from semgen import SemgenEngine` |
| CLI | `semgen run / validate / lift / floor-report / serve` |
| HTTP API | Litestar app, `semgen serve` or `semgen.api.create_app()` (optional `api` extra) |

## Contents

[Install](#install) · [External data](#external-data-snomed-ct-and-evidence-sources) ·
[Python usage](#python-usage) · [Custom operators](#adding-custom-operators) · [CLI](#cli) · [HTTP API](#http-api) ·
[Configuration](#configuration) · [Architecture](#architecture) · [Tests](#running-tests) ·
[Development](#development) · [Operators](#operators-and-motif-bundles) · [Concept lift](#concept-lift-snomed-ct-only) ·
[Guarantees](#guarantees-and-how-they-are-checked) · [Limitations](#known-limitations-and-open-items)

## Install

Python ≥ 3.12.

```bash
pip install .                 # the library and the `semgen` command
pip install ".[api]"          # + the HTTP API (Litestar, uvicorn)
```

From a checkout, for development:

```bash
uv sync --group dev           # library + API + test and lint tools
```

The wheel contains the code, the packaged DRAFT config (`semgen/resources/`) and `py.typed`; it contains no
SNOMED CT content and no patient data.

## External data (SNOMED CT and evidence sources)

semgen needs a **SNOMED CT International RF2 release**, which is licensed data: obtain it from SNOMED International
or your National Release Centre and keep it outside the repository. Point semgen at it with `SEMGEN_RF2_DIR` (the
release root, its `Snapshot`, or `Snapshot/Terminology`) or pass it explicitly (`--rf2`, `rf2_dir=`). Concept lift
reads the Terminology files (concepts, FSNs, inferred and concrete relationships, OWL refset) and the MRCM refsets in
`Snapshot/Refset/Metadata`; a missing MRCM or OWL file makes every lift `unknown`.

The parsed release is cached (pickle, keyed by file names, sizes and mtimes) in `SEMGEN_CACHE_DIR`, default
`$XDG_CACHE_HOME/semgen` or `~/.cache/semgen`. The first load of a full release takes a while; later loads read the cache.

Optional evidence sources, each pinned by sha256 in the config (a mismatch is a `ConfigError`; a missing file only
makes the dependent operator block):

| Variable | File | Without it |
|---|---|---|
| `SEMGEN_UCUM_ESSENCE` | UCUM `ucum-essence.xml` (essence 1.9) | A1 aggregation blocks `unit_validation_unavailable` |
| `SEMGEN_MAYO_DB` | Mayo `refrange.sqlite` | normative bucketing blocks `mayo_unavailable` |
| `SEMGEN_MAYO_TEST_MAP` | reviewed Mayo test map CSV | every Mayo lookup blocks `no_test_mapping` |
| `SEMGEN_CONFIG` | an alternative config YAML | the packaged config is used |

`.env.example` lists every variable; `data/external/README.md` describes a local layout. semgen does not read `.env`
files itself. **Never commit** RF2 files, caches, the Mayo DB or patient-level data: `.gitignore` excludes them and
`tests/test_architecture.py` fails if any would be published.

## Python usage

```python
from semgen import Budget, SemgenEngine

engine = SemgenEngine.from_config(rf2_dir="/data/SnomedCT_InternationalRF2_PRODUCTION_20260201T120000Z")
# or SemgenEngine.from_settings()  -> everything from SEMGEN_* variables

motif = {
    "motif_id": "M1", "anchor": "n1",
    "nodes": [{"id": "P", "type": "Patient", "role": "patient"},
              {"id": "n1", "type": "Disorder", "code": "44054006", "polarity": "present", "role": "anchor"}],
    "edges": [{"s": "P", "t": "n1", "rel": "has_condition", "prov": "asserted"}],
}

bundles = engine.parse(motif)                   # validate (also accepts motif lists and {"bundles": [...]})
result = engine.generalize(motif, Budget(max_depth=2))
result.status                                   # "exhausted" | "budget_limited"
result.summary()                                # counts
result.to_json()                                # run header, candidates, edges, blocked moves, termination
result.write("runs/")                           # the same files `semgen run` writes, byte for byte

engine.verify(motif, other_motif)               # independent order proof: is other_motif more general?
engine.check_lift("44054006", "73211009")       # one concept-lift step with rule evidence + verifier verdict
engine.inspect_lift("44054006")                 # every accepted ancestor, every transition, where branches stop
engine.provenance()                             # release, config/source hashes, lift fingerprint, operator set
```

`Budget(max_states=, max_depth=, seconds=)` bounds the breadth-first search (all `None` = unbounded). A
`GenContext` can also be built directly (`semgen.context.build_context`, or `GenContext(hierarchy, config, lift)`)
and wrapped with `SemgenEngine(ctx)`; the lower-level functions (`semgen.lattice.enumerate_lattice`,
`semgen.order.check_order`, the operators) remain public. An engine is immutable and can be shared between threads.

## Adding custom operators

An operator is a function `(motif, ctx) -> OperatorResult` that proposes one-step moves (`Move(child_motif,
ChangeRecord(...))`) and reports refused moves as `Blocked` rows; a bundle operator takes and returns bundles
(`BundleOperatorResult`). Operators are plain values in an immutable `OperatorSet`; there is no global registry to
mutate:

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
lift_only = engine.with_operators(engine.operators.only("concept_lift"))
```

The name of an operator is its `op_name` attribute or `__name__`. **Every move from any operator still passes the
policy guard and the independent order proof**; a move that is not provably more general raises
(`GeneralizationOrderError` / `PolicyViolation`) instead of entering the lattice. So a custom operator can widen
what is explored but cannot make the output unsound (an operator that, say, changed a context edge or narrowed a
value would raise). Per-node concept-lift climbs run only when `concept_lift` is in the set.

## CLI

```bash
semgen run --motifs data/motifs/synthetic_motifs.json --out runs/example \
    [--config PATH] [--rf2 DIR] [--max-states N] [--max-depth-budget N] [--time-budget SECONDS] [--depth N] [--progress]
semgen validate --motifs FILE                     # parse + validate against the release
semgen lift 44054006 [--parent 73211009]          # concept-lift inspection as JSON
semgen floor-report --motifs FILE [--out FILE]    # TSV of every root concept-lift decision
semgen serve [--host 127.0.0.1] [--port 8000]     # the HTTP API (needs the api extra)
```

`python -m semgen ...` is equivalent. Every location option falls back to its `SEMGEN_*` variable.

`--motifs` takes either file shape (see "Motif bundles"): today's motif list, where every motif runs as a bundle
of one with exactly the output it had before, or a `{"bundles": [...]}` file. The output directory of each run
is its bundle id (the motif id for a bundle of one). `--progress` also streams every accepted candidate, in BFS
order as it is accepted, to `OUT/<bundle_id>/progress.jsonl`; the final `candidates.jsonl` is still sorted. The
stream is written to `progress.jsonl.partial` and renamed to `progress.jsonl` only after every proof passed; a
stale `progress.jsonl` from an earlier run into the same directory is removed at the start of the run, so a
failed run leaves only the `.partial` file. Every bundle id is validated (`[A-Za-z0-9_.-]+`, inside OUT) before
anything is written.

**Search budgets versus `--depth`.** The search is unbounded unless a budget is given; budgets are explicit
and never a correctness limit:

- `--max-states N` stores at most N states, the root included; a new state beyond that is refused.
- `--max-depth-budget N` stores states at depth N but does not expand them.
- `--time-budget SECONDS` is checked before each expansion. A run it stops is `budget_limited` with
  `seconds` in `budget_hit`, and is **not** byte-reproducible (wall clock).

`--depth N` does **not** bound the search: it only filters the output. The summary line, `candidates.jsonl`,
`edges.jsonl` and `blocked.jsonl` keep only candidates with `depth <= N`, edges between kept candidates and
blocked moves from kept candidates;
`termination.json` always describes the whole search. Given `--depth` without `--max-depth-budget`, the CLI
prints a note to stderr saying so. Without any budget, the real M1-M4 lattices can be large; pass
`--max-depth-budget` for quick runs.

The run header records the concept-lift provenance (release, files, sha256, fingerprint). CLI runs
always climb (see "Search, climb and termination"). For each bundle the CLI prints one line
(`M1 depth=all candidates=... edges=... blocked=... status=...`, or `depth=N` with `--depth N`) and writes
`OUT/<bundle_id>/`:

| File | Contents |
|---|---|
| `run_header.json` | See "Run header" below |
| `candidates.jsonl` | `hash`, `depth`, `origin` (`lattice` or `axis`), and `motif` (canonical JSON) for a bundle of one or `bundle` (canonical bundle JSON: `semantics`, `anchor_part`, parts sorted by id) otherwise; sorted by depth then hash |
| `edges.jsonl` | `parent`, `child`, `changes` (each: `op`, `target`, `field`, `before`, `after`, `evidence`, plus `meaning`, `rule_id` and `source` when set) |
| `blocked.jsonl` | `from` (hash of the candidate), `op`, `target`, `reason`, `detail`. A blocked lift's `detail` includes `parent` whenever a parent was evaluated |
| `termination.json` | `status`, `complete`, `budget`, `budget_hit`, `refused`, `unexpanded_frontier`, `candidates`, `state_space_estimate` (see "Search, climb and termination"), and per liftable root node under `axes` (keyed `<part>/<node>` for a multi-part bundle): `status`, `reached`, `stopped_by` |

Exit codes: `0` success; `1` bad input or missing data (config, pinned files, motifs, RF2, FSN lookup);
`2` command-line usage error (argparse); `3` internal invariant violated (`PolicyViolation` or
`GeneralizationOrderError`, which should never happen).

A review table of every concept-lift decision (TSV, one row per decision) comes from:

```bash
semgen floor-report --motifs data/motifs/synthetic_motifs.json [--out floor_report.tsv]
```

`floor_report` covers the root step only (the direct parents of each root-motif node), not the climb. Its
columns are `motif_id, node, code, fsn, decision, parent, parent_fsn`; the tag, root and ceiling details stay
in `blocked.jsonl`.

### Run header

`run_header.json` holds: SNOMED release and edition, `semgen_version`, config SHA-256 and status (DRAFT),
`temporal_semantics`, the closed-world statement, `budget` (`max_states`, `max_depth`,
`seconds`; null = unbounded), `attribute_definitions_sha256`, `sources.mayo` (`sha256`, `available`,
`test_map_sha256`; no path, so the header holds no machine-specific absolute path), and `floor_policy` (concept-lift provenance: `mode: snomed_ontology`, algorithm, release, the RF2/MRCM/OWL file
names and sha256, and the fingerprint every lift record carries).

## HTTP API

The API is a Litestar application around one `SemgenEngine`. Install the `api` extra, then:

```bash
SEMGEN_RF2_DIR=/data/SnomedCT_... semgen serve --port 8000
# or, in your own ASGI setup:
#   from semgen.api import create_app;  app = create_app()             # engine loaded from SEMGEN_* at startup
#   app = create_app(engine)                                            # reuse an engine you built
```

OpenAPI: `GET /schema` (Swagger UI at `/schema/swagger`, JSON at `/schema/openapi.json`).

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness (200 while the engine is still loading) |
| `GET /ready` | Readiness: 200 with the release once loaded; 503 `loading` / `failed` (with the error) |
| `POST /v1/validate` | `{"input": <motif \| bundle \| list \| {"motifs"} \| {"bundles"}>}` → bundle ids, hashes; 422 on invalid input |
| `POST /v1/verify` | `{"specific", "general", "certificate"?}` → the independent order proof (`ok`, `reason`, `where`) |
| `POST /v1/generalize` | `{"input": <one motif or bundle>, "budget"?: {max_states, max_depth, seconds}, "climb"?: true}` → job (202); `?wait=S` waits up to S seconds and returns 200 when finished |
| `GET /v1/jobs`, `GET /v1/jobs/{id}` | Job status, budget used, summary, error (`invalid_input`, `invariant_violated`, …) |
| `GET /v1/jobs/{id}/result[?depth=N]` | The full lattice (run header, candidates, edges, blocked, termination); 409 while running or after a failure |
| `GET /v1/concepts/{code}` | Active? FSN, parents |
| `GET /v1/concepts/{code}/lift[?max_transitions=N]` | Concept-lift exploration with verifier results |
| `GET /v1/concepts/{code}/lift/{parent}` | One step: decision, rule evidence, verifier verdict |
| `GET /v1/config` | Active config (status, attribute definitions, sha256 pins), which locations are configured (no paths), limits |
| `GET /v1/provenance` | Release, config and source hashes, concept-lift provenance, operator set |

How it runs:

- **Lifecycle.** `create_app()` without an engine loads it from `Settings.from_env()` in a background thread inside
  the Litestar lifespan, so the server starts and answers `/health` immediately; `/ready` turns 200 when the release
  is loaded. Handlers receive the engine, the job store and the limits through Litestar dependency injection
  (`NamedDependency`); until the engine is ready they return 503.
- **CPU-bound work never runs on the event loop.** Lattice enumeration runs in a bounded worker pool
  (`ApiLimits.workers`, default 1); lift exploration, validation and verification run in the default thread
  executor. Threads, not processes: each process would otherwise load its own copy of the release. Enumeration is
  pure Python and holds the GIL while it computes, so it shares the interpreter with request handling — keep
  `workers` small and scale out with more processes (each loads the release once) if needed.
- **Budgets are always enforced.** A request's budget is clamped to `ApiLimits` (default `max_states=20000`,
  `seconds=120`); an omitted dimension gets the server limit, so no request is unbounded. Per-node concept-lift climbs
  are bounded by the ancestor set, not by the budget (as in the library). A run stopped by `seconds` is not
  byte-reproducible.
- **Results** live in memory for the process lifetime (the oldest finished jobs are evicted beyond
  `ApiLimits.max_jobs`). There is no authentication: run it on a trusted network or behind your gateway.

Tune limits with `create_app(limits=ApiLimits(max_states=..., seconds=..., workers=..., max_body_bytes=...))`.

## Configuration

Runtime **locations** come from `semgen.settings.Settings` (explicit arguments win over `SEMGEN_*` variables; see
[External data](#external-data-snomed-ct-and-evidence-sources)). **Clinical configuration** is a YAML file
validated at load (`semgen.config.load_config`); the packaged default is
`src/semgen/resources/generalization.yaml` (installed as `semgen/resources/`). Relative paths in a config file
resolve against that file's directory, so a copied config keeps working. Concept lift itself has no configuration:
it is derived from the release. See [DRAFT configuration](#draft-configuration-reference) for the fields; the removed
keys of older designs (`floor_policy`, `optimuskg`, `panel_sources`) are rejected with a `ConfigError`.

## Architecture

```
semgen/
  model.py, bundle.py, canonical.py     domain: motifs, nodes, edges, intervals, bundles, canonical JSON + hashes
  interfaces.py                         operator interfaces, GenContext, ChangeRecord/Move/Blocked, OperatorSet
  operators/                            the operators (concept_lift, normative_bucketing, attribute_deletion,
                                        attribute_aggregation, motif_deletion) + default_operators()
  lattice/                              policy.py (guard + independent lift verification), moves.py (one-step
                                        neighbours), search.py (budgeted BFS, climbs, root proofs, Budget, Lattice)
  order.py                              independent order proofs (check_order, check_bundle_order, A1/A3 exactness)
  lift.py, lift_verify.py               SNOMED-only concept-lift rules and their independent verifier
  snomed.py, concept_model.py           RF2 loaders (hierarchy, MRCM, relationships, OWL) with caching
  refrange.py, ucum.py, relevance.py    evidence sources (Mayo ranges, UCUM) and the cohort relevance gate
  config.py, settings.py, resources/    clinical config (pinned, validated) and runtime locations
  context.py, engine.py                 build a GenContext; SemgenEngine (the application service)
  motif_io.py, export.py                input parsing/validation; deterministic JSONL export + run header
  cli.py, __main__.py, floor_report.py  command line
  api/                                  Litestar app (app.py) and job runner (jobs.py) — optional extra
```

Dependencies point one way: domain → interfaces → operators → lattice → engine → CLI / API. `semgen.interfaces`
imports no operator, which is what keeps `semgen.order`, `semgen.refrange` and the operators free of import cycles
(`tests/test_architecture.py` imports every module first in a fresh interpreter). The core never imports Litestar.

Dependency decisions: **pydantic** (already used for the domain models) also validates config and settings, so
there is no separate settings library; **polars** reads RF2 files; **PyYAML** reads config. **Litestar** + **uvicorn**
are an optional extra; the API uses Litestar's own DI, lifespan and pydantic plugin (no extra framework). Background
execution uses the standard library (`concurrent.futures`, `asyncio`) rather than a task queue, because results are
per-process and the release is held in memory. Development: **pytest** + **Hypothesis** (property tests), **ruff**
(lint + import order), **mypy** (type check), **build** (wheel). `ruff format` is not enforced: the research code
keeps its compact style.

## Running tests

```bash
uv run pytest                      # everything available; licensed-data tests skip cleanly
uv run pytest -m "not snomed"      # synthetic only (what CI runs)
uv run pytest -rs                  # also list why tests were skipped
```

Ordinary tests use synthetic data only: a fake hierarchy and concept model (`tests/support/fake_snomed.py`), a
three-file synthetic RF2 release (`tests/fixtures/rf2/`), synthetic motifs and patients. Tests marked `snomed` need
the licensed release and run only when `SEMGEN_RF2_DIR` is set; set `SEMGEN_UCUM_ESSENCE`, `SEMGEN_MAYO_DB`,
`SEMGEN_MIMIC_BUNDLE` and `SEMGEN_MIMIC_GRAPHS` to enable the checks that need those files (all restricted or
third-party data, never committed). Reuse an existing parsed-release cache with `SEMGEN_CACHE_DIR`; otherwise tests
cache into a temporary directory.

`tests/test_golden.py` compares lattice output byte for byte with saved files (`tests/fixtures/golden/`,
`GENERATED_BY.md`); a difference is a regression, never a reason to regenerate. The `fake_*` goldens are committed;
the `real_*` goldens contain SNOMED CT content derived from the licensed release and are kept locally only (their
cases skip when absent). API tests (`tests/test_api.py`) skip when Litestar is not installed;
`tests/test_architecture.py` checks import cycles, that the core works without Litestar, and that no personal path,
RF2 file, cache, patient record or `.env` would be published.

## Development

```bash
uv sync --group dev
uv run ruff check src tests
uv run mypy
uv run pytest -m "not snomed"
uv build                           # sdist + wheel into dist/
```

CI (`.github/workflows/ci.yml`) runs the same lint, type check, synthetic test suite (Python 3.12 and 3.13), and
builds the wheel, installs it into a clean virtual environment outside the checkout and smoke-tests it, with and
without the `api` extra. It never needs licensed or restricted data.

Contributions: keep generalization semantics and the independence of the verifiers (`semgen.order`,
`semgen.lift_verify`) intact, add tests with synthetic data, never commit licensed or patient data, and record
design changes in the (local, unpublished) design documents.

## Operators and motif bundles

The unit of search is a **motif bundle**: all motifs of one patient or episode, joined at the shared patient node
`P`, with declared Boolean `semantics` (`"all"`: every part must match; `"any"`: at least one; missing = unknown,
never read as `"all"`). A single motif is a bundle of one (`semantics: "all"`) and hashes exactly as before.

Input: either a motif list, or

```json
{"bundles": [{"bundle_id": "B1", "semantics": "all", "anchor_motif": "M1", "subject": {"sex": "female", "age_days": 20000},
              "motifs": [ ... motif objects ... ]}]}
```

`anchor_motif` is required with more than one motif; `subject` (selection context for bucketing) is optional and
immutable within a run. `subject.sex` must use the reference source's own vocabulary: for Mayo, the values of
`ranges.sex` (today `female`, `male`; `any` is the wildcard), read from the pinned DB when it opens. A value the
source does not know (for example `"F"`) would silently match no sex-specific row, so when a candidate Mayo row
partitions on sex it blocks as `subject_sex_unrecognised`. A range attached to a result compares
`applies_to.sex` with `subject.sex` by equality. With more than one motif, non-`P` node ids are namespaced
`<motif_id>.<node_id>`. Bundle ids (and, in a motif-list file, motif ids) name output directories, so ids that
differ only by case are rejected as duplicates.

Operators, in fixed order. Per-motif operators act on every part (originals are never mutated):

| Operator | Kind | What it does | Meaning |
|---|---|---|---|
| `concept_lift` | per motif | A code becomes a direct IS-A parent accepted by `semgen.lift` (SNOMED CT only) | generalized |
| `normative_bucketing` | per motif | A point value becomes its low/reference/high bucket of a pinned reference range | generalized |
| `attribute_deletion` | per motif | Drops one constraint the bundle's cohort definition declares `relaxable`: a concept-independent attribute, a value, a date, a window or one of its bounds, or one A1 observation. The node, every edge, negated facts and context stay | generalized |
| `attribute_aggregation` (A1) | per motif | Merges repeated observations of one fully identified test (system, code, method, specimen; UCUM-valid unit) into one node whose `observations` keep every original value, unit, date, reference range and label (the node keeps a reference range only if all share it). No mean/latest/min/max | kept |
| `attribute_aggregation` (A3) | per motif | Groups P-attached nodes of one type and role under their unique lowest common SNOMED CT ancestor, reachable by accepted concept-lift steps; the members stay verbatim and the ancestor is a summary only | kept |
| `motif_deletion` | bundle | Removes a redundant part whose removal keeps the match set, proven by a SNOMED-constrained containment certificate: under `"all"` (AND) the broader part, under `"any"` (OR) the narrower one; exact duplicates keep the smaller `part_id` (the anchor part always stays) | kept |

**Attribute deletion relevance.** The cohort definition alone decides: `required` → rejected (`relevance_retain`),
`relaxable` → a candidate (still proven by the guard and `check_order`), not declared or no cohort →
`relevance_unknown`. A path from the node to the anchor does not decide anything. A `relaxable` declaration on an
attribute the attribute definitions mark `about: node_concept` is a conflict → `relevance_unknown`; on an attribute
they do not list it is also `relevance_unknown`, reported as unlisted (the existing contract treats an unlisted
attribute as concept-dependent, so e.g. `age_at_dx`, listed `about: patient`, is deletable and an unlisted name is
not).

**No motif aggregation.** Motif aggregation (replacing two AND-ed parts by an OR aggregate with an LGG summary) was
removed: it turned AND into OR. OR alternatives are an `"any"` bundle of plain parts, which needs no generalization
move. A2 (panel grouping from a pinned panel file) was removed as well; neither has configuration any more
(`panel_sources` and `optimuskg` are `ConfigError`s).

**Removed** in this round: the operators `edge_removal`, `relation_relaxation`, `temporal_coarsening`,
`range_coarsening` and `attribute_removal` (with their config: relation hierarchy, time ladder, value ladders,
`lvef_convention`), the PhecodeX floor mode (`floors.py`, `phecodex.py`, `icd10map.py`, `--phecodex` flags), the
config's `max_depth`/`max_candidates`, and the statuses `depth_limited`/`candidate_limited` (now
`budget_limited`).

## Concept lift (SNOMED CT only)

`src/semgen/lift.py` decides every one-step lift from the RF2 release alone; there is no configuration, no concept
list, no depth or count threshold. Each active inferred IS-A parent is evaluated independently and gets exactly one
outcome, `accepted`, `rejected` (first rejecting rule) or `unknown` (first undecidable rule), with every rule's evidence:

1. `concept`: both concepts active; the parent is an active inferred IS-A parent.
2. `hierarchy`: the parent is not the root (no parents) nor a top-level concept (all its parents are the root), and
   no top-level hierarchy of the child is lost.
3. `semantic_tag`: the FSN tag is unchanged (`no_semantic_tag` is unknown).
4. `definition`: both concepts have an OWL class axiom and RF2 definition status agrees with it (EquivalentClasses =
   fully defined). Primitive status is recorded as evidence; it is not a stopping rule.
5. `mrcm_domain`: the parent stays in every evaluable MRCM domain of the child and is not a domain's focus concept.
6. `defining_relationships`: the parent keeps every defining attribute type of the child (inferred relationships and
   concrete values) and at least as many relationship groups; values may broaden, but a value reduced to a focus of
   the attribute's MRCM range counts as dropped. Attribute types must be permitted by the MRCM attribute domain and
   parent values must lie in an evaluable MRCM range; a child with no defining relationships is `unknown`.

The **floor** of a branch is derived, not supplied: the concept whose every parent step is rejected or unknown.
`SnomedLift.explore(code)` runs the BFS over all accepted branches: candidates deduplicated by concept with every
derivation path, every transition, per-concept termination, `complete`/`exhausted` (a `max_transitions` technical
budget marks the result incomplete and lists the pending concepts). `src/semgen/lift_verify.py` is the independent
verifier (it does not import `semgen.lift`): activity, IS-A edge, top-level, tag, MRCM domains, value subsumption of
every defining relationship, groups, OWL status, the record and the release fingerprint. The lattice guard runs it on
every applied code change. Concept-level validity only; motif containment is proved by `semgen.order`.

## Synthetic motifs M1-M4

`data/motifs/synthetic_motifs.json` holds four motifs. **They are synthetic development fixtures, invented
by us to imitate the shape of motifs BioPathNet enrichment is expected to produce. They are not output
from our colleague, not BioPathNet output, and their values and context ids are made up** (the gene ids
are real, the pathway and disease context ids are placeholders). BioPathNet is not integrated and no patient
data is used. They are the only motifs semgen has been run on.

| Motif | Anchor and shape | What it exercises |
|---|---|---|
| M1 | Breast cancer (age at diagnosis 67), doxorubicin (cumulative dose 360), LVEF 38 %, followed by 23 d; context gene TOP2B and a pathway | Disorder climb, drug lift blocked by a concept-dependent attribute, value-carrying observable, attribute and window deletion |
| M2 | Type 2 diabetes with *absent* type 1 diabetes, metformin, CKD, eGFR 42 at 180 d; context "lactic acidosis" | Negation (absent nodes are never changed), T2DM climb, eGFR value (not bucketable: no test identity) |
| M3 | EGFR-mutant NSCLC, osimertinib, interstitial lung disease | Longest disorder climb, structural-grouper exclusion |
| M4 | Rheumatoid arthritis, methotrexate, ALT 3.6 xULN | ALT value (not bucketable: no test identity), RA climb to Arthritis, methotrexate climb |

### Real results

Run `pytest tests/test_lift.py` with `SEMGEN_RF2_DIR` set for the real-release checks; with
`SEMGEN_MIMIC_GRAPHS` also set it covers every SNOMED-coded fact of the MIMIC-IV demo patient graphs (restricted
local data, never committed). Per-concept outcomes are in each transition record.

## DRAFT configuration (reference)

Every clinical value in `src/semgen/resources/generalization.yaml` is **DRAFT: not clinically approved**. Nothing has been
reviewed by a clinician; each value needs sign-off before any real use. The file holds:

- `attribute_definitions`: path and sha256 of `src/semgen/resources/attribute_definitions.yaml`, verified at load, which says
  whether each attribute is `about: patient` (`age_at_dx`) or `about: node_concept` (`cumulative_dose`); an
  unlisted attribute is `node_concept` (protected)
- `mayo`: the sha256 of the Mayo `refrange.sqlite`, verified at start (a mismatch is a `ConfigError`); its location
  comes from `SEMGEN_MAYO_DB` (or an optional `path`). A missing file makes bucketing block as `mayo_unavailable`;
  the optional reviewed test map (`SEMGEN_MAYO_TEST_MAP` / `test_map`) is absent today, so every Mayo lookup is
  `no_test_mapping`
- `ucum`: the sha256 of the UCUM essence (`SEMGEN_UCUM_ESSENCE` / optional `path`); without it A1 blocks
- `protected_roles`, `negation_policy`

Relations compare by equality (there is no relation hierarchy), and there is no depth or candidate cap in the
config: the search is bounded only by an explicit budget.

## What is blocked and why

Each blocked move is written to `blocked.jsonl` with its reason.

| Reason | Operator | Meaning |
|---|---|---|
| any `semgen.lift.REJECT_REASONS` | concept lift | **rejected** by the named rule (e.g. `defining_attribute_dropped`, `semantic_tag_changed`, `top_level_concept`, `mrcm_domain_lost`). `detail.transition.rules` gives every rule's evidence |
| any `semgen.lift.UNKNOWN_REASONS` | concept lift | **unknown**: the release cannot establish the step (e.g. `no_defining_relationships`, `owl_axiom_missing`, `mrcm_unavailable`); blocked, never accepted |
| `inactive_parent` | concept lift | The parent concept is inactive in the release |
| `unknown_concept` | concept lift | The node's code is not an active concept in the loaded release |
| `no_parent` | concept lift | The concept is active but has no IS-A parent (the root), so there is nothing to lift to |
| `carries_value` | concept lift | The node has a measurement value, which only has meaning for its exact concept |
| `concept_dependent_attr` | concept lift | The node currently has an attribute whose meaning depends on the concept (or an unflagged one) |
| `carries_value` | concept lift (lattice) | The node holds A1 observations, whose values belong to its exact concept |
| `concept_dependent_attr` | attribute deletion | The attribute is concept-dependent (or unflagged) and cannot be deleted. `detail` has `{"attr": name}` |
| `relevance_retain` / `relevance_unknown` | attribute deletion | The cohort definition declares the constraint `required`; or it does not declare it, declares no cohort, or declares relaxable an attribute that is protected (`detail.reason`, `detail.necessity`) |
| `result_range_unverified` | normative bucketing | The range reported with the result fails an eligibility check (`detail.check`, e.g. `unbounded` when both bounds are null); Mayo is not tried |
| `subject_context_missing` | normative bucketing | A range partitions on sex or age and the subject lacks that field (`detail.missing`) |
| `subject_sex_unrecognised` | normative bucketing | A Mayo row partitions on sex and `subject.sex` is not in the DB's `ranges.sex` vocabulary (`detail.sex`, `detail.known`) |
| `no_test_identity` | normative bucketing | The result has no test identity, so no range can be looked up |
| `mayo_unavailable` | normative bucketing | The Mayo DB file is not present |
| `no_test_mapping` / `specimen_mismatch` / `ambiguous_test_mapping` | normative bucketing | The test map has no row, no row for this specimen, or rows for several Mayo tests |
| `no_applicable_range` / `ambiguous_range` | normative bucketing | Zero, or more than one, usable Mayo reference row applies |
| `units_not_convertible` | normative bucketing | The range unit differs from the value unit (identical strings only; no UCUM file) |
| `measurement_identity_unknown` / `measurement_identity_differs` | attribute aggregation | A test identity field is missing (null is unknown), or differs across the group |
| `observation_has_other_edges` / `observation_has_attrs` / `observation_edges_differ` / `observation_not_attached` / `anchor_would_be_removed` | attribute aggregation (A1) | Merging would lose an edge, attribute or edge constraint, or remove the anchor |
| `unit_invalid` / `unit_validation_unavailable` | attribute aggregation (A1) | The unit is not a valid case-sensitive UCUM expression of the pinned essence (e.g. `mEq/L`; UCUM writes `meq/L`), or no essence is loaded |
| `multiple_minimal_ancestors` | attribute aggregation (A3) | The concepts share several incomparable lowest common ancestors |
| `lcs_outside_floor` | attribute aggregation (A3) | A step to the common ancestor crosses the hierarchy boundary: concept lift's `hierarchy` rule (root, top-level concept) or a `TOP_REASONS` stop; `detail.step`, `detail.rule` |
| `lcs_semantic_rejection` | attribute aggregation (A3) | Concept lift rejects a step for another rule (e.g. `semantic_tag_changed`, `mrcm_domain_lost`, `defining_attribute_dropped`); `detail.step`, `detail.rule` |
| `ontology_evidence_unknown` | attribute aggregation (A3) | The release cannot decide a step (`semgen.lift.UNKNOWN_REASONS`), a concept is inactive, or there is no route; or a candidate concept is not active (`detail.code`) |
| `group_types_differ` / `group_edges_differ` | attribute aggregation (A3) | The nodes differ in type/role or in their `P` edge |
| `unknown_bundle_semantics` | motif deletion | The bundle's semantics are not declared |
| `anchor_part_protected` / `last_part` / `has_absent_node` | motif deletion | The anchor part, the last part, or a motif with an absent node |
| `not_contained` / `snomed_mapping_missing` | motif deletion | No containment certificate was found (`detail.inactive_codes` when an inactive code is in the way) |

Why these rules:

- **Lift eligibility is state-based.** A value or concept-dependent attribute present on the current motif blocks lifting. There is no historical blocking; a later lift must pass its own guard and order proof.
- **LVEF and ALT measurement nodes cannot be concept-lifted while they carry a value.** A value such as LVEF 38 % is only meaningful for its exact concept (finding F7), so lifting the concept would silently change what the number means. Their values can be bucketed against a pinned reference range (when the record carries the evidence), or deleted.
- **Dependent attributes are protected from removal (rule change).** Earlier versions protected `cumulative_dose` only from lifting, and nothing stopped `attribute_removal` dropping it; that was a gap. Now `attribute_deletion` (which replaced `attribute_removal`) refuses any concept-dependent attribute, including unflagged ones, and `semgen.lattice.policy.guard` independently rejects the same removal (`dependent_attr_removed`). A value can still be removed, so LVEF can lose its value and then lift. Doxorubicin with a dose can never be lifted: 360 mg/m2 of doxorubicin is not 360 mg/m2 of another anthracycline.
- **Absent constraints are never changed.** The semantics are closed world: "no X" means no recorded fact that is X or a descendant of X. Lifting "no X" to "no parent of X" would narrow the set of matching patients, so it is not a generalization.

## Search, climb and termination

`enumerate_lattice(root, ctx, budget=Budget(), progress=None)` takes a motif or a bundle, runs a breadth-first
search, then one climb per liftable node (per `(part, node)` for a multi-part bundle).

- **Lattice.** Level-by-level from the root over all operators, with global deduplication of states by hash (the
  hash covers the active representation only, so different operation orders reaching the same bundle meet in one
  state). It is unbounded by default; an explicit `Budget(max_states, max_depth, seconds)` bounds it (see the CLI section).
- **Climb.** From the root motif only, each liftable node follows accepted lifts on that node alone until none remain. It is finite because the ancestor set is, so the budget does not apply to it. Climb moves pass the same guard and order proof and produce real candidates (`origin: axis`), edges and ChangeRecords. A node blocked at the root stays `policy_restricted`; the climb does not remove values to get past that. Post-removal lifts come only from the bounded lattice.
- **Depth.** A climb candidate's `depth` can exceed the depth budget. Combinations of operations above it are not explored.
- **Logging.** Climbed motifs log only their `concept_lift` blocks.
- **Pure BFS.** `enumerate_lattice(..., climb=False)` skips the climb. CLI runs always climb.
- **State-space estimate.** `termination.json` records `state_space_estimate`, computed before the search: the
  product over parts and nodes of (1 + accepted ancestors per liftable node), 3 per bucketable value, 2 per
  deletable constraint, 2 per candidate deletion and 2 per candidate aggregation pair at the root. It is for
  orientation only, is **not an upper bound** (it undercounts aggregation and reach-in), and is never enforced.

Motif `status` in `termination.json` is one of:

| Status | Meaning |
|---|---|
| `exhausted` | No state was refused and no stored state with a move is left unexpanded, even if a budget value was reached exactly (a depth cap that lands on a dead end is `exhausted`). Only this status sets `complete: true` |
| `budget_limited` | A budget stopped the search; `budget_hit` says which (`max_states`, `max_depth` or `seconds`), `unexpanded_frontier` counts stored-but-unexpanded states and `refused` counts refused new states. `unexpanded_frontier` can be 0 when `max_states` hit during the last state's expansion |

`complete` is false whenever the search stopped for a budget, so a false value means "more candidates may
exist", not an error. All four M1-M4 lattices are `budget_limited` at a depth budget of 4.

Per-node `axes` status:

| Status | Meaning |
|---|---|
| `reached_floor` | Every blocked parent on the climb was stopped by the floor policy |
| `reached_hierarchy_top` | At least one branch reached a concept with no parent (`no_parent`). This is an "any branch" status |
| `policy_restricted` | Something other than the floor stopped a branch: a value, a dependent attribute, `no_semantic_tag`. It can also follow several climbed levels, when a restriction appears on a climbed ancestor |

`stopped_by` is the union of reasons across all branches, so it can show floors on branches other than the one
that determined the status. For an exhausted run, `blocked.jsonl` can differ with the cap, because blocks on a
final dead-end frontier are not recorded.

## Guarantees and how they are checked

- **Order proof.** Every move is proven by an independent checker that trusts no operator output: `semgen.order.check_order` (identity map) for a per-motif change, and `check_bundle_order` for bundles, which derives the transition from the two bundles (one part changed in place, or one part removed) and re-verifies deletion certificates in the direction the semantics require. A1 and A3 moves are also proven exact (`check_a1_merge`: every source has the merged node's code, unit and full test identity, and each observation keeps its value, dates, reference range and label; `check_group_merge`: members verbatim). A failure raises `GeneralizationOrderError`.
- **Policy guard.** Before the proof, `semgen.lattice.policy.guard` rejects any move that removes the patient or anchor, touches an absent node or edge, changes a context edge, removes a concept-dependent attribute, targets an inactive concept, or breaks the floor policy (`PolicyViolation`). Every observation unit of a new or changed A1 aggregate must be valid UCUM of the pinned essence (`a1_unit_invalid`; no essence: `a1_unit_unverified`), independently of the operator. For an A3 group it re-derives the summary concept: the unique lowest common ancestor of the member concepts, reached from each by steps `semgen.lift_verify` accepts (`group_summary_*`).
- **Root proof.** At the end `enumerate_lattice` re-proves, with `check_bundle_order`, the edge by which each candidate (climb candidates included) was first reached, so the proofs compose along a path to the root; for a bundle of one every candidate is also checked against the root with `check_order`.
- **Generalization versus matching.** Generalization reads ancestors only. Reading descendants is phenotype matching, which is separate; the only descendant reads in `src/` belong to the floor policies.
- **Containment oracle (tests only).** `tests/support/matcher.py` is an independent one-to-one, closed-world patient matcher (bundles by their semantics; an A3 group needs one fact per member and never reads its summary concept). Tests check that along every lattice edge the set of matching synthetic patients only grows, and stays equal on `kept` edges. Production code never imports it, which a test enforces.
- **Determinism.** The same inputs give byte-identical output files (no timestamps) for runs that are unbounded or bounded only by `max_states`/`max_depth`; two runs can be compared with `diff -r`. A run stopped by `--time-budget` is marked in `termination.json` and is not covered.

## Future integration boundary

Our colleague's real BioPathNet-enriched motifs are not available yet. BioPathNet is not integrated, and no
patient data is used anywhere. When the motifs arrive, an adapter from their format into this motif schema
will be needed; the schema here is our own and does not claim to match theirs. Context edges
(`prov: context`) are only ever removed, never promoted to asserted constraints. Nothing in this repository
has been run on real colleague output.

## Known limitations and open items

- Concept lift is ontology-derived and DRAFT, not clinically validated. It judges concept-level structure only: a
  step that keeps every attribute axis with broader values (e.g. doxorubicin -> substance with antibacterial
  mechanism of action) is accepted although a clinician may find the meaning drifted; SNOMED CT does not encode that.
- The ceiling is release-dependent: a different SNOMED release can change descendant counts and so the accepted parents.
- The climb runs from the root motif only. A value or dose node (LVEF, eGFR, ALT, doxorubicin with dose) stays `policy_restricted`, and its climb is not explored from the root even if the value could be removed. Post-removal lifts exist only inside the bounded lattice.
- Budgets do not bound the climb, and combinations above the depth budget are not explored, so `complete` is false for every M1-M4 run at a depth budget of 4.
- `floor_report` covers the root step only; its TSV has `decision` (the transition reason) and `parent`; full evidence is in the lattice records.
- SNOMED CT use is under your local licence; this is recorded but not resolved.
- Stage 2 (RxNorm/RxClass drug-class floors) is not implemented.
- Normative bucketing has positive paths on synthetic data only: real records carry no test identity, no
  reviewed Mayo test map exists, and the Mayo DB has no ALT range rows.
- Clinical review of the attribute definitions (check 7 of the methodology) is out of scope for the POC.
- A1 enforces UCUM validity, so units recorded in non-UCUM spellings (MIMIC's `mEq/L`) block the merge
  (`unit_invalid`); no spelling is rewritten.
- Attribute deletion needs an explicit cohort definition; real bundles declare none, so every deletion there is
  `relevance_unknown`. An attribute must also be defined `about: patient` in `src/semgen/resources/attribute_definitions.yaml` to
  be deletable at all (unlisted attributes are protected).
- Motif deletion is tested on synthetic bundles only (software properties: proofs,
  monotonicity on synthetic patients, determinism). Nothing here is a clinical validation, and the synthetic
  motif files contain no real bundles yet.
