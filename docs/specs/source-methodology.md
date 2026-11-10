Motif Simplification Operators — Methodology & Implementation Plan
10 Nov 2026 · @Suryansh
Summary
After the 10 Nov meeting the generalization step keeps concept lift unchanged and replaces every other operator with five simplification operators, all combined in one dynamically sized lattice.
Status
Operator
What it does
Kept as is
Concept lift
Replace a SNOMED code by an accepted IS-A ancestor (current semgen behaviour, climb included)
New (replaces range coarsening ladders)
Normative range bucketing
Replace a measured value by the reference-range bucket it falls in (low / normal / high, and finer published grades where they exist)
Extended
Attribute deletion
Remove an attribute or value, including every time window and date
New
Attribute aggregation
Merge several attributes that say the same thing into one
New
Motif deletion
Remove a sub-motif that is implied by another (via SNOMED or OptimusKG) or that changes no metric
New
Motif aggregation
Merge motifs that belong to the same larger disease or group into one
Removed
Temporal coarsening
Replaced by deleting the time window (attribute deletion)
Removed
Relation relaxation
Dropped
Removed
Edge (relationship) removal
Dropped; motif deletion takes over the job of removing parts
Two rules hold for every operator: no rule, list, threshold or concept is typed into code or config, and every move must keep S ⪯ S′ (the generalized motif never matches fewer patients). Where a move cannot be proved that way (deletion of an implied part), it is proved against the closure instead, as section 6 explains.
What already exists in semgen and stays
Most of the engine is kept; only the operator set and the object the lattice works on change.
Part
Keep, change or remove
Note
Motif model, loader, FSN resolution, canonical JSON and hash
Keep
The loader gains a motif bundle input (below)
SNOMED RF2 loader and hierarchy API (parents, children, descendant count, semantic tag)
Keep
New per-release tables are added for the new operators
Concept lift, its floor policy, the per-node climb, termination reporting
Keep unchanged
As on the branch today
Attribute removal, including protection of concept-dependent attributes (R6)
Keep, extend
Becomes attribute deletion and also removes time windows and dates
Identity-map order checker, policy guard, dedup, ChangeRecords, export, determinism
Keep, extend
New checks for aggregation and deletion (section 8)
Test-only patient matcher and containment tests
Keep, extend
Must understand buckets and merged nodes
Range coarsening and its YAML ladders (value, attribute)
Remove
Replaced by normative range bucketing
Temporal coarsening and time_ladder
Remove
Replaced by deleting the window
Relation relaxation and relation_parents
Remove

