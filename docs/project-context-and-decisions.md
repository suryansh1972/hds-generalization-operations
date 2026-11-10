# Semantic Generalization of Motifs — Project Context and Decision Log

*Covers the whole design conversation up to 1 Nov 2026, before implementation started.*

This document records what we set out to build, what we found in the repository and in SNOMED, every decision we made (and why), what changed from the original methodology, what was corrected along the way, and what is still open.

---

## 1. What we are building

**The module:** "Semantic Generalization of Motifs" — Section 6.5 of the Central–Leaf design (Eq. 15, Table 3).

**In plain words:** a *motif* is a small graph describing a clinical pattern, e.g. "a patient with breast cancer, given doxorubicin, whose LVEF was 38% 23 days later". The engine takes one motif and produces every **more general** version of it, e.g. "LVEF below 40%", "within 30 days", "exposed to the drug" instead of "administered". Each new version must match **at least the same patients** as the original — never fewer.

**What it outputs:**
- a *lattice* — all generalized versions, with duplicates removed,
- for every step, a *change record* saying exactly what changed,
- an independent *proof* that each version really is more general.

**What it deliberately does NOT do** (that is the next step): count patients, score utility, compute disclosure risk, choose a winner, or call BioPathNet.

**Project boundaries:**
- BioPathNet is not implemented, retrained, modified or called. A colleague is building the BioPathNet enrichment pipeline separately.
- The POC uses synthetic motifs M1–M4 that mimic what BioPathNet-enriched motifs should look like. We do not invent the colleague's real schema; integration happens later.
- No LLM / fuzzy matching anywhere. Every decision is a symbolic check against SNOMED or a fixed rule table.

---

## 2. How the conversation went (timeline)

| Phase | What happened |
|---|---|
| 1. Repository understanding | Read the methodology; inspected the HDX folder; produced architecture, package structure, data flow, dependencies, ambiguities and acceptance criteria. |
| 2. Methodological correctness review | Investigated floors, ladders, time, SNOMED direction, the containment proof (tested rustworkx), negation and provenance. Produced an issue table. |
| 3. Your decisions (round 1) | P6 one-to-one matching, floors by branch, allowlist for drugs, LVEF ladder, time ladder, M3 anchor change, etc. I raised gaps G1–G5. |
| 4. Stack change | Cypher/FalkorDB dropped; DuckDB/SQL, clingo, Graphviz proposed. Two earlier claims corrected (Cypher, ALT). I flagged bugs B1–B4 and a scope conflict. |
| 5. Consolidated table | Full issue table with status per item. |
| 6. "What is waiting on a clinician?" | Explained the open items in plain language; you clarified that "enriched" = BioPathNet output. |
| 7. Clinician-free proposal | Reviewed your document replacing clinician calls with published classifications (PhecodeX, ATC, LOINC, guidelines). Verified on local SNOMED. |
| 8. POC scope | You asked for a working POC only. Agreed: hand-written DRAFT floors first, PhecodeX later, deployment/licences ignored. |
| 9. Final decisions | M1 lift block accepted, `phecode_level` setting, age ladder, ALT as ×ULN, M5 idea, two stages. I found the DM blockers. |
| 10. Workspace | New git repo `semgen`, worktree, branch `feature/semantic-generalization`, Python 3.12, baseline 0 tests. |
| 11. Implementation plan | 17 TDD tasks written and committed. |
| 12. Execution rules | Subagent-driven development, one task at a time, review gate per task. |

---

## 3. What we found in the repository

