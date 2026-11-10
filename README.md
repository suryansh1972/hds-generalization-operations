# semgen

A Python proof of concept that takes a small graph pattern (a "motif") describing a kind of patient and
enumerates every provably more general version of it, as a lattice, using SNOMED CT as the concept
hierarchy. The methodology is `docs/semantic-generalization-methodology.md`, amended by the three plans below.
The Stage 1 floor design comes from the external document `clinician-free-generalization.md` in the HDX
workspace (`/Users/suryanshshivaprasad/Documents/HDX/clinician-free-generalization.md`, outside this
repository), which is cited only as the source of that design. The staged decisions for the floors are in
`docs/plans/stage1-phecodex-floors.md`, the recursive-ancestor amendment (default floor, per-node climb, termination
reporting) is `docs/plans/recursive-ancestor-generalization.md`, and the original build plan is
`docs/plans/semantic-generalization-implementation.md`.

semgen does **no support counting, no utility scoring and no disclosure control**, and it makes **no
BioPathNet calls**. It only generates, checks and exports generalized motifs.

## Install

```bash
uv sync
uv run python -m semgen.sources fetch
```

`fetch` is needed only for `floor_policy.mode: phecodex` (and the tests marked `phecodex`); the default
`snomed_boundary` mode needs the RF2 release alone. It downloads three PhecodeX CSVs from the pinned commit `6c5c6f78...` of `PheWAS/phecodeX` into
`data/external/phecodex/<commit>/` (git-ignored) and checks each against the sha256 recorded in
`config/generalization.yaml`. A missing or tampered file raises an error naming the file. The PhecodeX
licence is **unconfirmed**; the files are not committed.

SNOMED CT is read from a local International RF2 release. The default location is
`/Users/suryanshshivaprasad/Documents/HDX/SnomedCT_InternationalRF2_PRODUCTION_20260201T120000Z/Snapshot/Terminology`.
Override with environment variables:

| Variable | Meaning |
|---|---|
| `SEMGEN_RF2_DIR` | the RF2 `Snapshot/Terminology` folder (the ICD-10 map is found at `../Refset/Map`) |
| `SEMGEN_CACHE_DIR` | folder for the parsed-RF2 cache (default `<repo>/data/cache`, independent of the current directory) |
| `SEMGEN_PHECODEX_DIR` | folder holding the three PhecodeX files (default `data/external/phecodex/<commit>`) |

## Running tests

```bash
uv run pytest                                  # everything
uv run pytest -m "not snomed and not phecodex" # fast: synthetic hierarchy only
uv run pytest -rs                              # also list why tests were skipped
```

Tests marked `snomed` need the RF2 folder and tests marked `phecodex` need the fetched files. If that
data is missing they **skip** (they do not fail); use `-rs` to see the skips. A present-but-tampered
PhecodeX file fails instead of skipping.

## CLI

```bash
uv run python -m semgen run --motifs data/motifs/synthetic_motifs.json \
    --config config/generalization.yaml [--rf2 DIR] [--phecodex DIR] [--depth N] \
    [--floor-policy snomed_boundary|phecodex] --out runs/example
```