Edge removal and its cascade
Remove
Motif deletion removes parts instead
One structural change. Today the lattice works on one motif. Motif deletion and motif aggregation need several motifs at once, so the unit becomes a motif bundle: every motif of one patient, joined at the shared patient node. A single motif is just a bundle of one, so concept lift and the existing tests keep working unchanged.
Operator 1 — Normative range bucketing
A measured value is replaced by the reference-range bucket it falls in. The range reported on the result wins; otherwise the Mayo Clinic Laboratories reference-range dataset is used. No threshold is typed into code or config: every bound is read from a row.
The source: your Mayo reference-range dataset. It is extracted from the Mayo Clinic Laboratories Rochester 2026 Interpretive Handbook (5,885 pages, current as of 3 Nov 2026). semgen reads only data/refrange.sqlite, which holds three indexed tables.
Table
Rows
What semgen uses
ranges
18,938
mnemonic, analyte, sex, age_min_days / age_max_days, condition, category, low / low_op / high / high_op, below_limit, low_text, unit, confidence, pdf_page, raw
tests
3,765
result_kind: only numeric_ranges (1,699 tests) can give numeric buckets
context
18,569
Not used for bucketing. Its condition tags mean "discussed with", not "has its own range"
The file is pinned by path and sha256 in config, like PhecodeX. It is git-ignored and never committed.
Licence: a blocker for anything beyond personal use. The handbook is © Mayo Foundation. Its terms allow personal, noncommercial use and forbid republishing or use in an organisational system without written consent. The dataset derives from it, so semgen can use it for your own exploration, but Mayo's written permission is needed before team or production use. The run header records source_licences.mayo: permission_required.
Choosing the rows for one measurement. Each step reads a column; nothing is typed.
1. Test and analyte. The dataset is keyed by Mayo's test code (mnemonic), not by LOINC or SNOMED. Phase 0 checks whether tests.jsonl carries LOINC codes; the Mayo test catalog publishes one per test. If it does, the observation maps to the test by its LOINC code. If not, the value is unbucketable, because a hand-made code mapping is not allowed.
2. Sex. Rows for the patient's sex, or any.
3. Age. age_min_days ≤ age < age_max_days, with nulls open-ended.
4. Condition. Rows with no condition apply to everyone. When a test also has condition rows (pregnancy, Tanner stage, fasting, drug monitoring), it is unclear whether the patient belongs to them, so the value is unbucketable (fail closed). The condition text is free text, and matching it to SNOMED is a later step.
5. Unit. The row's unit must equal the result's unit or convert to it through UCUM. A row with a null unit is skipped.
6. Confidence. Only high rows by default; medium only if config says so. low rows are never used: that is where stacked tables can mislabel an analyte.
If no row survives, the value is unbucketable: it can only be kept exactly or deleted.
Building the buckets from the rows. The rows left for one analyte give bands. Their operators (>=, >, <=, <) set each bound's open or closed end directly.
• N is the reference band. L is everything below it and H everything above it.
• Named bands become finer buckets. A band such as "Borderline High" or "Severe deficiency" becomes a finer bucket only if it nests inside L, N or H, or is disjoint from them. A band that partly overlaps another is dropped and logged. The nesting is computed by interval containment, never typed.
• The chain for a value: its finest band → each enclosing band → A (L ∪ H), when abnormal → deleted. Every step is a superset interval, so the existing order checker proves it.
• An unparsed lower end (below_limit, or low_text such as "Undetectable") leaves N open below and builds no L. That is a superset, so it stays sound.
• Critical values (LL / HH) are not built. Mayo's critical-values list is a separate PDF and is not in the dataset.
Lab range first, Mayo second. The dataset notes that Mayo ranges reflect Mayo's own methods and populations. So a reference range attached to the result (FHIR Observation.referenceRange, OMOP range_low / range_high) always wins. When the two put a value in different buckets, the move emits their shared parent.
Every bucketing ChangeRecord carries the mnemonic, analyte, the row ids used, pdf_page, raw, confidence and the dataset sha256. Any bucket can then be checked against the handbook page.
Expected on the test motifs. ESR, MCH and MCHC have no ranges in this handbook. LVEF is an echo measurement, not a lab test, so it should come out unbucketable. eGFR and ALT should be in the handbook. Phase 0 prints the rows actually selected for each.
Operator 2 — Attribute deletion
Any attribute, value, time window or date on a present, non-context node may be deleted in one move. Deletion only removes a constraint, so S ⪯ S′ always holds.
What it deletes:
• a value (after it has been bucketed, or directly);
• a node attribute such as age at diagnosis;
• every date: dates are only ever deleted, never coarsened, matching the HHS Safe Harbor dates rule;
• a time window on an ordering edge. A second move can then delete the ordering itself ("B after A"), since that is also a temporal attribute of the pair.
What it never does:
• It never changes a value without removing it. Perturbation (date shifting, mean replacement) keeps a value just as specific but changes it, which breaks containment.
• It never touches absent nodes. Closed-world negation stays as it is.
• It never deletes a concept-dependent attribute on its own. A cumulative dose means something only for its drug, so it goes only when the whole node goes (motif deletion). Rule R6 stays.
Concept dependence is read from SNOMED, not from a YAML flag. An observable's relational slots (Component, Relative to, Process acts on, Towards, Characterizes) say what it is about. If one points to a concept in the motif, the attribute depends on it; if it only inheres in the person (weight, age), it is independent (SNOMED observable attributes). How SNOMED models "cumulative dose" has not been checked yet. Until Phase 0 shows the slots decide it, an attribute that cannot be classified counts as dependent (fail closed).
Why delete one attribute rather than another is a ranking question, not a legality question. When OptimusKG or SNOMED already links the anchor to the finding (typhoid → weight loss), the quantity on that finding adds no meaning. That deletion is tagged redundant_given: <edge evidence> so the selection step can prefer it. The KG never makes a deletion legal or illegal.
Operator 3 — Attribute aggregation
Several attributes that measure the same thing are replaced by one attribute that each of them implies. Which attributes belong together is read from published code-system files, never from a hand-made list.
Kind
Example
Source that decides it
Merged form
Sound for "any value in bucket" queries?
A1 Repeats of one analyte
Three ALT results
Same SNOMED observable key or same LOINC Group (Component + Property + Time match)
Set of buckets hit, or the min–max interval
Yes. Latest value or mean is not, so neither is offered.
A2 Measurement + the finding that interprets it
BMI 41 and obesity
SNOMED finding defined by Interprets + Has interpretation "above reference range" (finding attributes); the cut-off comes from the record's own range
The finding node; the value is dropped
Yes, if the patient-graph closure also derives the finding from the measurement
A3 Derived value + its inputs
BMI with weight and height
FHIR derivedFrom on the record
The derived value; inputs deleted
Yes (deletion)
A4 Combined codes
"Abnormality of albumin"
OMOP "Maps to value" splits it first
Measurement + value, then A1–A3
Yes
Each merged attribute carries members[], the rule_id, and the source file and version, so the merge can be traced and undone.
Two conditions keep it honest.
• A2 needs the closure to derive the finding. A patient with BMI 41 but no recorded obesity code must still match "has obesity". So the patient-graph builder must add the finding as a derived fact whenever the measurement is above the reference range. Without that, A2 is turned off (fail closed).
• LOINC Groups are Beta. LOINC says users must validate them, so A1 uses the SNOMED observable key first and LOINC Groups only as a cross-check.
The BMI → obesity example was not verified: the public SNOMED server was blocked. Phase 0 checks on the local release that Obesity is defined through Interprets → Body mass index.
A 2026 study found ARX's information-loss scores stayed low (0.074–0.093) while the data was clearly distorted (Kamdje Wabo et al., JMIR Med Inform 2026). So every aggregation is checked by its effect on synthetic cohort counts, not by a loss score alone.
Operator 4 — Motif deletion
A motif or node is deleted when SNOMED or OptimusKG shows it is implied by something the patient still has, or when deleting it leaves every metric unchanged. Deleting a present part only removes a constraint, so S ⪯ S′ always holds; the evidence decides whether meaning is also kept.
OptimusKG gives what this needs. It is Zitnik lab's 2026 successor to PrimeKG (paper, repo): about 191k nodes of 10 types and 21.8M edges of 27 labels, each edge with sources provenance. The edges this operator reads are:
• disease → phenotype PHENOTYPE_PRESENT, with HPO frequency, the NOT qualifier, evidence type and references;
• drug → disease INDICATION, CONTRAINDICATION and OFF_LABEL_USE;
• drug → phenotype ADVERSE_DRUG_REACTION.
Disease and phenotype nodes carry snomed_concept_ids, so patient codes map onto the KG from the data itself. Drug nodes use RxNorm, DrugBank and ChEMBL only, so drug rules wait until a SNOMED → RxNorm map exists (blocked until then).
Three reasons to delete, each with its own evidence.
Reason
Rule
Meaning kept?
Evidence recorded
D1 Subsumed by SNOMED
Two present nodes X and Y with X under Y in IS-A: Y is implied by X, so delete Y
Yes, by the closure
The IS-A path
D2 Entailed by the anchor
A PHENOTYPE_PRESENT edge from the anchor's disease with obligate (100%) frequency, no NOT qualifier, to a phenotype equal to or more specific than the patient's finding
Yes, relative to the KG
Edge id, frequency, evidence type, source, KG release
D3 Expected given the anchor
Any other positive phenotype annotation, or an INDICATION edge from the patient's drug to the anchor (pantoprazole for duodenal ulcer)
No: the motif is only generalized, and is tagged expected
Same fields
D4 Inconsequential
Deleting it changes no utility or disclosure metric
Measured
Metric values before and after
KG paths are not part of this work. How long KG paths may be (shortest paths, avoiding hub nodes) is owned by another team member. Motif deletion reads only direct typed edges between two motif nodes, plus SNOMED IS-A, through one KgEvidence interface. The KG phenotype must equal the patient's finding or sit under it, and the disease must be the anchor itself or one of its parents (weaker, tagged), never a subtype. When the path work is ready, it plugs into the same interface; no operator changes.
What blocks a deletion, always:
• the anchor, absent (negated) nodes, and any node a query names;
• a node that still carries a value or modifier (bucket or delete the value first);
• a CONTRAINDICATION edge to the anchor, which makes the drug informative;
• a competing explanation: another drug in the motif has an ADVERSE_DRUG_REACTION edge to the same finding;
• a missing or ambiguous SNOMED → KG mapping.
D4, the metric test. Delete one candidate at a time, recompute the metrics, and keep the deletion only if utility and disclosure are unchanged. "Unchanged" means the same retrieved cohort or equal discrete scores at the metric's own reporting resolution, so no epsilon is typed. Accepted deletions are re-tested in a fixed order, because nodes interact. Complexity always drops, so it is the thing being reduced, not a metric to hold fixed. D4 needs the metric harness (Nikita's work), so semgen only exposes the interface now.
Binding to the KG schema. The four OptimusKG relation labels are bound to roles (manifestation, indication, contraindication, adverse reaction) in one versioned KG-profile file. On load it is checked against the release's own schema: an unknown or missing label stops the run. That file is a schema binding, not a clinical list.
Whether meningitis or duodenal ulcer actually has these edges in the pinned OptimusKG release has not been checked. Phase 0 queries the Parquet files before any example is shown as real.
Finding the anchor
OptimusKG is tried first, with a feasibility test run on real data before anything is built. If it fails, the anchor comes from the record itself and from SNOMED's own cause links. The producer's anchor is never changed silently.
The feasibility test (Phase 0). For each test bundle:
1. Map every present condition and finding to OptimusKG through snomed_concept_ids.
2. For each mapped disease, count how many other motif nodes it explains through manifestation edges (the D2/D3 rule).
3. Check three conditions, none of which needs a threshold:
    ◦ every condition node maps;
    ◦ exactly one node has the highest count (no tie);
    ◦ that node is the anchor the bundle's author marked as the known answer.