| Item | Finding |
|---|---|
| HDX folder | Was **not** a git repository. Contains PDFs, notes in `dump/`, `kg-client/`, `kg-explorer/`, `OptimusKG/`, the SNOMED release. |
| Pipeline code | **None exists.** No BioPathNet, NBFNet, motif, or patient-graph code anywhere. This module is the first real code. |
| Motif format | Only the JSON in the methodology document. |
| Provenance in notes | `dump/plan.md` uses `extracted` / `ancestor, level n` / `enriched, score s`. The methodology uses `asserted` / `derived` / `context`. |
| OptimusKG | A clone of Harvard's public repo (mims-harvard). Someone else's code → we do not build inside it. House style: Python 3.12, `uv`, Polars, Pydantic. |
| OptimusKG ids | Real formats: `ENSG…` (genes), `DRUGBANK…`, `REACT:R-HSA-…`, `MESH…`. The methodology's `optimus:gene/TOP2B` style does not exist. Verified: TOP2B = `ENSG00000077097`, EGFR = `ENSG00000146648`. |
| Tests / deps | No tests in HDX. Python 3.12.2 and `uv` available. |
| SNOMED | `SnomedCT_InternationalRF2_PRODUCTION_20260201T120000Z` — **International edition, release 2026-02-01**. All needed Snapshot files present, plus the ICD-10 extended map refset. |

---

## 4. Facts verified on your SNOMED release

### Labels and ids
| Label in methodology | Result |
|---|---|
| Malignant neoplasm of breast | `254837009` ✓ |
| Doxorubicin | `372817009` ✓ |
| LVEF | Matches **two** concepts: `250908004` (active) and `389385008` (retired) → loader must use active only |
| "Type 2 diabetes mellitus (disorder)" | **Does not exist.** Real FSN: "Diabetes mellitus type 2 (disorder)" `44054006` |
| "Type 1 diabetes mellitus (disorder)" | **Does not exist.** Real FSN: "Diabetes mellitus type 1 (disorder)" `46635009` |
| Rheumatoid arthritis | Two matches: `69896004` (active), `156471009` (retired) |
| Osimertinib | `716032009` ✓ (my hand-typed id `716125002` was **wrong** — it is pembrolizumab; proves ids must always be resolved by label) |
| ALT | No "Alanine aminotransferase … (observable entity)". Found "Alanine transaminase in serum (observable entity)" `364571000119101` — **in the International core module** (`900000000000207008`), active since 2023-09-01 |
| EGFR mutation *finding* | **Does not exist** in International. Only the disorder "Non-small cell lung cancer with mutation in epidermal growth factor receptor" `703228009`, whose only parent is NSCLC `254637007` |

### Hierarchy direction checks
- Breast cancer **is** under Malignant neoplastic disease (`363346000`); the reverse is false.
- Type 2 diabetes **is** under Diabetes mellitus (`73211009`). Type 1 is too.
- CKD, ILD, RA and T2DM are **not** under Malignant neoplastic disease.
- Breast cancer's parents: "Neoplasm of breast" `126926005` (includes non-malignant → outside the floor) and "Malignant neoplasm of thorax" `188361007` (inside the floor).

### Drug parents (mixed structural and class groupers)
| Drug | Parents |
|---|---|
| Doxorubicin | Anthracycline |
| Metformin | Biguanide hypoglycemic agent |
| Osimertinib | EGFR-inhibitor mechanism; **Indole** (structural) |
| Methotrexate | Antifolate; **Pteridine** (structural) |
| Anthracycline | Cytotoxic antibiotic; Polyketide |

Grouper contents: Anthracycline (23 descendants, all real anthracyclines); **Antifolate contains bromadiolone (a rat poison)** and pteroyltriglutamic acid; Biguanide includes phenformin. The structural root is `312413002` "Substance categorized **by structure**" (not "structurally" — use the id, never the name).

### ICD-10 map (for the later PhecodeX stage)
- Refset `447562003`, ~215,000 rows, local. `mapRule`: 153,686 `TRUE`, 74 `OTHERWISE TRUE`, rest `IFA` (sex/age conditions).
- Coverage: everything under CKD, T2DM, ILD, RA, NSCLC has an unconditional target. Breast cancer: 3 blockers (grouper concepts with empty targets). Diabetes mellitus: 2 blockers — "Newly diagnosed diabetes" `405749004` and "Maternal diabetes mellitus with hypoglycemia affecting fetus OR newborn" `4783006` (empty targets).

