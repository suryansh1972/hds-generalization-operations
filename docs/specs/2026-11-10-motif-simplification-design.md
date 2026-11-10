# Motif Simplification Operators — Design

*10 Nov 2026 · Status: APPROVED 10 Nov 2026 with corrections (§11) · Source methodology: `docs/specs/source-methodology.md` (copy of `semantic-operators-methodology.md`, sha256 `328e1adc…251f7`).*

Nothing in this design is clinically validated. Every policy value stays DRAFT.

---

## 1. Context

semgen takes a synthetic clinical motif and lists every provably more general version of it as a lattice, with a ChangeRecord per step and an independent identity-map proof that each child matches at least the patients of its parent (S ⪯ S′). The branch `feature/semantic-generalization` has six operators: concept lift, attribute removal, range coarsening, temporal coarsening, relation relaxation and edge removal. It also has two floor policies (`snomed_boundary`, default; `phecodex`) and a per-node climb.

The 10 Nov meeting changed the operator set:

| Status | Operator |
|---|---|
| Kept unchanged | concept lift (floor policy, climb, termination per axis) |
| New | normative range bucketing (replaces range coarsening ladders) |
| Extended | attribute deletion (replaces attribute removal; also dates, time windows, ordering edges) |
| New | attribute aggregation (A1–A4) |
| New | motif deletion (D1–D4) |
| New | motif aggregation |
| Removed | temporal coarsening, relation relaxation, edge removal, range coarsening |

The lattice now works on a **motif bundle**: all motifs of one patient, joined at the shared patient node.

**Base.** The new work starts from a commit on `feature/semantic-generalization` that includes the recursive-ancestor work (R1–R10). That work is uncommitted at the time of writing; it will be committed after approval (§9).

**What Phase 0 changed.** Several assumptions in the methodology do not hold on the real data (§7). The decisions in §2 rule on each one. The main consequence is that most operators can be proved only on synthetic fixtures today. On real data they come out blocked, unbucketable or without an edge, each with a recorded reason.

### 1.1 Upstream requirements (outside semgen)

semgen's real-data behaviour waits on these. Until each one exists, the dependent move stays off and the run says so.

| # | Requirement | Owner | Unblocks |
|---|---|---|---|
| U1 | Patient graph carries **value, unit and reference range per result** (FHIR `Observation.value[x]`, `referenceRange`; OMOP `value_as_number`, `unit_concept_id`, `range_low/high`). Today `All_data/` records carry only `code_seen, relation, resource, status, time, route`. | patient-graph builder | normative bucketing on real data, A1 on real data |
| U2 | Patient graph keeps the **principal diagnosis** (FHIR `Encounter.diagnosis.use/rank` or OMOP `condition_status_concept_id`). Absent today. | patient-graph builder | anchor source `record` |
| U3 | Patient-graph **closure** derives interpreted findings from measurements (BMI above range → BMI 40+ finding) and publishes its rules as a file semgen can read. | patient-graph builder | A2 on real data |
| U4 | FHIR **`derivedFrom`** kept on results. | patient-graph builder | A3 on real data |
| U5 | A **SNOMED → RxNorm** (or SNOMED → ChEMBL) map. Note: the builder already maps 416 drug edges via "SNOMED CT medicine code, through the shared mapping"; that map could serve once it is published as a pinned file. | you / UMLS | drug rules in D3 and the guards (indication, contraindication, adverse reaction) |
| U6 | Saved Mayo catalog pages in `data/external/mayo_catalog_pages/` (git-ignored), at least ALT 8362, CRTS1 48216 and CSTCE 614154 (the "Fees & Codes" tab, which lists the result LOINC). `config/mayo_loinc_map.csv` is built only from those pages and shown to you before use (§2, P3). | you | Mayo branch of bucketing |
| U7 | Mayo extractor fixes (§7.1.3). | you (Mayo repo) | correct Mayo rows for ALT and eGFR |
| U8 | Metric harness implementing `evaluate(bundle)`. | Nikita | D4, metric_deltas values |

---

## 2. Decisions

### 2.1 Global rules

| ID | SPEC rule | Decision |
|---|---|---|
| G1 | **No hardcoding** | No SCTID, FSN, symptom or drug list, numeric threshold, depth or candidate cap in `src/` or `config/`. A test (`tests/test_no_hardcoding.py`) greps both trees for SCTID-shaped integers (6–18 digits), FSN-shaped strings (`… (tag)`), and numeric literals in config values. It allows only the entries in `config/hardcoding_exemptions.yaml`, where each entry has `value`, `file` and `reason`. 40- and 64-hex hashes and version strings are recognised as such and are not numbers. **Exemptions (complete list):** (a) the RF2 format ids (IS-A type, inferred characteristic type, FSN description type, root concept, ICD-10 extended-map refset), moved into one module, `src/semgen/rf2_schema.py`, reason "RF2 file-format constants"; (b) concept lift's `max_descendants: 2500`, the excluded-root FSN `Substance categorized by structure (substance)` and refset `447562003`, reason "concept lift kept unchanged by decision"; (c) `config/snomed_profile.yaml` (FSNs of the `interprets`, `has_interpretation` and `due_to` attributes), reason "schema binding, like the KG profile"; (d) the KG profile's HPO frequency term for "obligate", same reason; (e) `config/mayo_loinc_map.csv` once you approve it, reason "approved source mapping; every row cites a saved catalog page". New code gets no exemptions. |
| G1d | SNOMED profile | `config/snomed_profile.yaml` binds the roles `interprets`, `has_interpretation` and `due_to` to attribute FSNs. On load, each FSN must resolve to exactly one active concept that appears as an attribute in the pinned release's MRCM attribute-domain file (`der2_cissccRefset_MRCMAttributeDomainSnapshot_*`). Otherwise the run stops (`SnomedProfileError`). |
| G1a | Config contents | `config/generalization.yaml` keeps only source paths, pinned versions, sha256s, the concept-lift block (exempt), and one switch, `mayo.allow_medium_confidence` (boolean, default false). `max_depth` and `max_candidates` go in T10. `lvef_convention`, `value_ladders`, `attr_ladders`, `time_ladder` and `relation_parents` go in T1. `attribute_flags` goes in T5, replaced by the attribute-definitions file (P4). |
| G1b | KG profile | `config/kg_profile.yaml` binds OptimusKG **(label, relation)** pairs to roles: `manifestation: (DIS-PHE, PHENOTYPE_PRESENT)`, `indication: (DRG-DIS, INDICATION)`, `contraindication: (DRG-DIS, CONTRAINDICATION)`, `adverse_reaction: (DRG-PHE, ADVERSE_DRUG_REACTION)`, plus `kg_parent_disease: (DIS-DIS, PARENT)` and `kg_parent_phenotype: (PHE-PHE, PARENT)`, which the entailment direction needs. On load each pair must exist in the pinned release's `edges.parquet`; an unknown or missing pair stops the run. |
| G1c | Age cap | `AGE_CAP = 90` leaves `motif_io.py`. It moves to `sources/hipaa_safe_harbor.yaml` (value 90, citation 45 CFR §164.514(b)(2)(i)(C)), pinned by path and sha256 in config. |
| G2 | S ⪯ S′, ChangeRecord | Every move passes `guard` and the independent `check_order` (extended, §4.8). A ChangeRecord gains `source` (name + version/sha256), `rule_id` and `meaning: kept | generalized`. `kept` holds only for D1, D2, and A2 when the closure derives the finding. Everything else is `generalized`. |
| G3 | Determinism, invariants | Output is byte-identical for the same inputs. Absent nodes are never touched. Closed-world negation, the identity-map proof, `guard`, R5 (state-based lift eligibility) and R6 (dependent attributes are protected) stay. `src/` never imports `tests/support/matcher.py`. |
| G4 | Fail closed | A missing source blocks the move, or makes the node unbucketable or unmapped. There is no fallback source. Each block is a `Blocked` row with a reason. |
| G5 | Licences | The Mayo dataset is never committed. Its folder pattern `data/external/mayo/` is git-ignored, and the default path points outside the repo (`…/refrange-master/data/refrange.sqlite`). It is pinned by path and sha256 (`3edbad893eaca3825a3f161cf7c0b60df4026ff17f32ebf14d3c3a7fa4b4a107`). The run header carries `source_licences: {mayo: permission_required, phecodex: unconfirmed, optimuskg: per_source_terms}`. |