OptimusKG is used to find the anchor only if all three hold on every bundle. Otherwise the reason is recorded and the fallback below is used.
Why the test is likely to fail.
• Mapping gaps. OptimusKG nodes are keyed on MONDO and HPO, and SNOMED ids are only a property on them. Any patient code without one cannot be scored.
• No disease-to-disease cause edges. The relations read here are disease → phenotype, drug → disease and drug → phenotype. Two diseases in one bundle (type 2 diabetes and CKD) cannot be ordered, so both score 0.
• Ties with comorbidity. A patient with several unrelated diseases gets several equal top scores, and there is no principled tie-break.
• Hub bias. Coverage favours broad, heavily annotated diseases, not the one the patient was treated for.
• No research support. No 2021–2026 paper was found that picks a primary diagnosis by KG centrality.
• The wrong kind of fact. "Primary" is a fact about an encounter, recorded by clinicians and coders, not a property of a knowledge graph.
The fallback, in order (deterministic, nothing typed in).
1. The record says it.
    ◦ FHIR Encounter.diagnosis carries a use (admission, billing, discharge) and a rank within each use (HAPI FHIR R4).
    ◦ OMOP condition_status_concept_id takes descendants of "Qualifier for type of diagnosis": admitting, principal and secondary diagnosis (OHDSI THEMIS).
    ◦ The principal diagnosis, or rank 1 of the discharge or billing use, becomes the anchor. Phase 0 checks whether the patient-graph builder keeps these fields.
