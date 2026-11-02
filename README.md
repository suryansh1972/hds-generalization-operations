# semgen

A Python proof of concept that takes a small graph pattern (a "motif") describing a kind of patient and
enumerates every provably more general version of it, as a lattice, using SNOMED CT as the concept
hierarchy. The methodology is `docs/semantic-generalization-methodology.md`, amended by the two plans below.
The Stage 1 floor design comes from the external document `clinician-free-generalization.md` in the HDX
workspace (`/Users/suryanshshivaprasad/Documents/HDX/clinician-free-generalization.md`, outside this
repository), which is cited only as the source of that design. The staged decisions for the floors are in
`docs/plans/stage1-phecodex-floors.md` and the build plan is `docs/plans/semantic-generalization-implementation.md`.

semgen does **no support counting, no utility scoring and no disclosure control**, and it makes **no
BioPathNet calls**. It only generates, checks and exports generalized motifs.

## Install

```bash
uv sync
uv run python -m semgen.sources fetch
```

`fetch` downloads three PhecodeX CSVs from the pinned commit `6c5c6f78...` of `PheWAS/phecodeX` into
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
    --config config/generalization.yaml [--rf2 DIR] [--phecodex DIR] [--depth N] --out runs/example
```

`--depth` defaults to `max_depth` in the config (4). For each motif it prints one line
(`M1 depth=4 candidates=... edges=... blocked=...`) and writes `OUT/<motif_id>/`:

| File | Contents |
|---|---|
| `run_header.json` | SNOMED release and edition, config SHA-256 and status (DRAFT), LVEF convention, `temporal_semantics`, closed-world statement, max depth, floor source, PhecodeX commit and file hashes, ICD-10 map refset and release, `phecode_level`, `ccsr_check: unavailable`, source licences |
| `candidates.jsonl` | `hash`, `depth`, `motif` (canonical JSON), sorted by depth then hash |
| `edges.jsonl` | `parent`, `child`, `changes` (each: `op`, `target`, `field`, `before`, `after`, `evidence`) |
| `blocked.jsonl` | `from` (hash of the candidate), `op`, `target`, `reason`, `detail` |

Exit codes: `0` success; `1` bad input or missing data (config, source files, motifs, RF2, FSN lookup);
`2` command-line usage error (argparse); `3` internal invariant violated (`PolicyViolation` or
`GeneralizationOrderError`, which should never happen).

A review table of every concept-lift floor decision (TSV, one row per decision, with the blocking
descendant) comes from:

```bash
uv run python -m semgen.floor_report --motifs data/motifs/synthetic_motifs.json [--out floor_report.tsv]
```

## Synthetic motifs M1-M4

`data/motifs/synthetic_motifs.json` holds four motifs. **They are synthetic development fixtures, invented
by us to imitate the shape of motifs BioPathNet enrichment is expected to produce. They are not output
from our colleague, not BioPathNet output, and their values and context ids are made up** (the gene ids
are real, the pathway and disease context ids are placeholders). They are the only motifs semgen has been
run on.

| Motif | Anchor and shape | What it exercises |
|---|---|---|
| M1 | Breast cancer (age at diagnosis 67), doxorubicin (cumulative dose 360), LVEF 38 %, followed by 23 d; context gene TOP2B and a pathway | Disorder floors (both parents blocked), drug lift blocked by a concept-dependent attribute, value-carrying observable, relation relaxation, edge removal cascades over context edges |
| M2 | Type 2 diabetes with *absent* type 1 diabetes, metformin, CKD, eGFR 42 at 180 d; context "lactic acidosis" | Negation (absent nodes are never changed), strict T2DM to DM ruling, eGFR ladder |
| M3 | EGFR-mutant NSCLC, osimertinib, interstitial lung disease | The one allowed disorder lift (to NSCLC) |
| M4 | Rheumatoid arthritis, methotrexate, ALT 3.6 xULN | ALT range coarsening to (3,5], RA lifts blocked, drug `unmapped` |

## DRAFT configuration

Every clinical value in `config/generalization.yaml` is **DRAFT: not clinically approved**. Nothing has been
reviewed by a clinician; each value needs sign-off before any real use. The file holds:

- `floor_source`: the pinned PhecodeX commit and file hashes, `phecode_level`, ICD-10 map refset and rules, licence (unconfirmed)
- `attribute_flags`: which attributes are concept-independent (`age_at_dx`) or concept-dependent (`cumulative_dose`)
- `value_ladders` (LVEF, eGFR, ALT x ULN), `attr_ladders` (age, cumulative dose) and `time_ladder`
- `relation_parents` (for example `administered_drug` to `exposed_to_drug`)
- `protected_roles`, `negation_policy`, `lvef_convention` and `max_depth`

## What is blocked and why

Each blocked move is written to `blocked.jsonl` with its reason.

| Reason | Operator | Meaning |
|---|---|---|
| `outside_floor` | concept lift | The parent has at least one active descendant that is not inside every PhecodeX anchor of the node's concept, so lifting would leave the clinically meaningful group. `detail` names the blocking descendant and anchor |
| `unmapped` | concept lift | Applies to any SNOMED-coded node (Disorder, Finding, Procedure, Substance, Observable). The concept has no usable SNOMED to ICD-10 to PhecodeX mapping, so no floor can be derived. Fail-closed |
| `inactive_parent` | concept lift | The parent concept is inactive in the release |
| `unknown_concept` | concept lift | The node's code is not an active concept in the loaded release |
| `no_parent` | concept lift | The concept is active but has no IS-A parent (a root), so there is nothing to lift to |
| `carries_value` | concept lift | The node has a measurement value, which only has meaning for its exact concept |
| `concept_dependent_attr` | concept lift | The node has an attribute whose meaning depends on the concept (or an unflagged one) |
| `no_ladder` | range coarsening | No ladder is configured for this concept or attribute |
| `unit_mismatch` | range coarsening, temporal coarsening | The value or window unit differs from the ladder unit |
| `protected_anchor_edge` | edge removal | The edge is the patient to anchor edge |
| `touches_absent` | edge removal | The edge touches an absent (negated) node |
| `would_drop_protected` | edge removal | Removing it would orphan and drop the anchor or an absent node |
| `no_asserted_left` | edge removal | Removing it would leave no asserted edge |

Why these rules:

- **Substances and observables go through the same ICD-10 to PhecodeX rule.** The floor applies to every SNOMED-coded node. Most substances have no ICD-10 target and so are `unmapped`; observables with a value are blocked `carries_value` before any floor check. Drug-class floors (Stage 2, for example RxNorm/RxClass) are future work.
- **LVEF and ALT measurement nodes cannot be concept-lifted.** A value such as LVEF 38 % is only meaningful for its exact concept (finding F7), so lifting the concept would silently change what the number means. Their values can still be coarsened with a ladder.
- **`cumulative_dose` blocks a drug lift.** It is concept-dependent: 360 mg/m2 of doxorubicin is not 360 mg/m2 of another anthracycline. Any attribute without a flag in the YAML is treated as dependent.
- **Absent constraints are never changed.** The semantics are closed world: "no X" means no recorded fact that is X or a descendant of X. Lifting "no X" to "no parent of X" would narrow the set of matching patients, so it is not a generalization.
- **How floors are derived.** For any SNOMED-coded node, take its usable SNOMED to ICD-10 targets (International map, refset 447562003, rules `TRUE` and `OTHERWISE TRUE`), look them up in PhecodeX (with a trailing-character fallback), truncate to `first_decimal` and keep the most specific phecodes as the node's *anchors*. A direct parent is allowed only if **every** active descendant-or-self of that parent maps inside **every** anchor. Any gap (no map, no phecode, an inactive parent) blocks the lift (fail-closed).

Real outcomes on M1-M4 (DRAFT, release 20260201):

| Motif and node | Concept | Result |
|---|---|---|
| M1 n1 | Malignant neoplasm of breast | both parents (Neoplasm of breast, Malignant neoplasm of thorax) `outside_floor` |
| M2 n1 | Diabetes mellitus type 2 | parent Diabetes mellitus `outside_floor` (blocked by diabetes due to pancreatic injury); the strict ruling |
| M2 n4 | Chronic kidney disease | both parents `outside_floor` |
| M3 n1 | EGFR-mutant NSCLC | lift to Non-small cell lung cancer **allowed** |
| M4 n1 | Rheumatoid arthritis | both parents `outside_floor` |
| M1 n2, M2 n3, M3 n3, M4 n2 | drugs | `concept_dependent_attr` (M1 doxorubicin, checked first) or `unmapped` (metformin, osimertinib, methotrexate: no ICD-10 target) |
| M1 n3, M2 n5, M4 n3 | LVEF, eGFR, ALT | `carries_value` |

## Guarantees and how they are checked

- **Order proof.** Every candidate is compared with its parent, and finally with the root, by an independent identity-map checker (`semgen.order.check_order`) that reads nodes and edges only and trusts no operator output. A failure raises `GeneralizationOrderError`.
- **Policy guard.** Before the proof, `lattice.guard` rejects any move that removes the patient or anchor, touches an absent node or edge, changes a context edge, targets an inactive concept, or breaks the floor policy (`PolicyViolation`).
- **Root proof.** `enumerate_lattice` re-proves every candidate against the root at the end.
- **Containment oracle (tests only).** `tests/support/matcher.py` is an independent one-to-one, closed-world patient matcher. Tests check that along every lattice edge the set of matching synthetic patients only grows. Production code never imports it, which a test enforces.
- **Determinism.** The same inputs give byte-identical output files (no timestamps); two runs can be compared with `diff -r`.

## Future integration boundary

Our colleague's real BioPathNet-enriched motifs are not available yet. When they are, an adapter from their
format into this motif schema will be needed; the schema here is our own and does not claim to match theirs.
Context edges (`prov: context`) are only ever removed, never promoted to asserted constraints. Nothing in
this repository has been run on real colleague output.

## Known limitations and open items

- Licences (PhecodeX is unconfirmed; SNOMED CT use is under your local licence) are recorded but not resolved.
- The CCSR cross-check is unavailable (it needs the US ICD-10-CM map); `run_header.json` says `ccsr_check: unavailable`.
- Stage 2 (drug and observable floors) is not implemented, so those lifts stay blocked.
- The M2 T2DM to DM lift is ruled strict (no lift) for now; an exception list could come later.
- LVEF ladder uses the ESC `<40` convention (`lvef_convention: ESC2022_lt40`); this is a DRAFT choice needing clinical sign-off.
- Clinical review of all ladders, attribute flags and relation parents (check 7 of the methodology) is out of scope for the POC.