`--depth` defaults to `max_depth` in the config (4). `--floor-policy` overrides `floor_policy.mode` from the
config; the run header records the mode actually used. CLI runs always climb (see "Search, climb and
termination"). For each motif the CLI prints one line
(`M1 depth=4 candidates=... edges=... blocked=... status=...`) and writes `OUT/<motif_id>/`:

| File | Contents |
|---|---|
| `run_header.json` | See "Run header" below |
| `candidates.jsonl` | `hash`, `depth`, `origin` (`lattice` or `axis`), `motif` (canonical JSON), sorted by depth then hash |
| `edges.jsonl` | `parent`, `child`, `changes` (each: `op`, `target`, `field`, `before`, `after`, `evidence`) |
| `blocked.jsonl` | `from` (hash of the candidate), `op`, `target`, `reason`, `detail`. A blocked lift's `detail` includes `parent` whenever a parent was evaluated |
| `termination.json` | `status`, `complete`, `max_depth`, `max_candidates`, `unexpanded_frontier`, `candidates`, and per liftable root node under `axes`: `status`, `reached`, `stopped_by` |

Exit codes: `0` success; `1` bad input or missing data (config, source files, motifs, RF2, FSN lookup);
`2` command-line usage error (argparse); `3` internal invariant violated (`PolicyViolation` or
`GeneralizationOrderError`, which should never happen).

A review table of every concept-lift decision (TSV, one row per decision) comes from:

```bash
uv run python -m semgen.floor_report --motifs data/motifs/synthetic_motifs.json [--floor-policy MODE] [--out floor_report.tsv]
```

`floor_report` covers the root step only (the direct parents of each root-motif node), not the climb. Its
columns are `motif_id, node, code, fsn, decision, parent, parent_fsn, anchors, blocking_descendant,
blocking_fsn, anchor`. The last three are PhecodeX diagnostics; for `snomed_boundary` the report carries only
`decision` and `parent`, so the tag, root and ceiling details stay in `blocked.jsonl`.

### Run header

`run_header.json` holds: SNOMED release and edition, `semgen_version`, config SHA-256 and status (DRAFT),
`lvef_convention`, `temporal_semantics`, the closed-world statement, `max_depth`, `max_candidates`, and
`floor_policy` (the selected policy's provenance, including `mode`). For `snomed_boundary` that block holds the
DRAFT status string, `max_descendants`, `characteristic_type`, the semantic-tag rule, and each excluded root
with its resolved concept id, FSN and reason. For `phecodex` the header also carries `floor_source`,
`phecode_level`, `icd10_map_refset`, `icd10_map_release`, `phecodex_commit`, `phecodex_sha256`,
`ccsr_check: unavailable` and `source_licences`.

## Floor policies

`floor_policy.mode` is required in the config: `snomed_boundary` (the default) or `phecodex`. A missing or
unknown mode is a `ConfigError`; there is no unrestricted mode and no fallback. If the selected policy cannot
be built or evaluated, the run fails or the lift is blocked. `floor_source` is required only for `phecodex`.

**`snomed_boundary`** uses SNOMED CT alone. A candidate parent is accepted only if all of these hold:

1. it is active;
2. it has the same FSN semantic tag as the child (a concept with no parseable tag fails closed as `no_semantic_tag`);
3. it is not a descendant-or-self of an `excluded_ancestor_roots` entry (each FSN must resolve to exactly one active concept, or the run fails with `FsnError`);
4. its `descendant_count` is at most `max_descendants` (initially 2500).

`descendant_count` is strict: it counts distinct, active, transitive descendants and excludes the concept
itself, so a concept reached by two IS-A paths counts once. Arthritis therefore has 1,295 (1,296 including
itself), under the 2500 ceiling. Lift only reads upward: descendant enumeration happens only in the floor policies, and `is_descendant_or_self` is an upward check.

**This rule is DRAFT. It is a computational broadness heuristic, not a clinically validated boundary.** The
2500 ceiling and the exclusion list are not clinically validated either. The ceiling depends on the SNOMED
release, so the same value can admit different parents in another release.

**`phecodex`** keeps its earlier behaviour: a parent is allowed only if every active descendant-or-self maps
inside every PhecodeX anchor of the node's concept (see below). PhecodeX is an optional capability here,
retained for possible future cross-disease phenotype comparison. It is not a patient-similarity engine and
none is built.

## Synthetic motifs M1-M4

`data/motifs/synthetic_motifs.json` holds four motifs. **They are synthetic development fixtures, invented
by us to imitate the shape of motifs BioPathNet enrichment is expected to produce. They are not output
from our colleague, not BioPathNet output, and their values and context ids are made up** (the gene ids
are real, the pathway and disease context ids are placeholders). BioPathNet is not integrated and no patient
data is used. They are the only motifs semgen has been run on.

| Motif | Anchor and shape | What it exercises |
|---|---|---|
| M1 | Breast cancer (age at diagnosis 67), doxorubicin (cumulative dose 360), LVEF 38 %, followed by 23 d; context gene TOP2B and a pathway | Disorder climb, drug lift blocked by a concept-dependent attribute, value-carrying observable, relation relaxation, edge removal cascades over context edges |
| M2 | Type 2 diabetes with *absent* type 1 diabetes, metformin, CKD, eGFR 42 at 180 d; context "lactic acidosis" | Negation (absent nodes are never changed), T2DM climb, eGFR ladder |
| M3 | EGFR-mutant NSCLC, osimertinib, interstitial lung disease | Longest disorder climb, structural-grouper exclusion |
| M4 | Rheumatoid arthritis, methotrexate, ALT 3.6 xULN | ALT range coarsening to (3,5], RA climb to Arthritis, methotrexate climb |

### Real results at depth 4 (DRAFT, RF2 release 20260201)

Per liftable root node: axis status, number of distinct ancestors reached by the climb, and what stopped it.
Every one of the four lattices is `depth_limited` at depth 4 in both modes, so none is `complete`.
`snomed_boundary` candidates: M1 1207, M2 605, M3 476, M4 476. `phecodex` candidates: M1 476, M2 124, M3 67, M4 77.

| Node | Concept | `snomed_boundary` | `phecodex` |
|---|---|---|---|
| M1 n1 | Malignant neoplasm of breast | reached_floor, 5 (ceiling, tag) | reached_floor, 0 (outside_floor) |
| M1 n2 | Doxorubicin, with dose | policy_restricted, 0 (concept_dependent_attr) | policy_restricted, 0 (concept_dependent_attr) |
| M1 n3 | LVEF | policy_restricted, 0 (carries_value) | policy_restricted, 0 (carries_value) |
| M2 n1 | Type 2 diabetes | reached_floor, 4 (ceiling) | reached_floor, 0 (outside_floor) |
| M2 n3 | Metformin | reached_floor, 0 (excluded_ancestor_root) | policy_restricted, 0 (unmapped) |
| M2 n4 | Chronic kidney disease | reached_floor, 6 (ceiling, tag) | reached_floor, 0 (outside_floor) |
| M2 n5 | eGFR | policy_restricted, 0 (carries_value) | policy_restricted, 0 (carries_value) |
| M3 n1 | EGFR-mutant NSCLC | reached_floor, 16 (ceiling, tag) | reached_floor, 1 (outside_floor) |
| M3 n3 | Osimertinib | reached_floor, 7 (ceiling, excluded_ancestor_root) | policy_restricted, 0 (unmapped) |
| M3 n4 | Interstitial lung disease | reached_floor, 4 (ceiling, tag) | reached_floor, 0 (outside_floor) |
| M4 n1 | Rheumatoid arthritis | reached_floor, 4 (ceiling, tag) | reached_floor, 0 (outside_floor) |
| M4 n2 | Methotrexate | reached_floor, 3 (ceiling, excluded_ancestor_root) | policy_restricted, 0 (unmapped) |
| M4 n3 | ALT | policy_restricted, 0 (carries_value) | policy_restricted, 0 (carries_value) |

In `phecodex` mode the one root-step lift is M3 n1 to Non-small cell lung cancer; the T2DM to Diabetes
mellitus lift stays blocked (the strict M2 ruling applies to `phecodex` only). In `snomed_boundary` mode the
T2DM climb reaches Diabetes mellitus and a further ancestor that is not a direct parent of T2DM. Rheumatoid
arthritis reaches Arthritis. The LVEF value can be removed by `attribute_removal`, after which LVEF may lift
inside the bounded lattice.

## DRAFT configuration

Every clinical value in `config/generalization.yaml` is **DRAFT: not clinically approved**. Nothing has been
reviewed by a clinician; each value needs sign-off before any real use. The file holds:

- `floor_policy`: `mode` and the `snomed_boundary` block (`max_descendants`, `characteristic_type`, `excluded_ancestor_roots`)
- `floor_source`: the pinned PhecodeX commit and file hashes, `phecode_level`, ICD-10 map refset and rules, licence (unconfirmed); used by `phecodex` mode and the fetch command
- `attribute_flags`: which attributes are concept-independent (`age_at_dx`) or concept-dependent (`cumulative_dose`)
- `value_ladders` (LVEF, eGFR, ALT x ULN), `attr_ladders` (age, cumulative dose) and `time_ladder`
- `relation_parents` (for example `administered_drug` to `exposed_to_drug`)
- `protected_roles`, `negation_policy`, `lvef_convention`, `max_depth` and `max_candidates`

## What is blocked and why

Each blocked move is written to `blocked.jsonl` with its reason.

| Reason | Operator | Meaning |
|---|---|---|
| `above_descendant_ceiling` | concept lift (`snomed_boundary`) | The parent's strict descendant count exceeds `max_descendants`. `detail` has `descendant_count` and `ceiling` |
| `semantic_tag_changed` | concept lift (`snomed_boundary`) | The parent's FSN semantic tag differs from the child's, for example a disorder lifting to a finding |
| `no_semantic_tag` | concept lift (`snomed_boundary`) | The child or parent has no parseable semantic tag. Fail-closed |
| `excluded_ancestor_root` | concept lift (`snomed_boundary`) | The parent is a descendant-or-self of a configured excluded root. `detail` names the root and the reason |
| `outside_floor` | concept lift (`phecodex`) | The parent has at least one active descendant that is not inside every PhecodeX anchor of the node's concept. `detail` names the blocking descendant and anchor |
| `unmapped` | concept lift (`phecodex`) | Any SNOMED-coded node whose concept has no usable SNOMED to ICD-10 to PhecodeX mapping, so no floor can be derived. Fail-closed |
| `inactive_parent` | concept lift | The parent concept is inactive in the release |
| `unknown_concept` | concept lift | The node's code is not an active concept in the loaded release |
| `no_parent` | concept lift | The concept is active but has no IS-A parent (the root), so there is nothing to lift to |
| `carries_value` | concept lift | The node has a measurement value, which only has meaning for its exact concept |
| `concept_dependent_attr` | concept lift | The node currently has an attribute whose meaning depends on the concept (or an unflagged one) |
| `concept_dependent_attr` | attribute removal | The attribute is concept-dependent (or unflagged) and cannot be removed. `detail` has `{"attr": name}` |
| `no_ladder` | range coarsening | No ladder is configured for this concept or attribute |
| `unit_mismatch` | range coarsening, temporal coarsening | The value or window unit differs from the ladder unit |
| `protected_anchor_edge` | edge removal | The edge is the patient to anchor edge |
| `touches_absent` | edge removal | The edge touches an absent (negated) node |
| `would_drop_protected` | edge removal | Removing it would orphan and drop the anchor or an absent node |
| `no_asserted_left` | edge removal | Removing it would leave no asserted edge |

Why these rules:

- **Lift eligibility is state-based.** A value or concept-dependent attribute present on the current motif blocks lifting. There is no historical blocking; a later lift must pass its own guard and order proof.
- **LVEF and ALT measurement nodes cannot be concept-lifted while they carry a value.** A value such as LVEF 38 % is only meaningful for its exact concept (finding F7), so lifting the concept would silently change what the number means. Their values can be coarsened with a ladder, or removed.
- **Dependent attributes are protected from removal (rule change).** Earlier versions protected `cumulative_dose` only from lifting, and nothing stopped `attribute_removal` dropping it; that was a gap. Now `attribute_removal` refuses any concept-dependent attribute, including unflagged ones, and `lattice.guard` independently rejects the same removal (`dependent_attr_removed`). A value can still be removed, so LVEF can lose its value and then lift. Doxorubicin with a dose can never be lifted: 360 mg/m2 of doxorubicin is not 360 mg/m2 of another anthracycline. Range coarsening of the dose, and removal of a whole node through edge removal, are unchanged.
- **Absent constraints are never changed.** The semantics are closed world: "no X" means no recorded fact that is X or a descendant of X. Lifting "no X" to "no parent of X" would narrow the set of matching patients, so it is not a generalization.
- **How `phecodex` floors are derived.** For any SNOMED-coded node, take its usable SNOMED to ICD-10 targets (International map, refset 447562003, rules `TRUE` and `OTHERWISE TRUE`), look them up in PhecodeX (with a trailing-character fallback), truncate to `first_decimal` and keep the most specific phecodes as the node's *anchors*. A direct parent is allowed only if **every** active descendant-or-self of that parent maps inside **every** anchor. Any gap (no map, no phecode, an inactive parent) blocks the lift (fail-closed). This applies to every SNOMED-coded node, not only disorders.

## Search, climb and termination

`enumerate_lattice` runs a bounded breadth-first search, then one climb per liftable node.

- **Bounded lattice.** Level-by-level from the root motif over all operators, with global deduplication. `max_depth` (default 4) bounds the depth of combined operations and `max_candidates` (default 50000) bounds the combined lattice.
- **Climb.** From the root motif only, each liftable node follows accepted lifts on that node alone until none remain. It is finite because the ancestor set is, so `max_depth` and `max_candidates` do not apply to it. Climb moves pass the same guard and order proof and produce real candidates (`origin: axis`), edges and ChangeRecords. A node blocked at the root stays `policy_restricted`; the climb does not remove values to get past that. Post-removal lifts come only from the bounded lattice.
- **Depth.** A climb candidate's `depth` can exceed `max_depth`. Combinations of operations above `max_depth` are not explored.
- **Logging.** Climbed motifs log only their `concept_lift` blocks.
- **Pure BFS.** `enumerate_lattice(..., climb=False)` skips the climb. CLI runs always climb.

Motif `status` in `termination.json` is one of:

| Status | Meaning |
|---|---|
| `exhausted` | No unexplored move remains. Only this status sets `complete: true` |
| `depth_limited` | Motifs on the final frontier still had moves when `max_depth` was reached. `unexpanded_frontier` counts them. A cap that lands on a dead end is `exhausted`, not truncated |
| `candidate_limited` | `max_candidates` was reached. `unexpanded_frontier` can be 0 when the cap hit during the last motif's expansion |

`complete` is false whenever the search stopped for a limit, so a false value means "more candidates may
exist", not an error. All four M1-M4 lattices are `depth_limited` at depth 4.

Per-node `axes` status:

| Status | Meaning |
|---|---|
| `reached_floor` | Every blocked parent on the climb was stopped by the floor policy |
| `reached_hierarchy_top` | At least one branch reached a concept with no parent (`no_parent`). This is an "any branch" status |
| `policy_restricted` | Something other than the floor stopped a branch: a value, a dependent attribute, `unmapped`, `no_semantic_tag`. It can also follow several climbed levels, when a restriction appears on a climbed ancestor |

`stopped_by` is the union of reasons across all branches, so it can show floors on branches other than the one
that determined the status. For an exhausted run, `blocked.jsonl` can differ with the cap, because blocks on a
final dead-end frontier are not recorded.

## Guarantees and how they are checked

- **Order proof.** Every candidate is compared with its parent, and finally with the root, by an independent identity-map checker (`semgen.order.check_order`) that reads nodes and edges only and trusts no operator output. A failure raises `GeneralizationOrderError`.
- **Policy guard.** Before the proof, `lattice.guard` rejects any move that removes the patient or anchor, touches an absent node or edge, changes a context edge, removes a concept-dependent attribute, targets an inactive concept, or breaks the floor policy (`PolicyViolation`).
- **Root proof.** `enumerate_lattice` re-proves every candidate, including climb candidates, against the root at the end.
- **Generalization versus matching.** Generalization reads ancestors only. Reading descendants is phenotype matching, which is separate; the only descendant reads in `src/` belong to the floor policies.
- **Containment oracle (tests only).** `tests/support/matcher.py` is an independent one-to-one, closed-world patient matcher. Tests check that along every lattice edge the set of matching synthetic patients only grows. Production code never imports it, which a test enforces.
- **Determinism.** The same inputs give byte-identical output files (no timestamps); two runs can be compared with `diff -r`.

## Future integration boundary

Our colleague's real BioPathNet-enriched motifs are not available yet. BioPathNet is not integrated, and no
patient data is used anywhere. When the motifs arrive, an adapter from their format into this motif schema
will be needed; the schema here is our own and does not claim to match theirs. Context edges
(`prov: context`) are only ever removed, never promoted to asserted constraints. Nothing in this repository
has been run on real colleague output.

## Known limitations and open items

- `snomed_boundary`, the 2500 ceiling and the exclusion list are DRAFT and not clinically validated.
- Mechanism and disposition groupers such as Antifolate are not excluded; only the structural grouper `Substance categorized by structure` is. Osimertinib and methotrexate climbs can still reach such groupers. Needs clinical review.
- The excluded subtree (`Substance categorized by structure`) contains recognised drug classes as well as chemical structures. In SNOMED release 20260201 *Biguanide hypoglycemic agent* (metformin's only parent) and *Anthracycline* (doxorubicin's only parent) sit inside it, so metformin reaches nothing under `snomed_boundary` (`reached_floor` with 0 reached). Osimertinib and methotrexate still lift through their mechanism parents. This is a known DRAFT consequence for future review; the exclusion is unchanged.
- The ceiling is release-dependent: a different SNOMED release can change descendant counts and so the accepted parents.
- The climb runs from the root motif only. A value or dose node (LVEF, eGFR, ALT, doxorubicin with dose) stays `policy_restricted`, and its climb is not explored from the root even if the value could be removed. Post-removal lifts exist only inside the bounded lattice.
- `max_depth` and `max_candidates` do not bound the climb, and combinations above `max_depth` are not explored, so `complete` is false for every M1-M4 run at depth 4.
- `floor_report` covers the root step only; its TSV has no columns for `snomed_boundary` diagnostics beyond `decision` and `parent`.
- Licences (PhecodeX is unconfirmed; SNOMED CT use is under your local licence) are recorded but not resolved.
- The CCSR cross-check is unavailable (it needs the US ICD-10-CM map); in `phecodex` mode `run_header.json` says `ccsr_check: unavailable`.
- Stage 2 (RxNorm/RxClass drug-class floors) is not implemented.
- The M2 T2DM to DM lift is ruled strict (no lift) in `phecodex` mode; it climbs in `snomed_boundary` mode.
- LVEF ladder uses the ESC `<40` convention (`lvef_convention: ESC2022_lt40`); this is a DRAFT choice needing clinical sign-off.
- Clinical review of all ladders, attribute flags and relation parents (check 7 of the methodology) is out of scope for the POC.