2. SNOMED says one condition is caused by another. A finding can be defined with Due to (range: event, clinical finding or procedure; clinical finding attributes). If X is defined as Due to Y, or an ancestor of Y, and Y is in the bundle, then Y explains X and ranks above it (diabetic nephropathy → diabetes). The attribute is found from the release's concept-model files, not typed. The node no other node explains, while explaining at least one, is the anchor. A tie falls through to step 3.
3. Neither decides. The anchor set by the motif producer is kept, marked anchor_source: producer, unconfirmed.
Every bundle records anchor_source (record, snomed, optimuskg or producer) and its evidence. When the derived anchor differs from the producer's, the bundle is listed in a report for you to decide; the anchor is not switched. OptimusKG coverage stays as a cross-check column in that report even when it is not used.
Operator 5 — Motif aggregation
Two motifs of one patient that belong to the same disease group are replaced by their least general generalization: one motif whose anchor is the least common SNOMED subsumer of the two anchors, keeping only the parts both motifs share.
1. Are they the same group? PhecodeX decides, SNOMED does not. This follows the earlier split: SNOMED for vertical generalization, PhecodeX for comparing different diseases.
• Each anchor is mapped SNOMED → ICD-10 (International map) → PhecodeX (WHO ICD-10 file), the same pipeline semgen already has.
• The pair may merge only if they share a phecode at integer level or finer. Sharing only one of PhecodeX's 18 top categories does not count (Shuey et al. 2023).
• An anchor with no map is unmapped, so it is never merged (fail closed).
• OptimusKG and PrimeKG disease groupings are reported as a cross-check only. PrimeKG built its groups from a ClinicalBERT similarity cut-off plus manual approval, so it cannot decide a merge (PrimeKG).
2. What the merged motif is.
• The anchor is labelled with every minimal common SNOMED ancestor of the two anchors. SNOMED's logic (EL) always has exactly one least common subsumer (Cerna & Kutsia, IJCAI 2023; Baader 2003). Under polyhierarchy that is the conjunction of all minimal common ancestors, so no tie-break and no score is needed.
• Each label must pass concept lift's own floor policy. A merge can never climb further than concept lift would. If no common ancestor passes, the merge is blocked.
• Only shared parts are kept. An edge stays only when both motifs have it, and its target becomes the least common subsumer of the two targets (both drugs given → their shared drug class, if the lift policy accepts it). Parts only one motif has are dropped.
• More than two motifs merge pairwise in a fixed order (sorted by hash), because a many-way subsumer can grow exponentially.
3. Why it is sound. Map the merged anchor to the fact that motif 1's anchor matched. That fact is under motif 1's anchor, which is under every common ancestor, so the label holds. Kept edges exist because motif 1 has them, and the map stays one-to-one because one fewer fact is required. So every patient matching both motifs matches the merged one: S ⪯ S′. No paper states this lemma; it is derived here, and the test-only matcher checks it on synthetic patients.
The merged node means "at least one condition under this ancestor". That is weaker than two distinct conditions, and the export must say so.
4. What it must not do. It must not re-attach one motif's own edges (duodenal ulcer → pantoprazole) to the merged anchor, which would assert something duodenitis patients may lack. It must not replace symptoms with a disease inferred from them (fever + headache → meningitis): that adds a claim, so it is not a generalization. Symptoms explained by a recorded disease are handled by motif deletion.
Whether duodenal ulcer and duodenitis actually share a phecode has not been checked. Phase 0 looks it up in the PhecodeX files.
Combining the operators into one lattice
All six operators run together on the motif bundle, so the lattice holds every combination of moves, not just concept-lift chains. Its size is worked out from the bundle and the machine, with no depth or candidate number in config.
Each operator proposes moves on the bundle; a move that fails the guard or the proof stops the run loudly, and only proved moves enter the lattice.
Combinations, not permutations. A lattice node is a set of changes. Two moves on different parts give the same bundle in either order, so they share one hash and become one node with two incoming edges. Search is breadth-first over all six operators with global deduplication, exactly as today.
Moves that must come first. These are the existing state-based rules, not a fixed order:
• a node with a value cannot be lifted or deleted until the value is bucketed or deleted;
• a concept-dependent attribute leaves only with its whole node (motif deletion);
• a merged anchor can still be lifted, under the same floor policy;
• absent nodes are never touched by any operator.
Sizing (N9 from the earlier prompt, now covering all operators).
1. Before searching, count each independent dimension of change in the bundle. That is each node's accepted ancestor set, each value's bucket chain plus "deleted", each deletable attribute, each deletion candidate, and each aggregable pair or group. Their product is an upper bound U, written to termination.json first.
2. Candidates are streamed to disk as they are made, so memory holds only the hash set and the frontier.
3. The first frontier measures bytes and time per candidate and compares the projected cost of U with free disk, free memory and an optional --time-budget. If it fits, everything is built (exhausted). If not, the search switches to best-first by information loss, so the most useful part comes first (budget_limited).
The proof, extended. The identity-map checker stays, with three additions:
• deletion: S′'s node ids are a subset of S's;
• bucketing and attribute aggregation: each S′ interval or bucket set contains S's;
• motif aggregation: a merged node records its members, and the checker maps it to one member and checks the label, so the map is still one-to-one.
The proof never trusts the operator.
Meaning is tracked separately from the proof. Every ChangeRecord gets meaning: kept | generalized. kept holds only for D1, D2 and A2 under the closure; everything else is generalized. The next step can then prefer simplifications that keep meaning before ones that loosen the query.
How the metrics change per operation (handoff to the metrics work)
Every lattice edge is exactly one move, so any metric change between parent and child can be attributed to that move. semgen computes no metric itself; it gives the metrics work one hook and one file.
Following the 10 Nov discussion, the metrics fall into two groups:
• kept as specific as possible: soundness, utility or closeness to the original;
• pushed more general: complexity, disclosure risk.
Support (matching patients) is what links the two groups. The direction each operator should move them, by construction or by expectation:
Operator
Support
Complexity
Disclosure
Utility
Soundness
Concept lift
↑ or = (proved)
=
expected ↓
expected ↓
kept (proved)
Normative bucketing
↑ or = (proved)
=
expected ↓
expected ↓, small
kept (proved)
Attribute deletion
↑ or = (proved)
↓
expected ↓
expected ↓
kept (proved)
Attribute aggregation
↑ or = (proved)
↓
expected ↓
= when meaning: kept
kept (proved)
Motif deletion D1/D2
↑ or = (proved)
↓
expected ↓
= expected (meaning kept)
kept (proved)
Motif deletion D3/D4
↑ or = (proved)
↓
measured
measured
kept (proved)
Motif aggregation
↑ or = (proved)
↓
expected ↓
expected ↓
kept (proved)
"Proved" columns are guaranteed by the order proof and checked by the containment tests. "Expected" columns are hypotheses the metrics work should confirm or reject on the plots.
What semgen exports for this:
• an evaluate(bundle) -> metrics hook that the metrics harness implements; semgen only calls it;
• metric_deltas.jsonl: one row per lattice edge with the operator, the change, meaning, and the before and after metric values once the hook is plugged in;
• per-operator series along every root-to-leaf path, so each metric can be plotted against the number and type of moves.
D4 (inconsequential deletion) uses the same hook, so it switches on as soon as the harness exists.
No hardcoding: where every rule comes from
No threshold, concept id, FSN, symptom list, drug list or depth appears in code or config. Every decision reads one of the sources below, and its version goes into the run header.
Decision
Source read at run time
If the source is missing
Concept lift boundary
SNOMED RF2 release (unchanged policy)
Run fails
Bucket bounds
Range on the result (FHIR / OMOP), else the Mayo dataset (refrange.sqlite, pinned by sha256)
unbucketable
Bucket nesting
Computed from interval containment of the bounds
—
Graded scales (CTCAE, KDIGO)
Optional cited data files
Grades not offered
Concept-dependent attribute
SNOMED observable relational slots
Treated as dependent
Same-analyte grouping
SNOMED observable key; LOINC Groups as cross-check
No merge
Measurement ↔ finding
SNOMED Interprets / Has interpretation + the record's range
A2 off
Derived values
FHIR derivedFrom on the record
A3 off
Subsumed node (D1)
SNOMED IS-A closure
—
Explained node (D2, D3)
OptimusKG edges via the KG-profile file, checked against the release schema
Run fails if labels mismatch; else no deletion
Inconsequential node (D4)
Metric harness hook
D4 off
Same disease group
SNOMED → ICD-10 map → PhecodeX
No merge (unmapped)
Merged label
SNOMED least common subsumer + the concept lift floor policy
Merge blocked
Lattice size
Computed upper bound + measured machine budget
—
What remains in config is only which source files to use, their pinned versions and checksums, and the KG-profile file. A test greps src/ and config/ for SCTIDs, FSNs and numeric thresholds and fails if it finds any.
Implementation plan and how to check it
The work is one read-only fact check, then thirteen test-first tasks. Each task is reviewed and approved before the next starts, and nothing is committed until you approve it.
Phase 0 — fact check (read-only, stops for your review).
1. Ranges: whether the patient graphs keep the lab's own reference range per result; whether the Mayo dataset's tests.jsonl carries LOINC codes; and which Mayo rows the selection rules pick for every test measurement.
2. SNOMED, on the local release:
    ◦ the observable slots of the M1–M4 observables and of cumulative dose;
    ◦ whether Obesity is defined through Interprets → Body mass index.