### 2.2 Phase 0 rulings (your decisions of 10 Nov)

| ID | Decision |
|---|---|
| P1 | **Base.** Commit the recursive-ancestor work on `feature/semantic-generalization` after you approve its diff summary (§9). The worktree branches from that commit. |
| P2 | **Hardcoding.** As G1, G1a and G1c. |
| P3 | **Mayo.** (a) LOINC: the online catalog appears to publish a result LOINC per test (search snippet: ALT 8362 result "Alanine Aminotransferase (ALT), S" → LOINC 1743-4). mayocliniclabs.com returns HTTP 403 to automated fetches, and semgen work **never fetches it in any way that gets around its bot check**. You will save the pages (U6). `config/mayo_loinc_map.csv` (`loinc, mnemonic, analyte, page_file, url`) is then built only from those saved pages, one row per page, and shown to you before it is used. Until then Mayo stays unbucketable on real data, and every Mayo test uses the synthetic SQLite fixture. (b) Extractor bugs are listed for you in §7.1.3, with no workaround in semgen. (c) M4's ALT fixture becomes **145 U/L**. (d) Bucketing on real data stays **inactive** until U1. |
| P4 | **Concept dependence.** Every motif attribute is declared in `formats/attribute_definitions.yaml`, which ships with the motif format, as `about: patient | node_concept`. A missing entry counts as dependent. `age_at_dx: patient`, `cumulative_dose: node_concept`. The SNOMED-slot rule is dropped, with the reasons recorded in ADR-0005 (no `cumulative dose` concept; Age at diagnosis has no slots; Body weight inheres in a body structure, not the person). |
| P5 | **CHECKS.** Real-data expectations are the Phase 0 facts (blocked, unbucketable or no edge, each with its reason). Every positive path is proved on synthetic SNOMED, OptimusKG, Mayo and PhecodeX fixtures. Real-data positive fixtures are chosen from the data by a stated rule (§7.6), and you see them before tests are written. |
| P6 | **OptimusKG.** Bind (label, relation) pairs. Normalise float-string SNOMED ids (`"7180009.0"` → `"7180009"`, accepted only when the fractional part is exactly `.0` and the remainder is all digits; anything else is rejected and logged). Exclude edges with `relation_conflict = true` and log them to `kg_excluded.jsonl`. Map a motif node to the KG node whose type matches its FSN semantic tag (`disorder` → Disease node, `finding` → Phenotype node). No match, or more than one, means unmapped. |
| P7 | **Anchor.** OptimusKG anchor finding is dropped (ADR-0012 records the Phase 0 (e) failures). The chain is record → SNOMED Due to → producer. OptimusKG explanatory coverage stays as a column in `anchor_report.tsv`. Every fixture gets an `expected_anchor`. |
| P8 | `semantic-operators-methodology.md` copied to `docs/specs/source-methodology.md` (done; byte-identical). |

### 2.3 Task decisions (T1–T13)

| Task | Decision |
|---|---|
| T1 | Remove `temporal_coarsening`, `relation_relaxation`, `edge_removal`, `range_coarsening`, and the config keys `time_ladder`, `relation_parents`, `value_ladders`, `attr_ladders`, `lvef_convention`. Remove `Ladder` and `RelationHierarchy` from `config.py`. `check_order` requires equal relations (`relation_changed`). The test matcher compares relations by equality. Update `ALL_OPERATORS`, the README and the tests (delete the four operator test files; adjust lattice, neighbor, export and containment tests). |
| T2 | `MotifBundle`: one patient node `P`, motifs as parts (`motif_id`, `anchor`, `expected_anchor`, node ids). When a bundle holds more than one motif, the loader namespaces node ids as `<motif_id>.<node_id>`. A bundle of one keeps ids unchanged, so existing hashes and tests are unaffected. Bundle-level `subject: {sex, age_days}` is selection context for ranges only, not part of the pattern or the hash (§4.1, soundness does not depend on it). Canonical JSON and hash are defined over the bundle. `Motif` stays, and `MotifBundle.of(motif)` wraps it. |
| T3 | Reference-range layer exactly as specified (§4.1). UCUM conversion reads the pinned **UCUM essence file** (`ucum-essence.xml`, Regenstrief), so no conversion factor is typed. A unit pair it cannot convert is "not convertible". |
| T4 | `normative_bucketing` operator. Proof: interval or interval-union containment. |
| T5 | `attribute_deletion` replaces `attribute_removal` (§4.2). |
| T6 | `attribute_aggregation` A1–A4 (§4.3). |
| T7 | KG layer: Parquet loader for OptimusKG Dataverse doi:10.7910/DVN/IYNGEV **v3.2**, pinned by path and sha256 per file; KG-profile binding; SNOMED → KG mapping (P6). Drug rules return `Blocked(..., "drug_map_missing")` until U5. |
| T8 | `motif_deletion` D1–D3, guards, D4 interface (off) (§4.4). |
| T8b | Anchor finding by the fallback chain (§4.6). OptimusKG is a report column only. |
| T9 | `motif_aggregation` (§4.5). |
| T10 | Lattice over the six operators: upper bound U, streaming, machine budget, best-first fallback, `--depth` as a display filter, extended order checker (§4.7, §4.8). |
| T11 | `MetricsHook` protocol plus `metric_deltas.jsonl` (§4.9). |
| T12 | Fixtures and tests (§7.6, §8). |
| T13 | ADRs, README, dated methodology amendment, the existing lattice viewer carried into the repo and extended (§3.4). |

---

## 3. Architecture

### 3.1 Modules