---

## 5. Errors found in the original methodology

| Where | Error | Fix |
|---|---|---|
| LVEF ladder | Three different versions (config, Check 2, Section 3) | One ladder (D5) |
| Time ladder | Line 83 and line 415 disagree | One ladder (D6) |
| "co-occurs" | Not reliably broader than "after" | Removed |
| Line 61 | Calls ⊑ "ancestor-or-self"; it is **descendant-or-self** | Named helpers (D7) |
| Line 119 | `ancestors(c)` ≠ ECL `>> c` (`>>` includes self) | Named helpers (D7) |
| Floors | A Disorder-wide floor of Malignant neoplastic disease blocks every non-cancer | Floor list by branch (D2) |
| SNOMED attribute relaxation "for free" | Doesn't apply — motif relations are our own names | Relations only from YAML |
| Negation | Didn't forbid coarsening a value on, or relaxing the relation into, an absent node — both **narrow** the patient set | Operators skip absent nodes (D11) |
| Attribute removal | Defined two ways (leaf node vs attribute) | Attributes/values only; nodes removed only via edge removal |
| Edge removal | "connected to the anchor" vs "to the patient" | Connected to the patient (D13) |
| rustworkx VF2 | Recommended, but cannot do the job (see §7) | Identity-map proof |
| Labels | T1/T2 DM names wrong; EGFR finding and ALT label don't exist | D15 |
| "Patient matcher for free" | Fails for absent nodes ("no X" is a not-exists check, not a node match) | Separate closed-world handling |

---

## 6. All decisions (D1–D17, as written into the plan)