3. PhecodeX: shared phecodes for the test pairs, such as duodenal ulcer and duodenitis.
4. OptimusKG:
    ◦ pin a release;
    ◦ list its relation labels;
    ◦ measure snomed_concept_ids coverage of the motif codes;
    ◦ check that the example edges really exist (meningitis → fever, duodenal ulcer ← pantoprazole, typhoid → weight loss), with their frequency values.
Tasks.
1. Remove temporal coarsening, relation relaxation, edge removal and range coarsening, with their config, tests and README rows. The order checker requires equal relations.
2. Add the motif bundle model, its loader and its canonical hash. A single motif is a bundle of one, and every existing test still passes.
3. Add the reference-range layer: ranges on the result, the Mayo dataset reader (row selection by test, sex, age, condition, unit and confidence), UCUM unit conversion, and nested buckets built from the bands.
4. Add the normative bucketing operator.
5. Add attribute deletion: values, attributes, dates, time windows and ordering, with concept dependence read from SNOMED.
6. Add attribute aggregation A1–A4, each with members[], rule_id and its source.
7. Add the KG layer: the OptimusKG Parquet loader for the pinned release, the KG-profile schema binding and SNOMED → KG node mapping.
8. Add motif deletion: D1–D3, the blocking guards, the D4 interface and the explanatory-coverage report.
9. Add motif aggregation: the PhecodeX gate, the least common subsumer through the floor policy, and shared-edge keeping.
10. Run the lattice over all six operators: bound U, streaming, best-first fallback, the extended order checker and the meaning tag.
11. Add the metric hook and metric_deltas.jsonl.
12. Add synthetic test bundles and patients. Keep M1–M4, and add:
    ◦ meningitis with fever and headache;
    ◦ duodenal ulcer with duodenitis and pantoprazole;
    ◦ typhoid with a quantified weight loss;
    ◦ BMI 41 with obesity;
    ◦ three ALT results.
