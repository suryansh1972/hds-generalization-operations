# Stage 1 — PhecodeX-Derived Disorder Floors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Red → green → refactor on every task.

**Goal:** Replace the hand-written YAML floor list with floors derived deterministically from published, pinned sources: SNOMED → ICD-10 (International map refset `447562003`) → PhecodeX. A disorder may be lifted to a direct parent only if **every** active descendant-or-self of that parent maps inside **every** phecode anchor of the concept being lifted.

**Architecture:** Three read-only data sources:
- the SNOMED IS-A graph (existing `Hierarchy`, plus a new `descendants_or_self`)
- the ICD-10 extended map from the local RF2 `Refset/Map` folder
- three PhecodeX CSVs fetched from GitHub at a pinned commit, sha256-verified, git-ignored

A `PhecodeFloorPolicy` answers one question, `check_lift(child, parent) -> FloorDecision`. `concept_lift` calls this policy instead of reading `config.floors`, and the YAML `floors` list is deleted. Drugs and observables have no floor source in Stage 1, so they stay blocked (`no_floor`).

**Tech Stack:** unchanged. Python 3.12, uv, Pydantic v2, PyYAML, Polars, pytest, Hypothesis, plus stdlib `urllib`/`hashlib` for the fetch. No new dependencies.

**Spec:** `/Users/suryanshshivaprasad/Documents/HDX/clinician-free-generalization.md` §"Disorder floors come from PhecodeX through the ICD-10 map". Also `docs/project-context-and-decisions.md` §8. The decisions below amend both documents where they conflict.

---

## Facts verified on the local data (1 Nov 2026, before writing this plan)

| Fact | Value |
|---|---|
| ICD-10 map file | `<RF2 Snapshot>/Refset/Map/der2_iisssccRefset_ExtendedMapSnapshot_INT_20260201.txt` |
| Map header | `id effectiveTime active moduleId refsetId referencedComponentId mapGroup mapPriority mapRule mapAdvice mapTarget correlationId mapCategoryId` |
| Active rows in refset `447562003` | 153,894 |
| mapRule counts | 153,686 `TRUE`, 74 `OTHERWISE TRUE`, the rest `IFA …` |
| T2DM `44054006` | target `E11.9` |
| Newly diagnosed diabetes `405749004` | rule `TRUE`, empty target |
| RA `69896004` | target `M06.99`. PhecodeX has `M06.9`, not `M06.99`, so the prefix fallback is needed |
| PhecodeX repo | `PheWAS/phecodeX`, commit `6c5c6f787651c06351fe5a7c558a0a05c7a2f8a7` (2025-09-18). No licence file. |
| `phecodeX_R_map_ICD_10_WHO.csv` | columns `phecode,code,vocabulary_id`. Already unrolled: `E11.9` → `EM_202` and `EM_202.2`. sha256 `ba2cf94fdef67d7ea8fae63f12d38d4a5c389f579c257f189d05fc033e39c52a` |
| `phecodeX_R_rollup_map.csv` | columns `code,phecode_unrolled`, self-rows included. sha256 `b57311cd22a6adc3ac1595daa7261b0de761eb4b4010acf324fd99792a05bc6e` |
| `phecodeX_R_labels.csv` | columns `phenotype,description,icd10_only,groupnum,group,color`. sha256 `7ca090f8528efdddd8a7d2aed55cfd3ba739a4fffd8a45632a8c31a587dfad84` |
| ICD target coverage in PhecodeX | Of 10,692 distinct usable targets: 6,738 match exactly; 1,809 match after dropping trailing characters; 2,145 have no phecode at all (e.g. `J95.*`, `K91.*` procedural complications) and fail closed |

Prototype results of the rule below, at `first_decimal` level, on the real release:

| Concept | Anchors | Parent → decision (first blocking descendant by sorted id) |
|---|---|---|
| `254837009` Breast cancer | `CA_105`, `CA_130` | `126926005` blocked by `1080431000119107`. `188361007` blocked by `105041000119109` |
| `44054006` T2DM | `EM_202.2` | `73211009` blocked by `105401000119101` |
| `703228009` NSCLC-EGFR | `CA_102.1`, `CA_130` | `254637007` **allowed** (36 descendants) |
| `254637007` NSCLC | `CA_102.1`, `CA_130` | `448993007` blocked by `105041000119109` |
| `69896004` RA | `BI_181`, `MS_705.1` | `3723001` blocked by `10193001`. `85828009` blocked by `10743271000119103` |
| `709044004` CKD | `GU_582.2` | `128290005` blocked by `10194007`. `236423003` blocked by `10697004` |

## Decisions (S1–S10)

| # | Decision |
|---|---|
| S1 | **Usable targets.** Active rows of refset `447562003` with `mapRule ∈ {TRUE, OTHERWISE TRUE}` and a non-empty `mapTarget`. IFA rows are ignored, which is fail-closed: they can only remove support. All `mapGroup`s count. |
| S2 | **ICD → phecode lookup.** Exact code first. Otherwise drop trailing characters (then any trailing `.`) until a code in the PhecodeX map is found, never going shorter than 3 characters. The ICD code that matched is kept for evidence. No match means no phecodes. |
| S3 | **Anchors of c.** Truncate `Phecode(c)` to `phecode_level` (`first_decimal` default; `integer` optional; `GU_582.21` → `GU_582.2` or `GU_582`). Then drop any anchor that another anchor rolls up to, keeping only the most specific. An empty result gives `unmapped`, so no lift. |
| S4 | **Membership.** x is in anchor q iff some phecode p of x (or `truncate(p)`) equals q or rolls up to q in `phecodeX_R_rollup_map.csv`. |
| S5 | **Eligibility.** Parent P is allowed for child c iff every **active** descendant-or-self d of P is in every anchor of c. Descendants are checked in sorted id order, and the first failure is reported (`blocking_descendant`, `anchor`). |
| S6 | **No drift across repeated lifts.** Anchors are always those of the node's *current* code. This is sound: if P is allowed for c, then for every anchor q of c, P has an anchor at or below q, so anything inside all of P's anchors is inside all of c's. A lift chain can therefore never leave the original concept's floors. This is pinned by a test. |
| S7 | **Scope.** The policy applies to nodes of `type == "Disorder"` only. Other clinical types (Substance, Observable, Procedure, Finding) are blocked with reason `no_floor` and detail `{"type": t}`. Stage 2 (RxNorm/RxClass drug classes) is not part of this plan. |
| S8 | **Reasons.** `concept_lift` blocked reasons become `carries_value`, `concept_dependent_attr`, `no_floor`, `unmapped`, `inactive_parent` and `outside_floor`. `at_floor` is removed, because there are no explicit floor concepts any more; a concept "stops" when every parent is `outside_floor`. |
| S9 | **Sources.** The PhecodeX files are fetched, not vendored. They are downloaded from `https://raw.githubusercontent.com/PheWAS/phecodeX/<commit>/<file>` into `data/external/phecodex/<commit>/` (git-ignored), and each file's sha256 is checked against the config. Tests use tiny fixtures; real-data tests are marked `@pytest.mark.phecodex` and skip if the files are missing. |
| S10 | **Traceability and open items.** The run header (Task 15 of the main plan) gains these fields: `floor_source: "phecodex"`, `phecodex_commit`, `phecodex_sha256` (per file), `icd10_map_refset: "447562003"`, `icd10_map_release`, `phecode_level`, `ccsr_check: "unavailable"` (CCSR needs the US-edition ICD-10-CM map, which we don't have) and `source_licences: {"phecodex": "unconfirmed"}`. Licences are ignored for the POC (D1) but recorded. The §13 open item on M2 (T2DM → DM) is ruled **strict: no lift**; an exception list can come later. |

Unchanged: D3 (value/attr blockers run before the floor check), D7 (direction helpers; `descendants_or_self` is added as a fourth IS-A reader, used only by the floor policy), and D10/D11/D12.

## Global Constraints

- Every Global Constraint of `docs/plans/semantic-generalization-implementation.md` still applies (Python ≥3.12, uv, the dependency list, purity, determinism, DRAFT marking, commit trailer).
- No new dependencies. Downloads use `urllib.request` only.
- PhecodeX pin: commit `6c5c6f787651c06351fe5a7c558a0a05c7a2f8a7`, with the three sha256 values above.
- `data/external/` is git-ignored. No third-party data file is committed.
- Default PhecodeX dir: `data/external/phecodex/<commit>`. Override with env `SEMGEN_PHECODEX_DIR`.
- The ICD map is found as `<terminology_dir>/../Refset/Map/der2_iisssccRefset_ExtendedMapSnapshot_*_*.txt`, and exactly one file must match.
- Read the RF2 map like every RF2 file: tab separator, every column as text, `quote_char=None`.
- After this plan, no SCTID and no floor list may appear in `config/generalization.yaml` or in `src/`.

## Review Focus

1. **Polyhierarchy and multiple anchors.** A descendant inside one anchor but not another must block. Pinned in Task 3 (`test_every_anchor_required`).
2. **Prefix fallback.** `M06.99` must resolve through `M06.9`. A code with no ancestor in PhecodeX must give no phecodes, not crash. Pinned in Task 3.
3. **A parent that maps only to a coarser phecode** (child `CA_105.1`, parent `CA_105` only) must be blocked. Pinned in Task 3 (`test_coarser_parent_blocked`).
4. **Determinism of the reported blocker.** The same inputs must always report the same `blocking_descendant`, the smallest failing id in sorted order. Pinned in Task 3.
5. **Missing source files.** A missing or tampered PhecodeX file must raise a clear error that names the file. It must never be silently treated as "no floors". Pinned in Task 1.

---

## File structure

```
config/generalization.yaml          + floor_source block; floors list removed (Task 4)
.gitignore                          + data/external/
src/semgen/sources.py               PhecodeX manifest, fetch + sha256 verify, default dir      (Task 1)
src/semgen/config.py                FloorSourceConfig; GenConfig.floor_source; floors removed (Tasks 1, 4)
src/semgen/snomed.py                Hierarchy.descendants_or_self; check_floors removed        (Tasks 2, 4)
src/semgen/icd10map.py              Icd10Map loader (usable targets)                           (Task 2)
src/semgen/phecodex.py              PhecodeX tables, lookup with prefix fallback, rollup       (Task 3)
src/semgen/floors.py                FloorDecision, PhecodeFloorPolicy                          (Task 3)
src/semgen/operators/base.py        GenContext gains floors                                    (Task 4)
src/semgen/operators/concept_lift.py   uses ctx.floors                                         (Task 4)
src/semgen/floor_report.py          review table for motifs (python -m semgen.floor_report)    (Task 5)
tests/fixtures/icd10map/…           tiny map file
tests/fixtures/phecodex/…           tiny PhecodeX CSVs
tests/test_sources.py, test_icd10map.py, test_floors.py, test_floor_report.py
docs/plans/semantic-generalization-implementation.md   Tasks 13, 15, 17 amended               (Task 5)
```

---

### Task 1: Pinned PhecodeX sources and fetch

**Files:**
- Create: `src/semgen/sources.py`, `tests/test_sources.py`
- Modify: `src/semgen/config.py`, `config/generalization.yaml`, `.gitignore`

**Interfaces:**
- Produces:
  - `FloorSourceConfig` (frozen pydantic): `kind: Literal["phecodex"]`, `commit: str`, `files: dict[str, str]` (file name → sha256), `phecode_level: Literal["first_decimal","integer"] = "first_decimal"`, `icd10_map_refset: str = "447562003"`, `map_rules: tuple[str, ...] = ("TRUE", "OTHERWISE TRUE")`, `licence: str = "unconfirmed"`.
  - `GenConfig.floor_source: FloorSourceConfig`. It is required. `floors` stays until Task 4.
  - `SourceError(Exception)`.
  - `default_phecodex_dir(src: FloorSourceConfig) -> Path`. Returns env `SEMGEN_PHECODEX_DIR` if set, else `data/external/phecodex/<commit>`.
  - `verify_phecodex(dir_: Path, src) -> None`. Raises `SourceError` naming the file if it is missing or its sha256 differs.
  - `fetch_phecodex(dir_: Path, src, opener=urllib.request.urlopen) -> None`. Downloads each missing or invalid file from the raw GitHub URL, writes it atomically, then calls `verify_phecodex`.
  - CLI `python -m semgen.sources fetch [--dir DIR]`.

- [ ] **Step 1: Add the `floor_source` block to the YAML** (exact values from "Facts"), with a comment that the licence is unconfirmed and the floors are derived, not hand-picked. Add `data/external/` to `.gitignore`.
- [ ] **Step 2: Write the failing tests**

```python
def test_floor_source_loaded():
    s = load_config(CFG).floor_source
    assert s.kind == "phecodex" and s.commit == "6c5c6f787651c06351fe5a7c558a0a05c7a2f8a7"
    assert s.files["phecodeX_R_map_ICD_10_WHO.csv"] == "ba2cf94fdef67d7ea8fae63f12d38d4a5c389f579c257f189d05fc033e39c52a"
    assert s.phecode_level == "first_decimal" and s.icd10_map_refset == "447562003"
def test_fetch_writes_and_verifies(tmp_path):        # opener serves bytes whose sha256 we put in a test FloorSourceConfig
def test_fetch_skips_valid_existing(tmp_path):       # opener must not be called
def test_tampered_file_raises_naming_file(tmp_path): # SourceError, match the file name
def test_missing_file_raises(tmp_path):              # verify_phecodex on an empty dir → SourceError naming a file
def test_default_dir_env_override(monkeypatch, tmp_path)
def test_bad_phecode_level_rejected(tmp_path):       # ConfigError
```

- [ ] **Step 3: Run** `uv run pytest tests/test_sources.py tests/test_config.py -v` → FAIL (import error).
- [ ] **Step 4: Implement**, then **Step 5: Run** → pass. Then run `uv run python -m semgen.sources fetch` once for real and confirm the three files verify.
- [ ] **Step 6: Commit** `feat: pinned, sha256-verified PhecodeX source fetch`.

---

### Task 2: ICD-10 map loader and `descendants_or_self`

**Files:**
- Create: `src/semgen/icd10map.py`, `tests/test_icd10map.py`, `tests/fixtures/icd10map/Refset/Map/der2_iisssccRefset_ExtendedMapSnapshot_INT_20990101.txt`
- Modify: `src/semgen/snomed.py`, `tests/test_snomed.py`

**Interfaces:**
- Produces:
  - `Hierarchy.descendants_or_self(c) -> frozenset[str]`. It uses a children index built lazily from `_parents`, memoised, and excluded from pickling. An unknown concept returns `{c}`.
  - `Icd10Map`: `targets(c) -> frozenset[str]` (usable targets per S1), `release: str`, `refset_id: str`.
  - `Icd10Map.from_maps(targets: dict[str, set[str]], release="TEST")`.
  - `load_icd10_map(terminology_dir: Path, refset_id: str, rules: tuple[str, ...]) -> Icd10Map`. It locates the map at `terminology_dir/../Refset/Map/` and raises `FileNotFoundError` naming the pattern if there is not exactly one file.
- Fixture rows: one TRUE row with a target; one `OTHERWISE TRUE` row; one IFA row with a target, which is ignored; one TRUE row with an empty target, which gives no targets; one inactive row, which is ignored; one row of another refset, which is ignored; and a concept with two `mapGroup`s, both of which count.

- [ ] **Step 1: Write the failing tests.** Each fixture case gets its own assertion. Add `test_descendants_or_self(fake_h)`: `fake_h.descendants_or_self(DM) == {DM, T1DM, T2DM}`, `descendants_or_self(MALIG) == {MALIG, MAL_THORAX, BRCA}`, and an unknown id returns itself. Real tests, marked `snomed`:
  - `targets("44054006") == {"E11.9"}`
  - `targets("405749004") == set()`
  - `targets("69896004") == {"M06.99"}`
  - `release == "20260201"`
  - `real_h.descendants_or_self("254637007")` has 36 members
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `feat: ICD-10 extended map loader and descendants_or_self`.

---

### Task 3: PhecodeX tables and `PhecodeFloorPolicy`

**Files:**
- Create: `src/semgen/phecodex.py`, `src/semgen/floors.py`, `tests/test_floors.py`, `tests/fixtures/phecodex/{phecodeX_R_map_ICD_10_WHO.csv, phecodeX_R_rollup_map.csv, phecodeX_R_labels.csv}`
- Modify: `tests/conftest.py`, adding `fake_floors`, `real_floors` and the fake ICD/phecode tables

**Interfaces:**
- Consumes: `Hierarchy` (`descendants_or_self`, `is_active`, `fsn`), `Icd10Map` (Task 2), `FloorSourceConfig` (Task 1).
- Produces:
  - `PhecodeX`:
    - `phecodes_for_icd(code) -> tuple[frozenset[str], str | None]`. Returns the phecodes and the matched ICD code, per S2.
    - `rolls_up(p, q) -> bool`. True if `p == q` or `(p, q)` is a rollup row.
    - `truncate(p, level) -> str`.
    - `label(p) -> str | None`.
    - `PhecodeX.load(dir_: Path)`.
    - `PhecodeX.from_maps(icd_to_phecodes: dict[str, set[str]], rollup: dict[str, set[str]], labels: dict[str, str] = {})`.
  - `FloorDecision(ok: bool, reason: str | None, detail: dict)`. A frozen dataclass whose detail is JSON-safe.
  - `PhecodeFloorPolicy(hierarchy, icd_map, phecodex, level)`:
    - `phecodes(c) -> frozenset[str]`.
    - `anchors(c) -> frozenset[str]`, per S3.
    - `check_lift(child: str, parent: str) -> FloorDecision`.
      - Reasons are `unmapped` (detail `{"code": child}`) or `outside_floor` (detail `{"parent", "blocking_descendant", "blocking_fsn", "anchor"}`).
      - When `ok`, detail is `{"anchors": sorted, "phecode_level", "checked_descendants": n}`.
      - Results are memoised on `(parent, anchors)`.
    - Property `provenance -> dict`: `{"floor_source": "phecodex", "phecode_level": …, "icd10_map_refset": …, "icd10_map_release": …}`.
  - conftest builds `fake_floors` from `fake_h` plus these fake tables:
    - ICD: `BRCA→{"C50.9"}`, `MAL_THORAX→{"C50.9"}`, `NEO_BREAST→{"D24"}`, `T2DM→{"E11.9"}`, `T1DM→{"E10"}`, `DM→{"E14"}`, `MALIG→{"C80"}`, `CKD→{"N18.9"}`, `DISEASE→{}`.
    - PhecodeX: `C50.9→{CA_105, CA_130}`, `D24→{BI_999}`, `E11.9→{EM_202, EM_202.2}`, `E10→{EM_202, EM_202.1}`, `E14→{EM_202}`, `C80→{CA_130}`, `N18→{GU_582, GU_582.2}`.
    - Rollup: `CA_105.1→CA_105`, `EM_202.1→EM_202`, `EM_202.2→EM_202`, `GU_582.2→GU_582`, `GU_582.21→GU_582.2`.
    - `real_floors` is session-scoped, marked `snomed` + `phecodex`, and skips if either source is missing.

- [ ] **Step 1: Write the failing tests** (fake data unless marked otherwise):

```python
def test_prefix_fallback(): px = PhecodeX.from_maps({"M06.9": {"MS_705.1"}}, {}); assert px.phecodes_for_icd("M06.99") == ({"MS_705.1"}, "M06.9")
def test_no_ancestor_code_gives_nothing(): assert PhecodeX.from_maps({}, {}).phecodes_for_icd("J95.89") == (frozenset(), None)
def test_truncate_levels(): assert truncate("GU_582.21", "first_decimal") == "GU_582.2" and truncate("GU_582.21", "integer") == "GU_582"
def test_anchors_most_specific(fake_floors): assert fake_floors.anchors(T2DM) == {"EM_202.2"} and fake_floors.anchors(BRCA) == {"CA_105", "CA_130"}
def test_breast_cancer_thorax_allowed_neoplasm_blocked(fake_floors):   # MAL_THORAX ok; NEO_BREAST outside_floor, blocking_descendant NEO_BREAST
def test_t2dm_to_dm_blocked_by_t1dm(fake_floors):                     # DM outside_floor, blocking_descendant T1DM, anchor "EM_202.2"
def test_unmapped_concept(fake_floors): assert fake_floors.check_lift(RA, DISEASE).reason == "unmapped"
def test_every_anchor_required():         # descendant mapped to CA_105 only (not CA_130) blocks; anchor "CA_130"
def test_coarser_parent_blocked():        # child → CA_105.1, parent → CA_105 only: outside_floor
def test_ifa_only_descendant_blocks():    # Icd10Map without that descendant's targets → blocks
def test_multi_mapped_descendant_counts():# descendant → {CA_105, GU_582.2} still inside CA_105
def test_blocker_is_deterministic():      # two failing descendants: the smaller sorted id is reported, same across 3 calls
def test_inactive_descendant_ignored():
def test_integer_level_changes_anchor():  # CKD-subtype (GU_582.21) anchors GU_582.2 vs GU_582
@given(...)  # Hypothesis over small random DAGs + random maps
def test_no_drift_along_allowed_chains(): # if c→p and p→g are allowed, then check_lift(c, g) is allowed (S6)
@pytest.mark.snomed @pytest.mark.phecodex
def test_real_prototype_table(real_floors):   # every row of the "Prototype results" table, exactly
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → pass, including the real table. Register the `phecodex` marker in `pyproject.toml`.
- [ ] **Step 5: Commit** `feat: PhecodeX floor policy with every-anchor containment rule`.

---

### Task 4: Switch `concept_lift` to the floor policy and delete the YAML floors

**Files:**
- Modify: `src/semgen/operators/base.py`, `src/semgen/operators/concept_lift.py`, `src/semgen/config.py`, `src/semgen/snomed.py`, `config/generalization.yaml`, `tests/conftest.py`, `tests/test_op_concept_lift.py`, `tests/test_config.py`, `tests/test_snomed.py`

**Interfaces:**
- Consumes: `PhecodeFloorPolicy`, `FloorDecision` (Task 3).
- Produces:
  - `GenContext(hierarchy, config, floors)`. A frozen dataclass; `floors` is required and positional third.
  - `FloorPolicy` Protocol in base.py: `check_lift(child, parent) -> FloorDecision` plus `provenance`.
  - `concept_lift` check order:
    1. Skip silently if the node is not eligible (as before).
    2. `carries_value`.
    3. `concept_dependent_attr`.
    4. `type != "Disorder"` → `no_floor` (detail `{"code", "type"}`).
    5. For each sorted **inactive** parent, emit `inactive_parent`.
    6. Then for each sorted **active** parent, call `floors.check_lift(code, p)`. `unmapped` is emitted once for the node and the loop stops there. `outside_floor` is emitted per parent with the policy's detail plus `code`. A pass becomes a Move with evidence `{"isa": [code, p], **decision.detail, "parent_fsn", "depth_before", "depth_after"}`.
  - The `floors` field is removed from `GenConfig` and the YAML. `check_floors` is removed.
  - The `ctx` fixture becomes `GenContext(fake_h, config, fake_floors)`. `real_ctx` uses `real_floors`.

- [ ] **Step 1: Rewrite the failing tests.** Replace the old floor tests in `test_op_concept_lift.py`:
  - M1 n1 lifts to `MAL_THORAX` only, and NEO_BREAST is `outside_floor` with `blocking_descendant == NEO_BREAST`.
  - n2 is `concept_dependent_attr`.
  - M2 n3 metformin is `no_floor` with `type == "Substance"`.
  - n3 LVEF is `carries_value`.
  - M2 n1 T2DM gets no move, and DM is `outside_floor` with blocker T1DM.
  - `RA` gets `unmapped` (via `one_node_motif(RA)`).
  - `RA_OLD_PARENT` gets `inactive_parent`.
  - The unflagged attr blocks.
  - The input is not mutated.
  - Evidence carries `anchors` and `phecode_level`.

  Also add these tests:
  - `test_no_floor_list_anywhere()`: `"floors"` is not a key in the YAML.
  - `test_no_sctid_in_config()`: the regex `\b\d{6,18}\b` finds nothing in the YAML outside `applies_to_concepts` (ladder bindings) and `floor_source.icd10_map_refset` (the map's own id).

  Real tests, marked `snomed` + `phecodex`:
  - The M1 n1 lift set is empty, with two `outside_floor`.
  - The M3 n1 lift set is `{"254637007"}`.
  - M4 n1 has two `outside_floor` and no `no_floor`.
  - M2 n1 is blocked by `105401000119101`.

  Delete the `floors` tests from `test_config.py` and `test_snomed.py`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run the full suite** `uv run pytest -q` → all pass (other operators unaffected).
- [ ] **Step 5: Commit** `feat!: concept lift uses PhecodeX-derived floors; hand-written floor list removed`.

---

### Task 5: Floor review report and downstream plan amendments

**Files:**
- Create: `src/semgen/floor_report.py`, `tests/test_floor_report.py`
- Modify: `docs/plans/semantic-generalization-implementation.md`

**Interfaces:**
- Produces:
  - `floor_report(motifs: list[Motif], ctx) -> list[dict]`. One row per (motif, Disorder node, parent), with keys `motif_id, node, code, fsn, anchors, parent, parent_fsn, decision, blocking_descendant, blocking_fsn, anchor`. Rows are sorted by `(motif_id, node, parent)`.
  - CLI: `python -m semgen.floor_report --motifs PATH [--out FILE.tsv]` loads the real RF2, the map and PhecodeX, then prints a TSV.

- [ ] **Step 1: Write failing tests.**
  - `floor_report([fake_m1, fake_m2], ctx)` gives exactly the expected rows.
  - The output is deterministic.
  - The real test (`snomed`+`phecodex`) on `data/motifs/synthetic_motifs.json` contains the M3 `allowed` row and the M1 rows with the prototype's blockers.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → pass. Run the CLI once and save the TSV to `runs/floor_report.tsv` (git-ignored) for the user to review.
- [ ] **Step 5: Amend the main plan.** These are text edits only, with an "Amended by Stage 1" note on each.
  - **Task 13 guard:** replace "a `concept_lift` change's `after` is not descendant-or-self of every floor applicable to `before`" with "`ctx.floors.check_lift(change.before, change.after).ok` is False".
  - **Task 15 `run_header`:** add the S10 fields from `ctx.floors.provenance` and `config.floor_source`.
  - **Task 17 expectations:**
    - `test_m1_check2` lifts set is `set()` (both parents `outside_floor`).
    - `test_m2_check3` has no n1 lift.
    - `test_m3_anchor_lift` is unchanged.
    - `test_m4` RA is blocked `outside_floor`, not `no_floor`.
    - The README "blocked and why" table follows S7/S8.
  - **D2 row:** add "Superseded by docs/plans/stage1-phecodex-floors.md".
- [ ] **Step 6: Commit** `feat: floor review report; docs: amend main plan for PhecodeX floors`.

---

## Self-review notes

- **Spec coverage:** every rule in the spec's disorder-floor section maps to a task:
  - usable targets (S1, Task 2)
  - anchors with truncation (S3, Task 3)
  - membership (S4)
  - eligibility over all active descendants (S5)
  - downward-closed property and G1 under polyhierarchy (Task 3 tests)
  - CCSR is recorded as `unavailable` (S10). It needs the US Edition, which we don't have.
  - The spec's information-content ordering is not needed. We only ever test direct parents, so there is nothing to rank.
- **Not in this plan:** Stage 2 drug classes (RxNorm/RxClass), LOINC observable lifts, and ladder citations. Drugs and observables stay blocked `no_floor`, which is fail-closed.
- **Type consistency:**
  - `FloorDecision` is used unchanged by Tasks 3–5.
  - `GenContext` gains `floors` in Task 4. The main plan's Tasks 13–17 build `ctx` only through fixtures, so they are unaffected beyond the Task 5 text edits.