| # | Topic | Decision | Why |
|---|---|---|---|
| D1 | Scope | POC only. No counting, utility, disclosure, BioPathNet, LLM. No DuckDB, FalkorDB, rustworkx, clingo, Graphviz, Parquet, PhecodeX/ATC/LOINC/RxNorm tables. Deployment and licences ignored. | You asked for a working POC first |
| D2 | Floors | YAML list: `363346000` Malignant neoplastic disease, `73211009` Diabetes mellitus (DRAFT). A lift must stay under **every** floor that applies (G1). No floor → no lift, logged `no_floor`. No Substance/Observable floors invented. | Fail closed; polyhierarchy can't escape a floor |
| D3 | Lift blockers | Never lift a node with a value (F7) or a concept-dependent attribute (G2). Unflagged attribute = dependent. `age_at_dx` independent, `cumulative_dose` dependent. | A dose/value only means something for its exact concept |
| D4 | Intervals | Store `lo, hi, lo_closed, hi_closed, unit`; `None` = unbounded. "Unconstrained" = value removed, never (−∞,∞). | No gaps (39.5, 49.5); one way to say "no limit" |
| D5 | Ladders | Laminar rungs; move to the narrowest rung that strictly contains the current interval. LVEF `[0,40) [40,50) [50,55) [55,101) [0,50) [0,55)` (ESC `<40`); eGFR KDIGO categories + `[30,60) [0,60)`; ALT ×ULN `[0,1] (1,3] (3,5] (5,20] (20,∞) (3,∞) (1,∞)`; age `[65,80) [90,∞) [65,∞)`; dose `[0,100) [100,250) [250,∞) [100,∞)`. All DRAFT. | Guideline cut points only; containment by construction |
| D6 | Time | Window = target − source, days. Ladder `[0,30] [0,90] [0,365] [0,∞)`. Co-occurs removed. No constraint = remove the `followed_by` edge. No negative lower bound. Same day counts as "after". Fractional days allowed. "Certainly within" semantics. | Before/after order must be kept |
| D7 | Direction | Only `is_descendant_or_self`, `ancestors_or_self`, strict `ancestors` read the hierarchy. Lift = direct active parent under every applicable floor. | One place to get direction right; tested on real data |
| D8 | Proof | One-to-one via the **identity map**: S′ ids ⊆ S ids, each kept node/edge checked against its original. | Operators never rename/merge nodes, so no search is needed |
| D9 | Proof rules | Present: same type/role/polarity, S code under S′ code, context codes equal, S′ value/attrs contain S's. Absent: reversed direction. Edge: relation equal-or-broader, provenance equal, window contains. Missing on S′ = OK; added on S′ = fail. | Exact definition of "more general" |
| D10 | Legality ≠ order | Separate policy guard (floors, protected nodes, absent untouched, context edges unchanged) + order proof. Either fails → stop loudly. | "More general" isn't the same as "allowed" |
| D11 | Negation | Every operator skips absent nodes and their edges. Absent nodes = leaves attached only to the patient. Closed world. | Changing a "no X" can shrink the patient set |
| D12 | Provenance | extracted→asserted, ancestor→derived, enriched→context (BioPathNet only). Relaxation on asserted edges only, changes only `rel`. Context edges can only be removed. | Predicted links never become facts |
| D13 | Edge removal | Never remove patient→anchor or edges touching absent nodes. Removing patient→node removes that node and its edges. Drop orphans. Keep ≥1 asserted edge. | A fact not tied to the patient is meaningless |
| D14 | Loader | Exact FSN on active concepts only; reject unknown endpoints, missing/unlinked anchor, parallel edges (G5), non-leaf absent nodes, finite age ≥90. | Fail early with clear errors |
| D15 | Motifs | Correct DM names; M3 anchor `703228009` (old n2 deleted); M4 ALT = 3.6 `xULN`; real gene ids, placeholder pathway/disease ids; `has_finding` covered by a test fixture. | Labels must resolve; M3 gives a real positive lift test |
| D16 | Test matcher | Pure Python, one-to-one, closed-world, only under `tests/support/`; production must not import it. | Proves "more general never matches fewer patients" without building counting |
| D17 | Run header | SNOMED release + edition, config SHA-256, DRAFT status, LVEF convention, temporal semantics, closed-world statement, max depth. | Every result is traceable |

### Key reasoning behind P6 (one-to-one matching)
- **Sound:** if S′ maps one-to-one into S and a patient matches S one-to-one, chaining gives a one-to-one match to S′ — so a more general motif never matches fewer patients.
- **Clinical meaning:** two pattern nodes mean two recorded facts.
- **Safe:** one-to-one can only give equal or lower counts, and the support gate is a minimum, so errors block a release rather than allow one.

### Gap fixes G1–G5 (accepted)
- **G1** — polyhierarchy floors: lift must stay under *every* applicable floor.
- **G2** — concept-dependent attributes block lifts; unflagged = dependent (your addition).
- **G3** — ALT ladder: no unit/×ULN conversion in this step; mismatched units rejected.
- **G4** — time precision is the upstream builder's job; this step accepts fractional days.
- **G5** — loader rejects two edges between the same ordered node pair.

### Bugs B1–B4 found in the proposed instructions (all fixed in the plan)
- **B1** — interval checks ignored open/closed bounds → every comparison respects inclusivity.
- **B2** — "clingo refutes everything identity rejects" is false → only one direction is asserted.
- **B3** — proposed SQL tables couldn't store patient edges, type, polarity, attributes, context codes → noted for the future matcher.
- **B4** — the order proof doesn't enforce legality → separate policy guard (D10).

---

## 7. Tools and stack decisions