13. Write the ADRs, the README and a dated methodology amendment.
How to check the results.
Check
Expected result
Containment on synthetic patients
Zero edges where the child matches fewer patients than the parent
Bucketing on M1 LVEF, M2 eGFR, M4 ALT
A bucket only where the result's range or a high-confidence Mayo row exists, with its pdf_page recorded; LVEF unbucketable
Three ALT results (A1)
One attribute holding the set of buckets hit; no mean or latest value
BMI 41 + obesity (A2)
Value dropped and the finding kept, only if Phase 0 confirms the definition
Meningitis bundle (D2/D3)
Fever and headache deleted with their KG edge recorded as evidence, kept or generalized per frequency
Duodenal ulcer bundle
Pantoprazole deletable as D3 once a drug map exists; until then blocked
Duodenal ulcer + duodenitis (aggregation)
Merged anchor = their least common subsumer, only if they share a phecode
Negation (M2)
No operator touches "no type 1 diabetes"
No-hardcoding grep
No SCTID, FSN or numeric threshold in src/ or config/
Determinism
Two runs give byte-identical output
Lattice size
Actual count ≤ U; M1–M4 and the new bundles are exhausted
Prompt for Claude Code
Paste the block below into Claude Code in the semgen repository. It is self-contained and follows the superpowers workflow.
Checked against the superpowers workflow (brainstorm → worktree → plan → subagent execution with TDD → final review → finish branch). The earlier version missed six steps; this version adds them.
Superpowers step
Earlier prompt
Now
Brainstorming writes a spec doc (decisions, architecture, edge cases, acceptance criteria) for approval
Only checked for conflicts
Writes the spec, with Phase 0 facts, and stops for approval
Worktree location asked (project or global)
Not stated
Project-level .worktrees/, with a green baseline test run first
Execution mode asked (subagent or inline)
Implied
Subagent-driven, stated
Plan steps end in a commit
Conflicted with "do not commit"
Commit runs only after you approve that task
Final review dispatches fix subagents for critical and important issues
Review only
Fix subagents, then a re-review and a full test run
Manual smoke test, then merge or PR
Not stated
A smoke-test checklist for you, then the finish options for you to choose
Skills are called by name through the Skill tool. The old /superpowers: slash commands are deprecated. Claude Code cannot open this doc, so export it as Markdown to docs/specs/source-methodology.md in the repo first; the prompt points there.
Goal: upgrade semgen to production quality with a new operator set: normative range
bucketing, attribute deletion, attribute aggregation, motif deletion, motif aggregation.
Concept lift stays exactly as it is. Temporal coarsening, relation relaxation, edge removal
and range-coarsening ladders are removed. The full methodology is in
docs/specs/source-methodology.md; read it first. Use the superpowers skills through the
Skill tool, never the deprecated /superpowers: commands. Follow the phases in order and
stop where it says STOP.

=== PHASE 1: BRAINSTORM (superpowers:brainstorming) ===
The design decisions are already made (SPEC below). Use brainstorming to:
- explore the current code, and run the Phase 0 fact checks (read-only scratch scripts, no
  repo changes);
- list any conflict between the SPEC and the code or data. Do not reopen a decision unless
  evidence contradicts it; then show the evidence and ask me.
- ask me one question at a time only where the SPEC leaves a real choice.
Phase 0 fact checks (report each as a table):
  a. Ranges:
     - Whether our patient graph keeps a per-result reference range (FHIR
       Observation.referenceRange or OMOP range_low/range_high).
     - The Mayo dataset data/refrange.sqlite: whether tests.jsonl carries a LOINC code per
       test.
     - For every fixture measurement, the ranges rows the T3 rules select (mnemonic,
       analyte, sex, age band, condition, category, bounds with operators, unit, confidence,
       pdf_page), and any band that is not nested or disjoint.
  b. Local SNOMED RF2:
     - the observable relational slots (Component, Relative to, Process acts on, Towards,
       Characterizes, Inheres in) for every fixture observable and for cumulative dose;
     - whether Obesity is defined via Interprets -> Body mass index + Has interpretation
       above reference range.
  c. PhecodeX: the shared phecodes, and their level, for duodenal ulcer vs duodenitis and
     every fixture pair.
  d. OptimusKG:
     - pin a release;
     - list all edge labels;
     - measure snomed_concept_ids coverage of the fixture codes;
     - print the example edges with their fields: meningitis -> fever/headache, typhoid ->
       weight loss, pantoprazole -> duodenal ulcer.
  e. Anchor feasibility with OptimusKG, per fixture bundle:
     - map every present condition/finding to OptimusKG;
     - compute explanatory coverage (other motif nodes explained through manifestation
       edges).
     PASS only if all three hold on every fixture: every condition maps; a single top node
     (no tie); and that node is the anchor the fixture marks as the known answer. Report
     which condition failed and why. Also check whether the patient graph keeps FHIR
     Encounter.diagnosis use/rank or the OMOP condition_status_concept_id, and list the
     SNOMED Due to links among the fixture conditions.
Output: docs/specs/2026-11-10-motif-simplification-design.md. It must have these sections:
- context;
- decisions, one per SPEC rule;
- architecture (modules, data sources, data flow);
- each operator: legality, proof, evidence recorded;
- edge cases;
- the Phase 0 results;
- acceptance criteria (the CHECKS below).
STOP for my approval of the spec.

=== PHASE 2: WORKTREE (superpowers:using-git-worktrees) ===
- Project-level worktree .worktrees/motif-simplification on branch
  feature/motif-simplification, from the current head of feature/semantic-generalization.
- Run the full suite there first. The baseline must be green; if not, STOP and report.

=== PHASE 3: PLAN (superpowers:writing-plans) ===
- Write docs/plans/2026-11-10-motif-simplification.md from the approved spec: T1-T13 below.
- Every task has: justification, files, interfaces, and checkbox steps in this order:
  - [ ] write the failing test(s)
  - [ ] run them, verify they FAIL for the expected reason
  - [ ] implement the minimum to pass
  - [ ] run them, verify they PASS; run the full suite
  - [ ] refactor, re-run
  - [ ] commit (ONLY after I approve the task)
- No task depends on a later one.
STOP for my approval of the plan.

=== PHASE 4: EXECUTE (superpowers:subagent-driven-development; NOT inline execution) ===
- One task at a time, never in parallel:
  - a fresh implementer subagent per task, following superpowers:test-driven-development;
  - then a spec-compliance review and a code-quality review by fresh reviewer subagents;
  - fix findings, re-review, and use superpowers:verification-before-completion before
    calling the task done.
- Report per task: diff summary, tests added, the failing-run evidence, the review verdicts,
  and any ruling you made (and what happens if it is wrong). Then wait for my approval and
  commit.

=== PHASE 5: FINAL REVIEW (superpowers:requesting-code-review) ===
- Review the whole branch against the spec, the plan and the CHECKS.
- For Critical and Important findings, dispatch fix subagents.
- Evaluate feedback with superpowers:receiving-code-review: verify a finding before acting
  on it, and push back with evidence when it is wrong.