| Module | Status | Responsibility |
|---|---|---|
| `src/semgen/rf2_schema.py` | new (T1) | RF2 format ids: IS-A, inferred, FSN type, root, ICD-10 map refset. Exempt (G1). |
| `src/semgen/model.py` | change | `Interval` stays. New `IntervalUnion` (sorted, disjoint, same unit; normalised). `Node` gains `conj: tuple[str, ...]` (extra codes of a merged node; empty by default), `loinc: str | None`, `reference_range: ReferenceRange | None`, `dates: Mapping[str, str]` (ISO 8601), `members: tuple[str, ...]` and `derived_from: tuple[str, ...]`. `Edge` gains `dates`. `value` is `Interval | IntervalUnion | None`. |
| `src/semgen/bundle.py` | new (T2) | `MotifBundle`, `MotifPart`, loader, canonical JSON, hash. |
| `src/semgen/formats/` + `formats/attribute_definitions.yaml` | new (T5) | Attribute (`about`) and relation (`kind: assertion | ordering | context`) definitions shipped with the motif format. |
| `src/semgen/refrange/` | new (T3) | `result_range.py` (FHIR/OMOP range on the result), `mayo.py` (sqlite reader, row selection), `ucum.py` (essence-file conversion), `buckets.py` (L/N/H, finer bands, chain). |
| `src/semgen/kg/` | new (T7) | `profile.py` (KG profile + schema validation), `optimuskg.py` (Parquet loader, sha256 check), `mapping.py` (SNOMED → KG node), `evidence.py` (`KgEvidence` protocol + direct-edge implementation). |
| `src/semgen/snomed.py` | extend | Loads non-IS-A inferred relationships (attribute, destination, group) and MRCM attribute-domain rows on demand; `relationships(c)`, `mrcm_attributes()`. Lift behaviour unchanged. |
| `src/semgen/anchor.py` | new (T8b) | Fallback chain and `anchor_report.tsv`. |
| `src/semgen/operators/` | change | `concept_lift` (unchanged), `normative_bucketing`, `attribute_deletion`, `attribute_aggregation`, `motif_deletion`, `motif_aggregation`. |
| `src/semgen/order.py` | extend (T10) | Bundle-level identity-map proof (§4.8). |
| `src/semgen/lattice.py` | rewrite core (T10) | BFS over bundles, U, streaming, budget, best-first. Climb (R8) kept. |
| `src/semgen/metrics.py` | new (T11) | `MetricsHook` protocol and hook loader. |
| `src/semgen/export.py` | extend | Run header (sources, licences), `termination.json` (U first), `candidates.jsonl` (streamed), `edges.jsonl`, `blocked.jsonl`, `metric_deltas.jsonl`, `anchor_report.tsv`, `kg_excluded.jsonl`, `bucket_log.jsonl`. |
| `src/semgen/viewer.py` + `viewer/template.html` | new (T13) | `python -m semgen view RUN_DIR --out FILE` fills the existing viewer template (§3.4) from run files. |
| `tests/support/matcher.py` | extend | Understands `IntervalUnion`, `conj`, dates, merged nodes; relation equality. |

### 3.2 Data sources (all pinned; the version goes into the run header)

| Source | Pin | Used for | If missing |
|---|---|---|---|
| SNOMED CT International RF2 20260201 | path + release (existing) | lift, D1, A2 definitions, Due to, LCS | run fails |
| SNOMED → ICD-10 extended map (in RF2) | refset (exempt) | PhecodeX gate, phecodex floor | merge blocked (`unmapped`) |
| PhecodeX commit `6c5c6f78…` | sha256 per file (existing) | merge gate, phecodex floor | merge blocked |
| Mayo `refrange.sqlite` | path + sha256 | bucketing (Mayo branch) | unbucketable |
| LOINC → Mayo map (U6) | path + sha256 | test selection | unbucketable (today) |
| UCUM essence XML | path + version + sha256 | unit conversion | units not convertible |
| OptimusKG v3.2 (`nodes/disease`, `nodes/phenotype`, `nodes/drug`, `edges.parquet`) | DOI + version + sha256 per file | D2, D3, guards, coverage column | D2/D3 blocked (`kg_unavailable`) |
| KG profile | sha256 | role binding | run fails |
| HIPAA Safe Harbor file | sha256 | age cap | run fails |
| Attribute definitions | sha256 | concept dependence | all attributes dependent |
| Closure rules (U3) | optional path + sha256 | A2 | A2 off |

Measured OptimusKG v3.2 sha256: `edges.parquet 4a101918…727af`, `nodes/disease 5a8a8bd2…9c20ac5d`, `nodes/phenotype 79fe6582…1a210dba`, `nodes/drug 2b0d2217…69c2b`. Full values go into config in T7.

### 3.3 Data flow

```
bundle JSON ──load──► MotifBundle (FSN resolution, A4 split, structural checks)
                          │
       sources ──────────►│  GenContext{hierarchy, floors, refranges, kg, attrdefs, anchors, hook?}
                          ▼
               anchor finding (report only) ──► anchor_report.tsv
                          ▼
     size U ──► termination.json (U, written first)
                          ▼
  BFS frontier ─► operators (6) ─► guard ─► check_order ─► dedup by hash ─► candidates.jsonl (streamed)
        ▲                                                         │
        └──────────── next frontier ◄────────── edges.jsonl, blocked.jsonl, metric_deltas.jsonl
                          ▼
     first frontier measured ─► fits? exhausted : best-first ─► budget_limited
                          ▼
                 per-node climb (R8) ─► root proof over all candidates ─► termination.json (final)
```

### 3.4 Lattice viewer (existing; reused)

**Which viewer.** The workspace search found the viewer you used: the Claude artifact **"Semgen Lattice Walkthrough"** (claude.ai/artifact/AaZMUvPPFaAZwWP9s4sLJE, updated 6 Nov). It shows depth columns, operator colours (`--op-lift`, `--op-attr`, …) and change records. It is `template_v8.html` with a `__DATA__` placeholder, filled by `gen_feat.py` and `merge.py` from an earlier session's scratchpad. None of these is in the repo.

**Input format kept.** The embedded JSON `D` has `header, labels, motifs, boundary, groups, sources, overview, results, funnel`. Each `motifs[id]` carries `root, candidates{hash: {hash, depth, origin, motif, root_proof, path}}, edges[{parent, child, changes[], guard, order, trace}], depth1, depth1_blocked, ops, termination, summary`. `changes[]` items are semgen ChangeRecords (`op, target, field, before, after, evidence`). T13:
1. copies the template into `viewer/template.html`;
2. adds `src/semgen/viewer.py`, which rebuilds `D` from a run directory with the same keys (new keys are additive only: `meaning`, `rule_id`, `source`, `members`, `kept_member_id`);
3. adds the five new operators to the template's `OPS`/`OPN`/`OPSHORT`/`OPCOL` maps. The old operator names stay, so earlier data still renders.

`--depth` filters what the viewer shows. A test builds `D` from a fixture run and checks the key set against the template's reads.

---

## 4. Operators: legality, proof, evidence

Shared rules: operators are pure. They never touch absent nodes, the patient node or context-role nodes. They return `moves` and `blocked`. Every move is re-checked by `guard` and `check_order`, which trust nothing the operator says.

### 4.0 Concept lift (unchanged)

Exactly as on the branch: one direct parent per move, the floor policy (`snomed_boundary` default, `phecodex` selectable), blocks on value or dependent attribute (R5), and the climb (R8). The only change is the source of `attr_is_concept_dependent`: it now reads the attribute-definitions file (P4) instead of `attribute_flags`. Any attribute not declared `about: patient` counts as dependent, as before.

### 4.1 Normative range bucketing (T3, T4)

**Range source, in order.**
1. **Range on the result.** `Node.reference_range` (FHIR `referenceRange` / OMOP `range_low/high`) with `low/low_op`, `high/high_op`, `unit`, `type` and `applies_to {sex, age_min_days, age_max_days}`. Ranges are filtered by the bundle subject's sex and age, and only `type` normal or unset is kept. More than one surviving range that is not identical → unbucketable (`ambiguous_result_range`).
2. **Mayo**, read only from `refrange.sqlite`:
   - The node's `loinc` maps to (mnemonic, analyte) through the approved map (U6). No map entry, or no `loinc` → unbucketable (`no_loinc_map`).
   - `tests.result_kind` must be `numeric_ranges`.
   - Rows are selected by: sex equal or `any`; `age_min_days ≤ age < age_max_days`, with nulls open; unit equal or UCUM-convertible, skipping a null unit; confidence `high`, `medium` only if `mayo.allow_medium_confidence`, never `low`.
   - Any row of the test with a non-empty `condition` → unbucketable (`conditional_ranges`).
   - Subject sex unknown → only `any` rows; subject age unknown → only rows with both age bounds null.