| Tool | Decision | Reason |
|---|---|---|
| rustworkx VF2 | **Dropped** | Tested: it is one-to-one (not homomorphism); its node matcher gets `(first, second)` but its edge matcher gets `(second, first)` — would silently reverse "narrower than"; it handles parallel edges differently from our definition |
| FalkorDB / Cypher | **Dropped** | Cypher lets two node variables match the same node (needs `a <> b` everywhere); FalkorDB miscounts parallel edges |
| DuckDB + SQL matcher, Parquet | Deferred | Belongs to the next step (support counting) |
| clingo | Deferred | Test oracle; not needed for the POC |
| Graphviz | Deferred | `dot` binary not installed; pictures optional |
| PhecodeX / ATC / LOINC / RxNorm / CCSR | Deferred to Stage 1/2 | Need downloads, licences, UMLS account |
| **POC stack** | Python 3.12, uv, Pydantic v2, PyYAML, Polars, pytest, Hypothesis | Minimal, matches house style |

---

## 8. The "clinician-free" approach (evaluated, deferred)

**Idea:** replace each clinician judgement with a published classification + an exact containment rule: a lift is allowed only if *everything* it pulls in belongs to the same published group.

- Disorders: SNOMED → ICD-10 map → PhecodeX (CCSR as second check; unavailable on International).
- Drugs: ATC level 4 / FDA EPC via RxNorm/RxClass, with a containment guard and structural-grouper rejection.
- Observables: LOINC Groups rule (Component/Property fixed). LVEF has no group → blocked.
- Ladders: only guideline cut points (ESC 2022, KDIGO 2024, CTCAE, HIPAA).

**Verdict:** the logic is sound (deterministic, downward-closed, fail-closed). But "no clinician needed" was overclaimed: someone (you or your boss) must sign off once on which authorities are used, and the licences (ATC, PhecodeX, CCSR, EPC) are real deployment blockers.

**Consequence found:** the strict rule blocks most condition-level lifts:
- **M1 breast cancer** — blocked both ways (parents merge different diseases). **Accepted.**
- **M2 T2DM → DM** — blocked even at the integer phecode level, because two DM descendants have no ICD-10 target.
- **M3** — passes (NSCLC with EGFR mutation → NSCLC).

**Decisions:**
- Add a `phecode_level` setting (first decimal default, integer option) for the PhecodeX stage.
- An "authorities" record (PhecodeX, ATC/EPC, ESC `<40`, CTCAE) signed off by you/boss — later.
- **Order:** POC uses hand-written DRAFT floors so all six operators run; the PhecodeX floor table is added afterwards behind the same interface.
- **Stage 1:** engine + PhecodeX disorder floors. **Stage 2:** RxNorm/RxClass drug tables.
- **Q1 time semantics:** "certainly within". **Q3:** build the test-only matcher.

---

## 9. Claims that were corrected during the conversation

| Claim | Status |
|---|---|
| "One-to-one matching matches Cypher" | **Wrong.** Cypher reuses nodes; only relationships are unique. P6 still stands on its other reasons. |
| "ALT `364571000119101` is US-edition only" | **Wrong.** It is in the International core module (checked locally). Promoted concepts keep their original id. |
| My osimertinib id `716125002` | **Wrong** (pembrolizumab). Correct: `716032009`. |
| "Integer phecode level lets T2DM → DM pass" | **Wrong.** Two unmapped DM descendants still block it. |
| "None of this needs a clinician" | **Overclaimed.** Needs a one-time authority sign-off, not per-concept clinical judgement. |
| Methodology's "textbook homomorphism" | Replaced by injective (one-to-one) semantics; still sound for Eq. 15. |

---

## 10. Test motifs (as planned)

| Motif | Content | Role in tests |
|---|---|---|
| M1 | Breast cancer, doxorubicin (dose 360), LVEF 38% at 23 days, age 67, TOP2B → pathway context | Lift to "Malignant neoplasm of thorax" only (hand floors); dose blocks drug lift; LVEF value blocks lift; all other operators |
| M2 | T2DM, **no T1DM**, metformin, CKD, eGFR 42 at 180 days, lactic acidosis context | Negation protection; T2DM → DM then stops at floor; eGFR and 180→365 ladders |
| M3 | NSCLC with EGFR mutation (`703228009`), osimertinib, ILD at 41 days, EGFR → ErbB context | Positive anchor lift to NSCLC |
| M4 | RA, methotrexate, ALT **3.6 ×ULN** at 90 days, DILI context | ALT ladder (3,5] → (3,∞) → (1,∞); RA blocked `no_floor` |
| M5 (idea) | CKD subtype anchor | Deferred to the PhecodeX stage (CKD has no hand-written floor) |