- Re-review and run the full suite.
- Report: what was built, verification output, remaining Minor items.

=== PHASE 6: SMOKE TEST, THEN FINISH (superpowers:finishing-a-development-branch) ===
- Give me a smoke-test checklist with exact commands, each labelled with where it runs and
  what output to expect:
  - the CLI run on each fixture bundle;
  - opening the lattice viewer;
  - checking one bucketing ChangeRecord against its Mayo pdf_page;
  - checking one motif deletion against its OptimusKG edge;
  - diff -r of two runs.
- After I confirm, present the finish options (merge locally / open PR / keep / discard).
  I choose.

=== SPEC ===
GLOBAL RULES
- NO HARDCODING.
  - No SCTID, FSN, symptom/drug list, numeric threshold, depth or candidate cap in src/ or
    config/.
  - Config holds only source paths, pinned versions, sha256s and one KG-profile file
    (OptimusKG edge label -> role: manifestation, indication, contraindication,
    adverse_reaction).
  - The KG profile is validated against the release schema on load; an unknown or missing
    label stops the run.
  - A grep test enforces this.
- Every move keeps S ⪯ S′, proved by the independent order checker. Every ChangeRecord
  carries the source, version and rule that fired, plus meaning: kept | generalized.
- Deterministic, byte-identical output. Absent nodes are never touched. Closed-world
  semantics, the identity-map proof (extended in T10), guard, R5 and R6 stay. src/ never
  imports the test-only matcher.
- Fail closed: a missing source blocks the move or makes the node unbucketable/unmapped.
  There is never a fallback.
- Licences: the Mayo dataset is (c) Mayo Foundation, personal noncommercial use only.
  - Never commit it; git-ignore its folder.
  - Pin it by path + sha256, like PhecodeX.
  - The run header says source_licences.mayo = permission_required.

TASKS
T1 Remove temporal_coarsening, relation_relaxation, edge_removal, range_coarsening, and
   time_ladder, relation_parents, value_ladders, attr_ladders. The order checker requires
   equal relations. Update ALL_OPERATORS, the README and the tests.
T2 Motif bundle: all motifs of one patient joined at the patient node, with its loader and
   canonical hash. A single motif is a bundle of one; every existing test still passes.
T3 Reference-range layer, in order:
   (1) The range on the result itself, filtered by sex, age and type.
   (2) The Mayo dataset, read only from data/refrange.sqlite:
       - Map the observation to a Mayo test by the LOINC code in tests.jsonl. No hand
         mapping; no LOINC -> unbucketable.
       - tests.result_kind must be numeric_ranges.
       - Select ranges rows by:
         - sex: the patient's sex, or any;
         - age: age_min_days <= age < age_max_days, nulls open;
         - unit: equal or UCUM-convertible; a null unit is skipped;
         - confidence: high by default, medium only if config allows, low never.
       - If the test has condition rows, the value is unbucketable.
   (3) Else unbucketable.
   Buckets:
   - N = category 'reference'; L = below it; H = above it.
   - Other categories become finer buckets only if nested in or disjoint from L/N/H; else
     drop and log them.
   - low_op/high_op set each bound's inclusivity.
   - below_limit or low_text -> N open below, no L.
   - No LL/HH.
   - Chain: finest band -> enclosing bands -> A (L u H) -> deleted.
   - If the result's range and Mayo disagree, emit the shared parent.
   - The ChangeRecord holds mnemonic, analyte, row ids, pdf_page, raw, confidence and the
     dataset sha256.
T4 normative_bucketing operator over T3. Its proof is interval containment.
T5 attribute_deletion (replaces attribute_removal):
   - Deletes values, attributes, every date, every time window, then the ordering edge.
   - Never perturbs a value; never touches absent nodes.
   - Concept dependence comes from the SNOMED observable slots: a slot pointing to a motif
     concept = dependent; inheres-in-person only = independent; unknown = dependent. A
     dependent attribute leaves only with its node.
   - Tag redundant_given when a KG or SNOMED edge links the anchor to the finding. This only
     ranks; it never decides legality.
T6 attribute_aggregation:
   - A1: repeats of one analyte (SNOMED observable key; LOINC Groups as cross-check only) ->
     set of buckets hit, or the min-max interval. Never mean or latest.
   - A2: measurement + the finding that interprets it -> keep the finding, drop the value.
     Only if the closure derives that finding; otherwise A2 is off.
   - A3: FHIR derivedFrom -> keep the derived value, delete the inputs.
   - A4: OMOP "Maps to value" split first.
   - Each merge records members[], rule_id and its source.
T7 KG layer:
   - OptimusKG Parquet loader (pinned release), KG-profile binding, and SNOMED -> KG node
     mapping via snomed_concept_ids.
   - Drug rules stay blocked until a SNOMED -> RxNorm map exists.
T8 motif_deletion:
   - D1: a present node implied by another present node through SNOMED IS-A -> delete the
     ancestor.
   - D2 (meaning kept): a manifestation edge from the anchor's disease with obligate
     frequency and no NOT, to a phenotype equal to or under the patient's finding.
   - D3 (generalized): any other positive manifestation, or an indication edge from a patient
     drug to the anchor.
   - KG evidence: direct typed edges only, through a KgEvidence interface (KG path length is
     owned by another team); IS-A only in the entailment direction (the
     anchor or its parents, never subtypes).
   - Guards: never the anchor, absent nodes, value-bearing nodes, contraindicated drugs, a
     finding with a competing adverse-reaction explanation, or an unmapped node.
   - D4 interface: delete one node, call evaluate(), keep the deletion only if utility and
     disclosure are unchanged at their reporting resolution, and re-test accepted deletions
     in a fixed order. Off until the hook exists.
   - Anchor finding is T8b.