3. Otherwise unbucketable (`no_range_source`). An unbucketable value can only be kept or deleted.

**Buckets.**
- **N** is the `category = 'reference'` band; **L** is everything below it, **H** everything above. `low_op`/`high_op` set each end's open or closed state.
- More than one distinct `reference` band after selection → unbucketable (`ambiguous_reference`).
- `below_limit` or `low_text` set → N is open below and no L is built.
- Bands of other categories become finer buckets only if they are laminar with L, N, H and with each other (pairwise nested or disjoint, by interval containment). Any other band is dropped and logged in `bucket_log.jsonl`.
- No LL/HH.
- **Chain** for a value v: finest band containing v → each enclosing band → A = L ∪ H (an `IntervalUnion`, only when v is in L or H) → deleted. Each step strictly contains the previous one.
- **Result range and Mayo disagree** (both available, different finest bucket): my call, shared parent = the first chain level that both chains reach (N, L, H or A). Its interval is the hull of the two sources' intervals for that level, which is a superset of both, so containment still holds. If the only shared level is "deleted", only deletion is offered.

**Legality.** The node is present, not the patient, not context, its value is a point (or already a bucket of this chain), and its unit equals the range unit or converts. Converted values are compared in the range's unit, and the bucket is stored in the range's unit.

**Proof.** The S′ interval (or union) contains the S value: interval containment in `check_order`.

**Evidence.** `source: result_range | mayo`. For Mayo: `mnemonic, analyte, range_ids[], pdf_page[], raw[], confidence[], dataset_sha256, loinc_map_sha256`. Always `bucket_label, chain_position, rule_id: bucket.<level>`, and `meaning: generalized`.

### 4.2 Attribute deletion (T5)

**Deletes (one per move):**
- a value (raw or bucketed);
- an attribute declared `about: patient`;
- any date in `Node.dates` or `Edge.dates`;
- an edge's time window;
- an ordering edge, but only once its window is gone. An ordering edge is one whose relation is `kind: ordering` in the format definitions.

**Never:**
- perturbs or shifts a value or date;
- touches absent, patient or context nodes;
- deletes an attribute that is `node_concept` or undeclared (R6; `Blocked(..., "concept_dependent_attr")`);
- deletes an ordering edge if that would leave a node unreachable from `P` (`would_orphan`).

**Proof.** Removing a constraint: attributes, dates and windows absent in S′, edge set a subset. Checked by `check_order`.