---

## 11. Workspace

| Item | Value |
|---|---|
| Repository | New repo `HDX/semgen` (HDX itself was not a repo; OptimusKG untouched) |
| Worktree | `HDX/semgen/.worktrees/semantic-generalization` |
| Branch | `feature/semantic-generalization` (main branch: `main`) |
| Python | 3.12.2 in `.venv` (git-ignored) |
| Baseline tests | 0 tests (no suite existed) |
| Commits | `f129f8f` initialise repo (`.gitignore`); `2f0a761` methodology + implementation plan |

---

## 12. Implementation plan and execution rules

**Plan:** `docs/plans/semantic-generalization-implementation.md` — 17 TDD tasks:

1. Package and data models · 2. YAML config + validation · 3. SNOMED RF2 loader · 4. Motif loader + FSN resolution · 5. Canonical JSON + hash · 6. Concept lift · 7. Attribute removal · 8. Range coarsening · 9. Temporal coarsening · 10. Relation relaxation · 11. Edge removal + orphan cleanup · 12. Order checker · 13. Neighbors (guard + proof + dedup) · 14. BFS lattice · 15. JSONL export + CLI · 16. Synthetic patient containment tests · 17. Real-SNOMED integration + README.

**Review focus pinned by tests:** bound inclusivity at equal endpoints; polyhierarchy floor escape; edge-removal cascades; values outside every rung; the same child reached by two operators.

**Execution rules (agreed):**
- Subagent-driven development (not Native).
- One task at a time; fresh implementer + separate fresh reviewer per task.
- Red → green → refactor; tests first and must fail for the expected reason.
- Reviewer checks the real diff against the plan; fix findings, rerun, then commit with the plan's message.
- No next task until the current one passes tests and review. No parallel dependent tasks.
- Only the plan's dependencies; YAML stays DRAFT; production never imports the test matcher.

---

## 13. Still open

| Item | Who | When it matters |
|---|---|---|
| M2 under the strict rule: accept no lift, or a logged exception list for SNOMED-unmapped descendants | You | PhecodeX stage |
| Authorities sign-off record | You / your boss | Before real use |
| Licences (PhecodeX, ATC, CCSR, EPC) | You | Deployment only |
| Real floors, drug allowlist, observable floors, ladder confirmation | Authority sources or clinician | Before real use |
| Your colleague's real BioPathNet motif schema | Colleague | Integration step |
| "Certainly vs possibly within" implementation | Upstream builder owner | Patient-graph builder |
| Does "active recorded fact" mean SNOMED-active or clinically active? | Next step | Patient matcher |

---

## 14. Glossary

- **Motif** — a small typed graph describing a clinical pattern.
- **Generalization / lift** — replacing something specific with something broader.
- **Floor** — the highest concept a lift may reach.
- **Ladder** — fixed steps for widening a number or a time window.
- **Laminar** — any two rungs are either nested or don't overlap.
- **Lattice** — all generalized versions and the steps between them.
- **Change record** — what exactly one step changed.
- **Order proof** — the check that a version is really more general.
- **Absent node / "no X"** — a constraint that the patient does *not* have X.
- **Closed world** — anything not recorded counts as absent.
- **Provenance** — where a fact came from: asserted (in the record), derived (rule/SNOMED), context (BioPathNet-predicted).
- **Fail closed** — when unsure, block the move rather than allow it.
- **DRAFT** — a value chosen for the POC, not clinically approved.