T8b Anchor finding:
   - Use OptimusKG only if the Phase 0 (e) feasibility test passed on every fixture;
     otherwise use the fallback chain and record the failed condition(s) in an ADR.
   - OptimusKG method: explanatory coverage = the number of other motif nodes a disease
     explains through manifestation edges.
   - Fallback chain, in order:
     1. record: FHIR Encounter.diagnosis (principal / rank 1 of discharge or billing use)
        or the OMOP condition_status_concept_id principal diagnosis;
     2. snomed: SNOMED Due to links between bundle conditions (Y explains X when X is
        defined Due to Y or an ancestor of Y). The anchor is the node that no other node
        explains and that explains at least one. The attribute comes from the release's
        concept-model files, never typed;
     3. producer: keep the producer's anchor, marked unconfirmed.
   - Record anchor_source (record | snomed | optimuskg | producer) with its evidence.
   - Never switch the anchor: a derived anchor that differs from the producer's is listed in
     anchor_report.tsv for me to decide. The OptimusKG coverage is a cross-check column.
T9 motif_aggregation:
   - Merge only if the anchors share a phecode at integer level or finer (SNOMED -> ICD-10
     -> PhecodeX).
   - The merged anchor = the conjunction of all minimal common SNOMED ancestors. Each must
     pass concept lift's floor policy, else the merge is blocked.
   - Keep only shared edges, with their targets merged the same way. Never re-attach
     one-sided edges.
   - Merge pairwise in hash order. The merged node records members[].
   - The export states "at least one condition under this ancestor".
T10 Lattice over all six operators:
   - BFS with global dedup (combinations, not permutations).
   - The upper bound U is written first to termination.json.
   - Candidates are streamed to disk.
   - A machine budget is measured on the first frontier (free disk and memory via stdlib;
     optional --time-budget). Fits -> exhausted; else best-first by information loss ->
     budget_limited.
   - --depth is a display filter only.
   - Order checker: deletion -> subset ids; bucketing and aggregation -> interval or set
     containment; a merged node maps to one member.
T11 Metric hook evaluate(bundle) -> metrics, implemented by the metrics harness (not
    semgen), plus metric_deltas.jsonl with one row per lattice edge.
T12 Fixtures and tests:
    - Keep M1-M4, and add bundles for:
      - meningitis + fever + headache;
      - duodenal ulcer + duodenitis + pantoprazole;
      - typhoid + a quantified weight loss;
      - BMI 41 + obesity;
      - three ALT results.
    - Synthetic patients. The expected-result tables come from Phase 0 facts, never
      invented.
    - Mayo logic is tested on a tiny synthetic sqlite with the same schema. Real-data tests
      are marked mayo/snomed/phecodex/optimuskg and skip if the data is absent.
T13 ADRs (one per operator and per removal), the README, and a dated methodology amendment.
    Never call anything clinically validated.

CHECKS (acceptance criteria)
- Containment: zero lattice edges where the child matches fewer synthetic patients.
- Bucketing: a bucket only from the result's range or a high-confidence Mayo row, with
  pdf_page recorded; LVEF unbucketable.
- A1: three ALT results -> one set of buckets; no mean or latest.
- A2: BMI + obesity merged only if Phase 0 confirmed the SNOMED definition.
- D2/D3: the meningitis bundle deletes fever/headache with the KG edge recorded and the
  correct meaning tag.
- Pantoprazole deletion stays blocked until a drug map exists.
- Aggregation: duodenal ulcer + duodenitis -> their least common subsumer only if they share
  a phecode.
- Negation: no operator touches an absent node (M2).
- Anchor: every bundle has anchor_source plus evidence; no anchor is switched
  automatically; the OptimusKG method is used only if Phase 0 (e) passed.
- The no-hardcoding grep passes; two runs are byte-identical; actual count <= U; every
  fixture is exhausted.
Open questions
1. Can we get Mayo's written permission? The reference-range dataset derives from © Mayo content licensed for personal, noncommercial use; team or production use needs Mayo's written consent.
2. Do the patient graphs keep each lab's own reference range per result? If not, every bucket depends on a population table.
3. Is a SNOMED → RxNorm map available (UMLS account)? Without it, drug-based deletion (indication, contraindication, adverse reaction) stays blocked.
4. Who owns the metric harness interface (evaluate)? D4 and the metric plots wait on it.
5. Should a merged anchor be kept as "at least one condition under X", or should merging be limited to cases where one motif is wholly implied by the other?
6. Does the patient graph keep the principal diagnosis? If the OptimusKG feasibility test fails, the anchor falls back to FHIR Encounter.diagnosis or OMOP condition status, then to SNOMED Due to links. The first works only if the builder keeps those fields.
Sources
All pages were opened during the research. Some claims are marked unverified in the sections above where a page could not be opened.
• github.com/mayoclinic, OHNLP, CLIR, Mayo Clinic Platform blog, Mayo Labs critical values list, labNorm
• LOINC forum on reference ranges, FHIR R4 Observation, FHIR R5 Observation, HL7 interpretation codes, OMOP CDM 5.4, OMOP vocabulary
• Montgomery et al., ICML 2026
• SNOMED observable attributes, SNOMED finding attributes, LOINC Groups
• HHS de-identification guidance, ARX configuration, Pitoglou et al. 2022, Kamdje Wabo et al. 2026
• OptimusKG paper, OptimusKG repo, OptimusKG announcement, PrimeKG repo, PrimeKG paper, HPO annotation format
• Hetnet connectivity search, Dr.Knows, Rotmensch et al. 2017, Rodríguez-Muro & Calvanese 2011, CF-GNNExplainer, SubgraphX
• Cerna & Kutsia 2023, Baader 2003, Figueira & Romero 2023, phecodeX, Shuey et al. 2023, Prasser et al. 2016