**Ranking tag.** `redundant_given: {source, edge}` when the KG (manifestation edge, anchor → the finding's KG phenotype) or SNOMED (finding defined with an attribute whose target is the anchor or its ancestor) links the anchor to the node that holds the deleted quantity. It ranks only and never changes legality.

**Evidence.** `rule_id: delete.value | delete.attr | delete.date | delete.window | delete.ordering`, `meaning: generalized`.

### 4.3 Attribute aggregation (T6)

| Rule | When | Result | Proof | Meaning |
|---|---|---|---|---|
| **A1** | ≥ 2 present non-anchor Observable nodes with the **same SNOMED code** (the observable key), all valued, all without attributes. A LOINC Groups cross-check is reported as `unavailable` unless a LOINC Groups file is pinned. | One node keeps the **first member's id** (sorted by id). Its value is either the union of the members' current values (the set of buckets hit, or the raw points) or the hull (min–max) interval. Two separate moves; never a mean or the latest value. Other members and their edges are deleted. `members[]` lists all ids. | S′ ids are a subset; the kept node's value contains the first member's value. | generalized ("at least one result of this analyte in these buckets / this interval") |
| **A2** | A present valued Observable node O plus a present Finding node F whose inferred SNOMED definition has `Interprets` → O's code or an ancestor of it, **and** the pinned closure rules (U3) state that the builder derives F from O. Without closure rules, A2 is off (`Blocked(..., "a2_no_closure")`). | O is deleted; F kept. | Subset. | **kept** (relative to the closure) |
| **A3** | A node whose `derived_from` lists present nodes. | Inputs deleted; the derived node kept. | Subset. | generalized |
| **A4** | A node coded with an OMOP concept that has a "Maps to value" relationship. | **Load-time normalisation** (approved): splitting adds a node, so it cannot be a lattice move. The loader splits it into measurement + value before the root is built. The split is recorded in the loaded bundle's `provenance.normalisations[]` (rule `A4`, source vocabulary and version, original node, resulting nodes), which is exported with the run header. Without a pinned OMOP vocabulary (`CONCEPT_RELATIONSHIP`), A4 is off. | n/a (root is the normalised bundle) | — |

`Interprets` and `Has interpretation` are bound through `config/snomed_profile.yaml` (G1d) and checked against the MRCM file; they are never typed in code.

Each merge records `members[]`, `rule_id: agg.A1.union | agg.A1.hull | agg.A2 | agg.A3`, and `source` (SNOMED release, closure-rules sha256, or record).

### 4.4 Motif deletion (T7, T8)

**KgEvidence interface.**
```
class KgEvidence(Protocol):
    def manifestations(self, disease_kg_id) -> list[KgEdge]     # direct DIS-PHE edges, role=manifestation
    def indications(self, drug_kg_id, disease_kg_id) -> list[KgEdge]
    def contraindications(self, drug_kg_id, disease_kg_id) -> list[KgEdge]
    def adverse_reactions(self, drug_kg_id, phenotype_kg_id) -> list[KgEdge]
    def disease_parents(self, kg_id) -> list[str]               # DIS-DIS PARENT, from = parent
    def phenotype_descendants_or_self(self, kg_id) -> set[str]  # PHE-PHE PARENT, downward
```
Only direct typed edges. KG path length belongs to another team, who will plug into the same interface.

| Rule | Condition | Meaning | Evidence |
|---|---|---|---|
| **D1** | Present nodes X, Y (neither absent, anchor, context or patient) with X's code strictly under Y's in SNOMED IS-A → delete Y. | kept (closure) | IS-A path X → … → Y |
| **D2** | The anchor's KG disease (the anchor itself) has a manifestation edge to phenotype p, with frequency **obligate** and `qualifier_not` false, where p is the patient finding's KG phenotype or a KG descendant of it → delete the finding. | kept (relative to the KG) | edge from, to, label, relation, frequency, evidence_type, sources, references, KG release |
| **D3** | Any other positive manifestation edge, from the anchor or from a KG **parent** of the anchor (tagged `via_parent`), to the finding's phenotype or its descendant. Or an indication edge from a present drug to the anchor's KG disease → delete the finding or drug. | generalized (`expected`) | same fields |
| **D4** | Interface only: delete one candidate, call `evaluate()`, keep it only if utility and disclosure are unchanged at their reporting resolution; re-test accepted deletions in sorted id order. **Off** until U8 (`Blocked(..., "d4_no_hook")`). | measured | metrics before and after |

**Obligate**, my call (still open as O2): the HPO frequency term **HP_0040280** (Obligate, 100%) only. Case-count fractions such as `1/1` or `15/15` are observation tallies, not an obligate claim, so they count as D3. The term id is not in code; it is read from the KG profile as part of the schema binding (exemption G1 d).

**Guards (always block):**

| Guard | Reason |
|---|---|
| the anchor, absent nodes, patient, context | `protected` |
| a node carrying a value, or an `about: patient` attribute (delete it first). `node_concept` attributes go with the node. | `carries_value` / `carries_attr` |
| an unmapped or ambiguous node (P6), including the anchor's own mapping | `unmapped` |
| a drug with a contraindication edge to the anchor | `contraindicated` |
| a finding when another present drug has an adverse-reaction edge to it | `competing_adr` |
| while drugs are unmappable (U5), a finding **only when the bundle actually contains a present drug node**, because the competing-explanation check cannot run (approved; fail closed). Bundles without a drug node are unaffected. | `drug_map_missing` |
| drug rules (indication, contraindication) | `drug_map_missing` |
| edges with `relation_conflict = true` are invisible to the interface and logged | — |

**Proof.** Subset of node ids, and incident edges are removed with the node. Remaining nodes stay reachable from `P`, or the move is blocked (`would_orphan`).

### 4.5 Motif aggregation (T9)

1. **Gate.** Two motifs of one bundle, each anchor mapped SNOMED → ICD-10 → PhecodeX. They may merge only if the sets of phecodes truncated to **integer level** intersect; this also covers finer shared codes, which imply a shared integer code. An unmapped anchor → `Blocked(..., "unmapped")`. Sharing only a top category does not count. OptimusKG and PrimeKG groupings are not read.
2. **Label.** `M` = all minimal common SNOMED ancestors of the two anchor codes. Each m ∈ M must be **reachable by an accepted concept-lift climb from both anchors** under the active floor policy (my reading of "passes the floor policy"). If any m fails, the merge is blocked (`lcs_outside_floor`, with the failing step). The merged node keeps the first anchor's id (pair sorted by motif hash) and `code = min(M)`, `conj = M − {min}`. It records `members = [anchorA, anchorB]` (with their codes), `label` = the conjunction of all minimal common ancestors (codes and FSNs), and `kept_member_id`. The candidate export and the ChangeRecord both state which member's id was kept. A1 merges record the same three fields.
3. **Edges.**
   - An edge is shared when both motifs have an edge with equal `(rel, prov)` from the corresponding source to targets of equal `type` and `role`, matched one-to-one. My call: if more than one candidate matches, the edge counts as one-sided.
   - A shared edge's target becomes the LCS of the two targets through the same floor rule. If that fails, the edge is dropped (dropping is sound; the anchor rule is stricter by SPEC).
   - Every node and edge of motif B, and every one-sided edge of A, is deleted. One-sided edges are never re-attached.
4. **Order.** More than two motifs merge pairwise in hash order. Each merge is one move, so the lattice holds every merge combination.
5. **Export.** A merged node carries `semantics: "at least one condition under this ancestor"` in the candidate JSON.

**Proof.** The merged node keeps anchor A's id. A's code is under every code in `M`, so the code condition holds. The other ids are a subset and the edges a subset. The identity map stays one-to-one.

**Evidence.** `phecodes_shared[]` with level, `lcs[]`, the climb path per member, `members[]`, `rule_id: agg.motif`, and `meaning: generalized`.

### 4.6 Anchor finding (T8b; reporting only, never switches)

1. **record.** The bundle's `record` block (FHIR `Encounter.diagnosis` with `use` discharge or billing and `rank` 1; or OMOP `condition_status_concept_id` equal to the principal-diagnosis concept). Concept ids are matched through the bundle's own record, not typed. Absent on real data today (U2).
2. **snomed.** For present condition nodes X, Y in the bundle, Y explains X when X's inferred definition has the **Due to** attribute with target Y or an ancestor of Y. The anchor is the unique node that no other node explains and that explains at least one. A tie or no link falls through. Due to is bound through `config/snomed_profile.yaml` and checked against MRCM (G1d).
3. **producer.** The producer's anchor, `confirmed: false`.

`anchor_report.tsv` columns: `bundle, motif, producer_anchor, expected_anchor, derived_anchor, anchor_source, evidence, optimuskg_coverage, differs`. The lattice always uses the producer's anchor.

### 4.7 Lattice (T10)

- **Search.** BFS over all six operators with global dedup by bundle hash, so a lattice node is a set of changes (combinations, not permutations). The R8 per-node climb is kept.
- **Upper bound U**, computed before search and written first to `termination.json`. It is the product over independent dimensions:
  - per liftable node, 1 + the size of its accepted ancestor set (from the climb's reachability);
  - per value, 1 + the chain length (the extra 1 for deleted);
  - per deletable attribute, date, window or ordering edge, 2;
  - per deletion candidate, 2;
  - per A1 group, 3 (keep, union, hull); per A2/A3 pair, 2;
  - per mergeable motif pair, 2.
- **Streaming.** Candidates are appended to `candidates.jsonl` in deterministic BFS order. Memory holds the hash set and the frontier only.
- **Budget**, measured after the first frontier:
  - bytes per candidate on disk (file growth) against free disk (`shutil.disk_usage`);
  - bytes per in-memory entry against memory. Approved for both macOS and Linux: the memory budget is physical memory (`SC_PHYS_PAGES × SC_PAGE_SIZE`) minus semgen's own peak RSS (`resource.getrusage`, normalised for the platform's unit: bytes on macOS, KiB on Linux);
  - optional `--time-budget` seconds.

  If U fits, the status is `exhausted`. Otherwise the search switches to best-first by information loss, ordered by (number of `meaning: generalized` changes, total changes, hash), and the status is `budget_limited`.
- **Measured numbers** (free disk, physical memory, peak RSS, bytes per candidate, seconds per candidate, projected cost of U) are recorded in `termination.json` under one key, `measured` (approved).
- **Determinism, ruling** (needed because those numbers differ between runs): the byte-identity check C11 compares every output file byte for byte, except that the `measured` object in `termination.json` is ignored. Everything else in `termination.json` (U, status, counts, axes) must match. The test `test_determinism.py` and the smoke-test command strip `measured` before comparing. If this ruling is wrong, the alternative is a separate `measured.json` and a plain `diff -r` of the rest. The fit decision for the fixtures is far from any limit. With `--time-budget`, byte-identity of the candidate set is not promised.
- `--depth` filters display (viewer, CLI summary) only.
- The root proof runs over every candidate, as today.

### 4.8 Order checker, extended

`check_order(S, S′)` on bundles:
- **ids:** S′ node ids ⊆ S node ids;
- **per node:** type, role and polarity equal, and context code equal;
  - present: S′ `code` and every `conj` code subsume S's `code` (and S's `conj`, if S's node is itself merged);
  - absent: unchanged (no change allowed);
  - value: S′ `Interval | IntervalUnion` contains S's;
  - attrs and dates: S′'s are a subset of S's, each attr contained, each date equal;
- **edges:** S′ edges ⊆ S edges by key, with **equal** `rel`, equal `prov`, window contained or removed, and dates a subset;
- **merged node:** it keeps one member's id, so the checks above are the "maps to one member" proof;
- **anchors:** each S′ motif part's anchor is an S node id.

### 4.9 Metrics hook (T11)

```
class MetricsHook(Protocol):
    def evaluate(self, bundle: MotifBundle) -> Mapping[str, int | float | str]: ...
```
Loaded with `--metrics-hook module:attr`; semgen ships no implementation. `metric_deltas.jsonl` has one row per lattice edge: `parent, child, op, rule_id, meaning, change, before, after`. `before`/`after` are null without a hook. Per-operator series along root-to-leaf paths are derivable from `edges.jsonl` and are written as `metric_series.jsonl` when a hook is present.

---

## 5. Edge cases

| Case | Behaviour |
|---|---|
| Absent node (M2 "no T1DM") | No operator proposes a move on it; `guard` rejects any change; the matcher keeps closed-world negation. |
| Value in a unit neither equal nor UCUM-convertible to any range | unbucketable (`unit_not_convertible`) |
| Value exactly on a band boundary | `low_op`/`high_op` decide; the boundary belongs to exactly one band |
| Several `reference` bands survive selection | unbucketable (`ambiguous_reference`) |
| Finer band straddles the N boundary | dropped, logged to `bucket_log.jsonl` |
| Mayo test has any condition row | unbucketable (`conditional_ranges`), even if the patient is outside the condition |
| Subject sex or age missing | only `any`-sex rows / rows with null age bounds |
| Result range and Mayo disagree | shared chain level, hull interval (§4.1) |
| Undeclared attribute | dependent: blocks lift; deletable only with the node |
| Ordering-edge deletion would orphan a node | blocked (`would_orphan`) |
| A1 group containing the anchor or a node with attributes | blocked |
| A1 members already bucketed from different sources | union is allowed only within one unit; mixed units → blocked |
| KG node claimed by two SNOMED codes, or SNOMED code mapping to two KG nodes of the same type | unmapped |
| Float-string id not of the form `<digits>.0` | rejected, logged |
| `relation_conflict = true` | excluded, logged (pantoprazole → duodenal ulcer is one such edge) |
| KG phenotype only on a subtype of the anchor | not used (entailment direction) |
| Polyhierarchy LCS with several minimal ancestors | conjunction; each must pass the floor rule |
| Merge where only some minimal ancestors pass the floor | blocked (no partial conjunction) |
| Merge of a bundle of one | not proposed |
| Node ids colliding across motifs | namespaced by the loader (`<motif_id>.<node_id>`) |
| Two moves reaching the same bundle | one lattice node, both incoming edges kept |
| U overflows practical size | budget path; status `budget_limited`; never silently truncated |
| `--time-budget` given | byte-identity not promised (documented) |

---

## 6. ADRs (T13)

ADR-0001 remove temporal coarsening · 0002 remove relation relaxation · 0003 remove edge removal · 0004 remove range coarsening and ladders · 0005 concept dependence from attribute definitions, not SNOMED slots (Phase 0 b facts) · 0006 normative bucketing (Mayo LOINC gap, extractor bugs, U1) · 0007 attribute deletion · 0008 attribute aggregation (A2 closure, A4 at load time) · 0009 KG layer and profile ((label, relation), float ids, relation_conflict, type-matched mapping) · 0010 motif deletion (obligate definition, drug block, ADR fail-closed) · 0011 motif aggregation (integer-level gate, floor-reachable LCS) · 0012 anchor finding without OptimusKG (Phase 0 e) · 0013 dynamic lattice sizing (removal of `max_depth` and `max_candidates`) · 0014 hardcoding exemptions.

---

## 7. Phase 0 results

All checks are read-only; scripts were kept in the session scratchpad. SNOMED release 20260201 (International), PhecodeX commit `6c5c6f78…`, OptimusKG doi:10.7910/DVN/IYNGEV v3.2 (latest; released 2026-09-09), Mayo `refrange.sqlite` sha256 `3edbad89…a4107`.

### 7.1 a. Ranges

**7.1.1 Patient graph.** 1,826 records in `All_data/` (5 sites); 14,156 record edges. Record-edge fields: `code_seen, current, from, relation, resource, route, source, status, to, time, exposure, end`. **No value, unit, referenceRange, range_low/high, Encounter.diagnosis use/rank, or condition_status.** The semgen motif format has no range field today.

**7.1.2 Mayo LOINC.** `tests.jsonl`: 0 of 3,765 tests carry a LOINC; the word "LOINC" appears nowhere in the 5,885-page PDF. The online catalog appears to publish result LOINCs (search snippet: ALT 8362 → 1743-4), but its pages return HTTP 403 to automated fetches.

**7.1.3 Rows per fixture measurement (as if a LOINC map existed), and extractor bugs for your Mayo repo**

| Measurement | Mayo test | Rows the T3 rules select | Reason |
|---|---|---|---|
| M1 LVEF 38 % | none | none | echo measurement; no test: **unbucketable** |
| M2 eGFR 42 mL/min/1.73m2 | CRTS1, p.1682–1683 | **none** | CRTS1-11 `ESTIMATED GFR`, any sex, age ≥ 6574.5 d, `>= 60`, unit `mL/min`, **medium**: fails the confidence default and the unit check. Rows 12–16 (G2 `>=60 <=89`, G3a `>=45 <=59`, G3b `>=30 <=44`, G4 `>=15 <=29`, G5 `<15`): medium, null unit (skipped), `category = reference` (five overlapping N bands → would be `ambiguous_reference`). |
| M4 ALT (now 145 U/L) | ALT, p.233 | **none** | `result_kind = not_established`, 0 range rows. The page prints Males ≥1 y 7–55 U/L, Females ≥1 y 7–45 U/L. |
| BMI 41 | none | none | no BMI rows (4 text matches are parse noise from VEDOZ/VEDOL p.5697/5701) |

Extractor bugs (to fix in the Mayo repo; semgen does not work around them):

| # | Test, rows, page | Bug |
|---|---|---|
| B1 | ALT (8362), p.233 | Tagged `result_kind = not_established` with 0 rows. The sentence "Reference values have not been established for patients who are <12 months of age" overrides the printed ≥1-year ranges (M 7–55 U/L, F 7–45 U/L). |
| B2 | CRTS1 rows 12–16, p.1682 | KDIGO G2–G5 stages tagged `category = reference` instead of the stage names, analyte set to the stage label, null unit. |
| B3 | CSTCE rows 4–8, p.1753 | Same as B2: stages labelled `2, 3A, 3B, 4, 5`, `category = reference`, null unit. |
| B4 | CRTS1-11, p.1683 | Unit `mL/min`; the page says `mL/min/BSA` (conventionally `mL/min/1.73m2`). |
| B5 | CSTCE-3, p.1754 | Same unit truncation as B4, and `category = "/BSA (body surface area"`, which is unit text parsed into the category. |

Dataset-wide: 10,694 high / 6,736 medium / 1,508 low rows. 213 of 1,699 `numeric_ranges` tests have condition rows, and these are always unbucketable under T3.

**Non-nested bands.** For the fixtures no rows are selected, so there is nothing to test for nesting. On the as-if rows, the CRTS1 G-stages would be pairwise disjoint but all tagged `reference`, which is the bug above.

### 7.2 b. SNOMED

| Concept | Inferred relational slots |
|---|---|
| Left ventricular ejection fraction 250908004 | none (IS-A only) |
| Glomerular filtration rate 80274001 | none |
| Alanine transaminase in serum 364571000119101 | Component → Alanine aminotransferase (substance); Direct site → Serum specimen |
| Body mass index 60621009 | none |
| Age at diagnosis 423493009 | none |
| Body weight 27113001 / Measured body weight 363808001 | Property → Mass; Time aspect → Single point; **Inheres in → Entire body as a whole (body structure)** |
| Weight loss (amount) 363806002 | none |
| "cumulative dose" | **no concept** (searched FSNs; nearest are radiation doses and insulin dose) |

| Definition check | Result |
|---|---|
| Obesity 414916001 | Interprets → **Measured body weight** 363808001; Has interpretation → Above reference range. **Not BMI.** |
| Body mass index 40+ – severely obese 408512008 | g1 Interprets → **Body mass index** 60621009, Has interpretation → Increased; g2 Interprets → Measured body weight, Has interpretation → Above reference range |
| Weight decreased 262285001 | Interprets → Weight loss (amount); Has interpretation → Decreased relative to previous |
| Fever 386661006 | Interprets → Body temperature; Has interpretation → Above reference range |
| Due to links among bundle conditions (M1–M4, meningitis, duodenal, typhoid, obesity) | **none**. `Due to` is one of the 127 attributes in the MRCM attribute-domain file. |

### 7.3 c. PhecodeX (SNOMED → ICD-10 → PhecodeX)

| Concept | ICD-10 | Phecodes |
|---|---|---|
| Ulcer of duodenum 51868009 | K26.9 | GI_513, GI_513.3 |
| Duodenitis 72007001 | K29.8 | GI_522, GI_522.8 |
| Meningitis 7180009 | G03.9 | NS_320 |
| Fever 386661006 | R50.9 | SS_805 |
| Headache 25064002 | R51 | NS_331 |
| Typhoid fever 4834000 | A01.0 | ID_001, ID_089, ID_089.1 |
| Weight decreased 262285001 | — | none (unmapped) |
| Obesity 414916001 | E66.9 | EM_236, EM_236.1 |
| BMI 40+ 408512008 | E66.8 | EM_236, EM_236.1 |
| DM2 44054006 / DM1 46635009 | E11.9 / E10.9 | EM_202, EM_202.2 / BI_181, EM_202, EM_202.1 |
| CKD 709044004 | N18.9 | GU_582, GU_582.2 |

| Pair | Shared phecodes (level) |
|---|---|
| duodenal ulcer – duodenitis | **none**: merge blocked; LCS would be Disorder of duodenum 52182008 |
| meningitis – fever, meningitis – headache, typhoid – weight decreased, NSCLC-EGFR – ILD, DM2 – CKD | none |
| DM2 – DM1 | EM_202 (integer) |
| obesity – BMI 40+ | EM_236 (integer), EM_236.1 (first decimal) |

### 7.4 d. OptimusKG v3.2

**Edge labels.** 27 node-type labels, 67 (label, relation) pairs. The pairs the profile uses are DIS-PHE PHENOTYPE_PRESENT 157,144; DRG-DIS INDICATION 58,174; DRG-DIS CONTRAINDICATION 11,379; DRG-DIS OFF_LABEL_USE 827; DRG-PHE ADVERSE_DRUG_REACTION 574; DRG-PHE INDICATION 1,028; DRG-PHE CONTRAINDICATION 8,278; DIS-DIS PARENT 47,892 (from = parent); PHE-PHE PARENT 26,121. The full list is in the Phase 0 output and will be stored as `tests/fixtures/kg/labels_v3.2.txt`.

**`snomed_concept_ids` coverage.** 1,073 of 36,753 disease nodes and 289 of 19,341 phenotype nodes carry any. Values are float-strings. Drug nodes have the field absent.

| Fixture concept | KG nodes via `snomed_concept_ids` | Type-matched (P6) |
|---|---|---|
| Malignant neoplasm of breast | MONDO_0007254 | Disease ✓ |
| DM2 / DM1 | MONDO_0005148 / MONDO_0005147 | ✓ / ✓ |
| CKD | EFO_0003884 | ✓ |
| NSCLC with EGFR mutation | — | unmapped |
| Interstitial lung disease (disorder) | HP_0006530 (Phenotype) | **unmapped** (disorder needs a Disease node) |
| Rheumatoid arthritis | EFO_0000685, HP_0001370 | Disease EFO_0000685 ✓ |
| Meningitis | MONDO_0021108, HP_0001287 | Disease MONDO_0021108 ✓ |
| Fever (finding) | HP_0001945 | Phenotype ✓ |
| Headache (finding) | — (only in xrefs: HP_0002315) | unmapped |
| Ulcer of duodenum | EFO_0004607 | ✓ |
| Duodenitis | MONDO_0004627 | ✓ |
| Typhoid fever | EFO_0006789 | ✓ |
| Weight decreased (finding) | — (xrefs: HP_0001824, HP_0004325) | unmapped |
| Obesity (disorder) | EFO_0001073, HP_0001513 | Disease EFO_0001073 ✓ |
| BMI 40+ (finding) | — | unmapped |
| all substances and observables | — | unmapped |

**Example edges.**

| Edge | Result |
|---|---|
| meningitis → fever / headache | **no edge.** MONDO_0021108 has 0 PHENOTYPE_PRESENT edges; its KG parents (nervous system disease, encephalomyelitis, CNS disease) have none to these phenotypes; nor do its subtypes. |
| typhoid → weight loss | **no edge.** EFO_0006789 and its parents (salmonellosis, bacterial disease, …) have none. |
| pantoprazole (CHEMBL1502) → duodenal ulcer (EFO_0004607) | DRG-DIS **INDICATION**; sources direct DRUG_CENTRAL, OPEN_TARGETS, indirect CLINICAL_TRIALS; reference_ids NCT01847404, NCT01847417; highest_clinical_trial_phase 1.0; relation_assertions DRUG_CENTRAL: OFF_LABEL_USE, OPEN_TARGETS: INDICATION; **relation_conflict: true** → excluded under P6, and blocked anyway by U5 |
| obligate frequency (HP_0040280) | 37 edges in the whole release |

### 7.5 e. Anchor feasibility (OptimusKG explanatory coverage)

| Bundle | Every condition maps | Unique top | Top = expected anchor | Result |
|---|---|---|---|---|
| M1 | yes | yes (single node, 0) | yes | pass (trivially) |
| M2 | yes | **no** (DM2 0, CKD 0) | no | **FAIL: tie** |
| M3 | **no** (NSCLC-EGFR) | no | no | **FAIL: unmapped** |
| M4 | yes | yes (single) | yes | pass (trivially) |
| meningitis | **no** (headache) | no (all 0) | no | **FAIL** |
| duodenal | yes | **no** (0, 0) | no | **FAIL: tie** |
| typhoid | **no** (weight decreased) | no | no | **FAIL** |
| obesity | yes | yes (single) | yes | pass (trivially) |

The test fails overall, so OptimusKG is dropped as an anchor source (P7). There is no record source (§7.1.1) and no Due to link (§7.2), so **every fixture resolves to `producer`, unconfirmed**, on real data.

### 7.6 Fixtures chosen from the data (for your review before tests; P5)

Each pick follows a stated rule, so it is reproducible.

| Purpose | Selection rule | Pick | Real-data expectation |
|---|---|---|---|
| Motif aggregation, positive | user-named pair; checked: shares an integer phecode, and the LCS is floor-reachable from both anchors | Bundle DM-PAIR: motif A anchor DM2 44054006, motif B anchor DM1 46635009 (both present) | Merge → Diabetes mellitus 73211009 under `snomed_boundary` (both climbs accepted; 122 descendants). Under `phecodex`: blocked, `outside_floor` (44054006 → 73211009). |
| Motif aggregation, negative | SPEC fixture | Bundle DUODENAL: duodenal ulcer + duodenitis (+ pantoprazole on the ulcer motif) | Blocked, `no_shared_phecode` (GI_513 vs GI_522) |
| A2, positive | user-named; checked: finding's inferred definition has Interprets → BMI | Bundle BMI: BMI 60621009 value 41 kg/m2 (with a synthetic result range) + BMI 40+ 408512008 | SNOMED condition **met**; A2 still **off** on real data (`a2_no_closure`, U3). On by synthetic closure rules. |
| A2, negative | SPEC fixture | Bundle OBESITY: BMI 41 + Obesity 414916001 | A2 not applicable: Obesity interprets Measured body weight, not BMI |
| D3, positive | Among PHENOTYPE_PRESENT edges with type-matched, unique mappings at both ends, `qualifier_not` false, `relation_conflict` false (209 edges): the first **three** by (disease SCTID, phenotype SCTID) | Bundle D3-PAGET: Osteitis deformans 2089002 (EFO_0004261) + Bone pain 12584003 (HP_0002653); evidence IEA, TAS; OPEN_TARGETS; no frequency. Bundle D3-TOURETTE: Gilles de la Tourette's syndrome 5158005 (EFO_0004895) + Aggressive behavior 61372001 (HP_0000718); evidence TAS; OPEN_TARGETS. Bundle D3-BBS: Bardet-Biedl syndrome 5619004 (MONDO_0015229) + Reduced visual acuity 13164000 (HP_0007663); evidence PCS; frequency 15/15, 2/2, 9/9 | D3 deletes the finding in each, `meaning: generalized` (n/n fractions are not obligate, O2) |
| D2, positive | the same 209 edges filtered to frequency HP_0040280 | **none exist** | D2 positive is synthetic only |
| D2/D3, negative | SPEC fixtures | Bundles MENINGITIS (meningitis, fever, headache) and TYPHOID (typhoid, weight decreased with a quantified weight-loss value) | No edge (fever, typhoid); unmapped (headache, weight decreased) |
| Drug | SPEC fixture | pantoprazole in DUODENAL | Blocked, `drug_map_missing` |
| A1 | SPEC fixture | Bundle ALT3: three ALT 364571000119101 results with synthetic result ranges | real data: unbucketable (no range); synthetic: one node, set of buckets |
| Bucketing | M1, M2, M4 | LVEF / eGFR / ALT 145 U/L | all unbucketable on real data (reasons in §7.1.3); positives on the synthetic Mayo sqlite and synthetic result ranges |

`expected_anchor` per fixture is the producer's anchor (the authored answer), and every bundle reports `anchor_source: producer` on real data.

---

## 8. Acceptance criteria (CHECKS)

Synthetic data is marked (S); real data is marked (R). Real-data tests carry the pytest markers `snomed`, `phecodex`, `optimuskg` or `mayo`, and skip cleanly when the data is absent. Mayo logic is tested on a tiny synthetic sqlite with the real schema, built from SQL text in `tests/fixtures/mayo/`.

| # | Check | Pass condition |
|---|---|---|
| C1 | Containment | (S) for every lattice edge of every fixture, the child matches ≥ the parent's synthetic patients (test-only matcher). Zero violations. |
| C2 | Bucketing | (S) a bucket appears only from a result range or a `high` Mayo row (`medium` only with the switch), and every Mayo bucket records `pdf_page`, row ids, raw, confidence and dataset sha256. LVEF unbucketable. (R) LVEF, eGFR and ALT unbucketable, with the reasons of §7.1.3. |
| C3 | A1 | (S) three ALT results → one node with an `IntervalUnion` of the buckets hit, or a hull; no mean or latest value anywhere in the output. |
| C4 | A2 | (R) BMI + Obesity: not applicable. BMI + BMI 40+: definition met, A2 off without closure. (S) with closure rules: BMI node deleted, finding kept, `meaning: kept`. |
| C5 | D2/D3 | (S) meningitis bundle with a synthetic KG: fever/headache deleted with the edge recorded and `kept` for obligate, `generalized` otherwise. (R) meningitis and typhoid: no edge or unmapped, as in §7.4. (R) PAGET: Bone pain deleted as D3 with the OptimusKG edge recorded. |
| C6 | Drugs | pantoprazole deletion blocked (`drug_map_missing`) in both (S) and (R); findings in drug-free bundles are not blocked by this guard. |
| C7 | Aggregation | (R) duodenal ulcer + duodenitis blocked, `no_shared_phecode`. (R) DM2 + DM1 → Diabetes mellitus under `snomed_boundary`; blocked under `phecodex`. (S) merged node's export states "at least one condition under this ancestor". |
| C8 | Negation | (S, R) M2: no move in any operator's output changes, deletes or merges the absent node; `guard` rejects a forged one. |
| C9 | Anchor | every bundle has `anchor_source` and evidence; no anchor is switched (lattice anchor = producer anchor); OptimusKG appears only as a report column. |
| C10 | No hardcoding | `test_no_hardcoding.py` passes; every exemption hit is listed in `hardcoding_exemptions.yaml`. |
| C11 | Determinism | two runs on each fixture: every file byte-identical, ignoring only the `measured` object in `termination.json` (§4.7 ruling). |
| C12 | Size | for every fixture, actual candidate count ≤ U, and status `exhausted`. |
| C13 | Invariants | `src/` does not import `tests.support`; existing concept-lift, climb and floor tests pass unchanged (apart from the T1 removals). |

---

## 9. Pending actions before Phase 2

1. Approve the diff summary of the recursive-ancestor work (given in chat), then commit it on `feature/semantic-generalization`.
2. Commit this design doc and `docs/specs/source-methodology.md` as a separate docs commit on the same branch after spec approval. The worktree `.worktrees/motif-simplification` (`feature/motif-simplification`) branches from that commit.

## 10. Open items

| # | Item | Status |
|---|---|---|
| O1 | Identifying `Interprets`, `Has interpretation` and `Due to` | **Resolved**: `config/snomed_profile.yaml`, MRCM-checked (G1d). |
| O2 | **Obligate frequency.** Only HPO term HP_0040280 counts as obligate. Should `n/n` case fractions also count? | Open; the design proceeds with HP_0040280 only. It decides D2 vs D3 (meaning kept vs generalized). The D3-BBS fixture (15/15) would flip to D2 under the other reading. |
| O3 | Lattice viewer | **Resolved**: the existing viewer is reused (§3.4). |

## 11. Approval record (10 Nov 2026)

- Recursive-ancestor work committed as `48f4862` on `feature/semantic-generalization`.
- Approved calls: merged node keeps one member's id and records `members[]`, `label` and `kept_member_id`; A1 set semantics (one result whose value falls in any of the buckets); A4 at load time, with provenance; disagreement → first shared bucket level; merge floor = reachable by accepted lifts from both anchors; drug guard only when a drug node is present (`drug_map_missing`); memory budget = physical memory minus own peak, with measured numbers in `termination.json`; existing viewer reused.
- Rulings made while applying the corrections: C11 ignores `termination.json.measured` (§4.7); the D3 fixtures are the first three by sorted SNOMED id (§7.6); `mayo_loinc_map.csv` and the snomed and KG profiles are exemption entries by file (G1).
