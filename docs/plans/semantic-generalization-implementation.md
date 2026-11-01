# Semantic Generalization of Motifs — Implementation Plan (POC)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Red → green → refactor on every task. Do not start task N+1 until task N's tests pass and it has been reviewed.

**Goal:** A deterministic, symbolic engine that takes one validated motif and returns every legal, more general motif (a deduplicated lattice), with a change record on every edge and an independent proof that each candidate is more general.

**Architecture:** Read-only knowledge (SNOMED IS-A from local RF2 + one YAML config) → frozen Pydantic motif model → six independent operators, each returning `(new motif, change record)` → a policy guard plus an identity-map order proof on every move → breadth-first lattice → JSONL export. A test-only reference matcher proves on synthetic patients that a more general motif never matches fewer patients.

**Tech Stack:** Python 3.12, uv, Pydantic v2, PyYAML, Polars (RF2 reading), pytest, Hypothesis.

**Spec:** `docs/semantic-generalization-methodology.md`, **as amended by "Decisions that supersede the methodology" below**. Where the two disagree, the amendments win.

**Amended by Stage 1** (`docs/plans/stage1-phecodex-floors.md`): disorder floors are now derived from SNOMED→ICD-10→PhecodeX via `ctx.floors` (a `FloorPolicy`); the YAML `floors` list, `check_floors` and the `at_floor` reason no longer exist. Tasks 1–11 below describe the code as originally built and are kept for history.

---

## Decisions that supersede the methodology

These were settled in the design review. Each one changes or pins something in the methodology.

| # | Topic | Decision |
|---|---|---|
| D1 | Scope | POC. No support counting, utility, disclosure, BioPathNet calls, fuzzy/LLM matching, DuckDB, FalkorDB, rustworkx, clingo, Graphviz, Parquet, PhecodeX/ATC/LOINC/RxNorm tables. Deployment and licences are out of scope. |
| D2 | Floors | A flat list of floor concepts in YAML: `363346000` Malignant neoplastic disease, `73211009` Diabetes mellitus (marked DRAFT). A node's applicable floors are the listed floors its concept is descendant-or-self of. A lift target must be descendant-or-self of **every** applicable floor (G1). No applicable floor → no lift, logged `blocked: no_floor`. No Substance or Observable floors are invented, so those lifts are blocked. — **Superseded by Stage 1 (S1–S10).** |
| D3 | Lift blockers | Never lift a node that has a `value` (F7) or any concept-dependent attribute (G2). Attribute flags live in YAML; an attribute with no flag is treated as concept-dependent. `age_at_dx` = independent; `cumulative_dose` = dependent. |
| D4 | Intervals | Every interval stores `lo`, `hi`, `lo_closed`, `hi_closed`, `unit`. `None` bound = unbounded. "Unconstrained" = the value/attr/window is **absent**, never (−∞, ∞). |
| D5 | Ladders | A ladder is a laminar set of rungs (any two rungs are nested or disjoint), all in one unit. Coarsening moves to the **narrowest rung that strictly contains** the current interval; none → no move. The final "→ removed" step is not a rung (attribute removal does that). Ladders (DRAFT): LVEF `[0,40) [40,50) [50,55) [55,101) [0,50) [0,55)` (ESC `<40` convention); eGFR `[0,15) [15,30) [30,45) [45,60) [60,90) [90,∞) [30,60) [0,60)`; ALT ×ULN `[0,1] (1,3] (3,5] (5,20] (20,∞) (3,∞) (1,∞)`; age `[65,80) [90,∞) [65,∞)`; cumulative dose `[0,100) [100,250) [250,∞) [100,∞)`. |
| D6 | Time | Window = target time − source time in days. Ladder `[0,30] [0,90] [0,365] [0,∞)`. **"Co-occurs" is removed.** No time constraint = the `followed_by` edge is removed (edge removal). Negative lower bounds are rejected. Fractional days allowed. Matching semantics: "certainly within". |
| D7 | Hierarchy direction | Only three helpers read the IS-A graph: `is_descendant_or_self(concept, of_)` (ECL `<<`), `ancestors_or_self(c)` (`>>`), `ancestors(c)` (strict `>`). Lift: new code ∈ `parents(old)`, active, under every applicable floor. |
| D8 | Order proof | One-to-one semantics via the **identity map**: S′ node ids ⊆ S node ids; each kept node and edge is checked against the same-id original. No graph search, no rustworkx. |
| D9 | Order rules | Present node: equal type/role/polarity; S code is descendant-or-self of S′ code (context codes: equal); S′ value/attrs ⊆ S's and each contains S's. Absent node: S′ code is descendant-or-self of S code. Edge (keyed by ordered `(s,t)`): S relation ≤ S′ relation in the relation hierarchy, equal provenance, S′ window contains S window. Missing on S′ = unconstrained; present on S′ but missing on S = fail. |
| D10 | Legality ≠ order | A move is kept only if the **policy guard** (floors, protected nodes, absent nodes untouched, context edges never altered) and the order proof both pass. Either failing raises; a bug is never shipped silently. |
| D11 | Negation | Every operator skips absent nodes and edges touching them (`negation_policy.allow_drop_absent: false`). Absent nodes must be leaves attached only to the patient. Closed world: "absent X" = no fact whose code is X or a descendant of X. |
| D12 | Provenance | `extracted→asserted`, `ancestor→derived`, `enriched→context` (enriched = BioPathNet-predicted only). Relation relaxation applies to asserted edges only and changes only `rel`. Context edges can only be removed. |
| D13 | Edge removal | Never remove patient→anchor or any edge touching an absent node. Removing a patient→node edge removes that node and all its edges (X2). Then drop nodes no longer connected (ignoring direction) to the patient. At least one asserted edge must remain. |
| D14 | Loader rules | Exact FSN match against **active** concepts only; 0 or >1 matches → error. Reject: unknown edge endpoints, missing anchor, anchor not linked to patient, two edges with the same ordered `(s,t)` (G5), absent nodes that are not patient-only leaves, a finite `age_at_dx` interval at or above 90 (must be `[90,∞)`). |
| D15 | Motifs | M2 labels are `Diabetes mellitus type 1/2 (disorder)`. M3 anchor = `703228009` Non-small cell lung cancer with mutation in epidermal growth factor receptor (disorder); old n2 deleted. M4 ALT = `Alanine transaminase in serum (observable entity)` with value 3.6 `xULN`. Context ids use OptimusKG format (genes are real: TOP2B `ENSG00000077097`, EGFR `ENSG00000146648`; pathways/diseases are placeholders). `has_finding` is covered by a unit-test fixture. |
| D16 | Test matcher | Pure-Python, one-to-one, backtracking, closed-world; lives only under `tests/support/`; production code must not import it. |
| D17 | Run header | Records SNOMED release + edition, config SHA-256, `config_status: DRAFT`, `lvef_convention`, `temporal_semantics: certain`, closed-world statement, max depth. |

## Global Constraints

- Python `>=3.12`; managed with `uv`; src layout, package name `semgen`.
- Runtime deps only: `pydantic>=2.10`, `pyyaml>=6`, `polars>=1.19`. Dev deps only: `pytest>=8`, `hypothesis>=6`.
- RF2 directory default: `/Users/suryanshshivaprasad/Documents/HDX/SnomedCT_InternationalRF2_PRODUCTION_20260201T120000Z/Snapshot/Terminology`, overridable with env var `SEMGEN_RF2_DIR`. Tests needing it are marked `@pytest.mark.snomed` and skip if the folder is missing.
- RF2 reading: tab separator, every column as text, quoting off. IS-A = `typeId 116680003`, `characteristicTypeId 900000000000011006`, `active 1`. FSN = `typeId 900000000000003001`.
- Every operator is pure: it never mutates its input motif.
- Output must be deterministic: same inputs → byte-identical files (timestamps excluded).
- All YAML values are marked `DRAFT — not clinically approved`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Bound inclusivity at equal endpoints** — `[0,40]` must NOT be contained in `[0,40)`; LVEF 40 is not in `[0,40)`. Pinned in Task 1.
2. **Polyhierarchy escape** — a parent that is under one floor but not another must be blocked. Pinned in Task 6 (`test_lift_requires_every_applicable_floor`).
3. **Edge-removal cascades** — removing patient→drug in M1 must also drop drug→LVEF, drug→TOP2B and the orphaned TOP2B and pathway nodes, while LVEF stays (still linked to the patient). Pinned in Task 11.
4. **A value outside every rung** (LVEF 60, eGFR 120) — no move and no crash. Pinned in Task 8.
5. **Same child reached by two operators** (e.g. the age ladder end vs. attribute removal later) — one candidate, both change records kept. Pinned in Task 13.

---

## File structure

```
pyproject.toml                         package + deps + pytest markers
config/generalization.yaml             all DRAFT clinical choices (D2–D6, D12)
data/motifs/synthetic_motifs.json      M1–M4 (D15)
src/semgen/__init__.py
src/semgen/model.py                    Interval, Node, Edge, Motif (frozen)
src/semgen/config.py                   Pydantic config models, load_config, Ladder, RelationHierarchy
src/semgen/snomed.py                   RF2 loader, Hierarchy, cache, check_floors
src/semgen/motif_io.py                 load_motifs, FSN resolution, structural validation
src/semgen/canonical.py                canonical_json, motif_hash
src/semgen/operators/__init__.py       ALL_OPERATORS (fixed order)
src/semgen/operators/base.py           GenContext, ChangeRecord, Move, Blocked, OperatorResult, helpers
src/semgen/operators/concept_lift.py
src/semgen/operators/attribute_removal.py
src/semgen/operators/range_coarsening.py
src/semgen/operators/temporal_coarsening.py
src/semgen/operators/relation_relaxation.py
src/semgen/operators/edge_removal.py
src/semgen/order.py                    check_order, OrderResult
src/semgen/lattice.py                  guard, neighbors, enumerate_lattice, Lattice
src/semgen/export.py                   run header + JSONL writers
src/semgen/__main__.py                 CLI: python -m semgen run ...
tests/conftest.py                      fake hierarchy, fake M1/M2, ctx fixtures, real-RF2 fixtures
tests/fixtures/rf2/*.txt               tiny RF2 snapshot for loader tests
tests/support/matcher.py               test-only reference matcher (D16)
tests/support/patients.py              synthetic patient builders
tests/test_*.py                        one file per task
```

## Shared test fixtures (created in Task 1, extended as noted)

`tests/conftest.py` defines constants with real SCTIDs so unit tests read naturally but need no RF2:

```python
ROOT, DISEASE, MALIG, NEO_BREAST, MAL_THORAX, BRCA = "138875005","64572001","363346000","126926005","188361007","254837009"
DM, T1DM, T2DM, RA, RA_OLD_PARENT = "73211009","46635009","44054006","69896004","900000000000000001"  # last: inactive
CKD, BIGUANIDE, MET = "709044004","1363127000","372567009"
SUBST, ANTHRA, DOX, DAUNO = "105590001","372540003","372817009","372715008"
OBS, LVEF, GFR = "363787002","250908004","80274001"
```

Fake IS-A (child → parents): DISEASE→ROOT; MALIG→DISEASE; NEO_BREAST→DISEASE; MAL_THORAX→MALIG; BRCA→{NEO_BREAST, MAL_THORAX}; DM→DISEASE; T1DM→DM; T2DM→DM; CKD→DISEASE; RA→{DISEASE, RA_OLD_PARENT}; SUBST→ROOT; ANTHRA→SUBST; DOX→ANTHRA; DAUNO→ANTHRA; BIGUANIDE→SUBST; MET→BIGUANIDE; OBS→ROOT; LVEF→OBS; GFR→OBS. `RA_OLD_PARENT` is inactive. Fixture `fake_h` (Task 3 adds `Hierarchy.from_maps`; until then Task 1 only needs constants). Fixture `fake_m1` / `fake_m2`: M1/M2 from the methodology with these codes filled in and D15 values. Fixture `ctx` (Task 6): `GenContext(hierarchy=fake_h, config=load_config("config/generalization.yaml"))`. Fixtures `real_h`, `real_ctx`, `real_motifs` (Task 4) load the real RF2 once per session and are `snomed`-marked.

---

### Task 1: Package structure and data models

**Files:**
- Create: `pyproject.toml`, `src/semgen/__init__.py`, `src/semgen/model.py`, `tests/conftest.py`, `tests/test_model.py`

**Interfaces:**
- Produces:
  - `Interval(lo: float|None, hi: float|None, lo_closed: bool=True, hi_closed: bool=True, unit: str)` frozen; `Interval.point(x, unit)`; `Interval.closed(lo, hi, unit)`; `contains(other: Interval) -> bool`; `contains_point(x: float) -> bool`; `strictly_contains(other) -> bool`; `to_json() -> dict`.
  - `Node(id, type, role, label: str|None=None, code: str|None=None, polarity: Literal["present","absent"]="present", value: Interval|None=None, attrs: dict[str, Interval]={})` frozen.
  - `Edge(s, t, rel, prov: Literal["asserted","derived","context"], window: Interval|None=None, bpn_score: float|None=None)` frozen; property `key -> tuple[str,str]`.
  - `Motif(motif_id, anchor, nodes: tuple[Node,...], edges: tuple[Edge,...])` frozen; `node(id) -> Node`, `edge(s,t) -> Edge|None`, `node_ids -> frozenset[str]`, `replace_node(node) -> Motif`, `replace_edge(edge) -> Motif`, `without(node_ids: set, edge_keys: set) -> Motif`.
  - Constant `PATIENT_ID = "P"`.

- [ ] **Step 1: Write `pyproject.toml`** with hatchling, src layout, deps from Global Constraints, `[tool.pytest.ini_options] markers = ["snomed: needs local RF2"]`, `testpaths=["tests"]`. Run `uv sync` → succeeds.

- [ ] **Step 2: Write the failing tests** in `tests/test_model.py`

```python
from semgen.model import Interval, Node, Edge, Motif
import pytest
def iv(lo, hi, lc=True, hc=True, u="%"): return Interval(lo=lo, hi=hi, lo_closed=lc, hi_closed=hc, unit=u)

def test_point_inside_half_open():
    assert iv(0, 40, hc=False).contains_point(38)
    assert not iv(0, 40, hc=False).contains_point(40)
def test_equal_endpoint_inclusivity():
    assert not iv(0, 40, hc=False).contains(iv(0, 40))          # [0,40) does not contain [0,40]
    assert iv(0, 40).contains(iv(0, 40, hc=False))              # [0,40] contains [0,40)
def test_unbounded():
    assert iv(65, None).contains(iv(65, 80, hc=False))
    assert not iv(65, 80, hc=False).contains(iv(65, None))
def test_unit_mismatch_never_contains():
    assert not iv(0, 50, u="%").contains(iv(38, 38, u="xULN"))
def test_strictly_contains():
    assert iv(0, 50, hc=False).strictly_contains(iv(0, 40, hc=False))
    assert not iv(0, 40, hc=False).strictly_contains(iv(0, 40, hc=False))
def test_motif_is_frozen_and_replace_returns_new():
    m = Motif(motif_id="X", anchor="n1",
              nodes=(Node(id="P", type="Patient", role="patient"), Node(id="n1", type="Disorder", role="anchor", code="1")),
              edges=(Edge(s="P", t="n1", rel="has_condition", prov="asserted"),))
    m2 = m.replace_node(m.node("n1").model_copy(update={"code": "2"}))
    assert m.node("n1").code == "1" and m2.node("n1").code == "2"
    with pytest.raises(Exception): m.node("n1").code = "3"
    assert m.edge("P", "n1").key == ("P", "n1") and m.edge("n1", "P") is None
```

- [ ] **Step 3: Run** `uv run pytest tests/test_model.py -v` → FAIL (`ModuleNotFoundError: semgen.model`).

- [ ] **Step 4: Implement `src/semgen/model.py`.** Pydantic `BaseModel` with `model_config = ConfigDict(frozen=True)`. `contains(other)`: units equal, and on each side the other's bound is not outside ours, where for equal finite endpoints `other_closed ⇒ self_closed`; `None` on our side always passes, `None` on theirs fails unless ours is `None`. `strictly_contains = contains(other) and self != other`. Also create `tests/conftest.py` with the constants above.

- [ ] **Step 5: Run** `uv run pytest tests/test_model.py -v` → 6 passed.

- [ ] **Step 6: Commit** `feat: package skeleton and frozen motif data model`.

---

### Task 2: YAML configuration and Pydantic validation

**Files:**
- Create: `config/generalization.yaml`, `src/semgen/config.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: `Interval` (Task 1).
- Produces:
  - `Ladder(name: str, unit: str, rungs: tuple[Interval,...], applies_to_concepts: tuple[str,...]=(), applies_to_attr: str|None=None)`; `Ladder.next_rung(current: Interval) -> Interval|None` (narrowest rung strictly containing `current`; `None` if none or unit differs).
  - `RelationHierarchy(parents: dict[str,str])`; `parent(rel) -> str|None`; `leq(narrow, broad) -> bool` (reflexive-transitive).
  - `GenConfig` with: `status: str`, `lvef_convention: str`, `floors: tuple[str,...]`, `attribute_flags: dict[str, Literal["concept_dependent","concept_independent"]]`, `value_ladders: tuple[Ladder,...]`, `attr_ladders: tuple[Ladder,...]`, `time_ladder: Ladder`, `relations: RelationHierarchy`, `protected_roles: frozenset[str]`, `allow_drop_absent: bool`, `max_depth: int`; methods `value_ladder_for(code) -> Ladder|None`, `attr_ladder_for(name) -> Ladder|None`, `attr_is_concept_dependent(name) -> bool` (unflagged → `True`).
  - `load_config(path) -> GenConfig`; `config_sha256(path) -> str`; `ConfigError(Exception)`.

- [ ] **Step 1: Write `config/generalization.yaml`.** Top-level `status: "DRAFT — not clinically approved"`, `lvef_convention: ESC2022_lt40`, `floors` (D2, ids with label comments), `attribute_flags: {age_at_dx: concept_independent, cumulative_dose: concept_dependent}`, ladders from D5 and D6 (each with `unit`, family `bounds` `"[)"`, `"(]"` or `"[]"`, rungs as `[lo, hi]` with `null` for unbounded, or `{lo, hi, lo_closed, hi_closed}` for exceptions such as ALT `[0,1]`), value ladders `applies_to_concepts`: LVEF `250908004`, eGFR `80274001`, ALT `364571000119101`; attr ladders `applies_to_attr`: `age_at_dx` (unit `a`), `cumulative_dose` (unit `mg/m2`); `relation_parents: {administered_drug: exposed_to_drug, has_finding: has_observation}`; `protected_roles: [patient, anchor]`; `negation_policy: {allow_drop_absent: false}`; `max_depth: 4`. An open upper bound is always open (`hi_closed: false` when `hi: null`).

- [ ] **Step 2: Write the failing tests** in `tests/test_config.py`

```python
from semgen.config import load_config, ConfigError
from semgen.model import Interval
import pytest, yaml
CFG = "config/generalization.yaml"
def test_loads_and_is_draft():
    c = load_config(CFG)
    assert c.status.startswith("DRAFT") and c.floors == ("363346000", "73211009") and c.max_depth == 4
def test_lvef_ladder_walk():
    lad = load_config(CFG).value_ladder_for("250908004")
    walk, cur = [], Interval.point(38, "%")
    while (cur := lad.next_rung(cur)) is not None: walk.append((cur.lo, cur.hi, cur.hi_closed))
    assert walk == [(0, 40, False), (0, 50, False), (0, 55, False)]
def test_alt_ladder_walk_and_boundary():
    lad = load_config(CFG).value_ladder_for("364571000119101")
    assert lad.next_rung(Interval.point(3.0, "xULN")).hi == 3            # 3.0 is in (1,3]
    walk, cur = [], Interval.point(3.6, "xULN")
    while (cur := lad.next_rung(cur)) is not None: walk.append((cur.lo, cur.hi))
    assert walk == [(3, 5), (3, None), (1, None)]
def test_time_ladder_walk():
    lad, walk, cur = load_config(CFG).time_ladder, [], Interval.point(23, "d")
    while (cur := lad.next_rung(cur)) is not None: walk.append((cur.lo, cur.hi))
    assert walk == [(0, 30), (0, 90), (0, 365), (0, None)]
def test_value_outside_every_rung_has_no_move():
    assert load_config(CFG).value_ladder_for("250908004").next_rung(Interval.point(120, "%")) is None
def test_unflagged_attr_is_concept_dependent():
    c = load_config(CFG)
    assert c.attr_is_concept_dependent("cumulative_dose") and not c.attr_is_concept_dependent("age_at_dx")
    assert c.attr_is_concept_dependent("never_seen_attr")
def test_relation_leq():
    r = load_config(CFG).relations
    assert r.leq("administered_drug", "exposed_to_drug") and r.leq("has_condition", "has_condition")
    assert not r.leq("exposed_to_drug", "administered_drug")
@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d["value_ladders"]["lvef"]["rungs"].append([35, 45]), "laminar"),
    (lambda d: d["time_ladder"]["rungs"].append([-5, 30]), "negative"),
    (lambda d: d["relation_parents"].update({"exposed_to_drug": "administered_drug"}), "cycle"),
    (lambda d: d.update({"floors": ["not-an-id"]}), "floor"),
])
def test_invalid_configs_fail_at_load(tmp_path, mutate, msg):
    d = yaml.safe_load(open(CFG)); mutate(d); p = tmp_path / "c.yaml"; p.write_text(yaml.safe_dump(d))
    with pytest.raises(ConfigError, match=msg): load_config(p)
```

(Ladder keys in YAML: `value_ladders: {lvef: ..., egfr: ..., alt_xuln: ...}`, `attr_ladders: {age: ..., cumulative_dose: ...}`.)

- [ ] **Step 3: Run** `uv run pytest tests/test_config.py -v` → FAIL (`ModuleNotFoundError: semgen.config`).

- [ ] **Step 4: Implement `src/semgen/config.py`.** Pydantic models for the raw YAML, converted to `GenConfig`. Validators raise `ConfigError` with these words in the message: `laminar` (two rungs overlap without nesting), `unit` (rung unit differs), `negative` (time rung lower bound < 0), `cycle` (relation parents), `floor` (floor not all digits). `next_rung`: among rungs with `strictly_contains(current)`, return the one that every other candidate contains (laminarity makes it unique).

- [ ] **Step 5: Run** `uv run pytest tests/test_config.py -v` → 11 passed.

- [ ] **Step 6: Commit** `feat: DRAFT YAML config with validated ladders, floors and relation hierarchy`.

---

### Task 3: SNOMED RF2 loader

**Files:**
- Create: `src/semgen/snomed.py`, `tests/fixtures/rf2/sct2_Concept_Snapshot_INT_20990101.txt`, `tests/fixtures/rf2/sct2_Description_Snapshot-en_INT_20990101.txt`, `tests/fixtures/rf2/sct2_Relationship_Snapshot_INT_20990101.txt`, `tests/test_snomed.py`
- Modify: `tests/conftest.py` (add `fake_h`, `real_h`)

**Interfaces:**
- Consumes: `GenConfig.floors` (Task 2).
- Produces:
  - `Hierarchy` with attributes `release: str`, `edition: str`; methods `parents(c) -> frozenset[str]`, `is_active(c) -> bool`, `fsn(c) -> str|None`, `resolve_fsn(label) -> str` (raises `FsnError` on 0 or >1 active matches), `ancestors(c) -> frozenset[str]` (strict, cached), `ancestors_or_self(c)`, `is_descendant_or_self(concept, of_) -> bool`, `depth(c) -> int` (shortest distance to `138875005`).
  - `Hierarchy.from_maps(parents: dict[str,set[str]], fsn: dict[str,str], active: set[str], release="TEST", edition="TEST")`.
  - `load_rf2(terminology_dir: Path, cache_dir: Path|None=None) -> Hierarchy`; `default_rf2_dir() -> Path`; `check_floors(config, h) -> None` (raises `ConfigError` if a floor is missing or inactive).

- [ ] **Step 1: Write the fixture RF2 files** (same headers as the real release). Content: concepts A (root `138875005`), B, C, D active; E inactive; descriptions: FSN "Bee (disorder)" for B; FSN "Dup (disorder)" for both D (active) and E (inactive); a synonym row (typeId `900000000000013009`) "Bee" for B. Relationships: B IS-A A inferred active; C IS-A B inferred active; D IS-A A inferred active; C IS-A D **stated** (`900000000000010007`) active (must be ignored); D IS-A B inferred **inactive** (must be ignored).

- [ ] **Step 2: Write the failing tests** in `tests/test_snomed.py`

```python
from semgen.snomed import load_rf2, FsnError, check_floors
from tests.conftest import *   # constants
import pytest
FIX = "tests/fixtures/rf2"
def test_inferred_active_isa_only(tmp_path):
    h = load_rf2(FIX, cache_dir=tmp_path)
    assert h.parents("C") == {"B"} and h.parents("D") == {"138875005"}
    assert h.release == "20990101"
def test_fsn_resolution_uses_active_concepts_only(tmp_path):
    h = load_rf2(FIX, cache_dir=tmp_path)
    assert h.resolve_fsn("Dup (disorder)") == "D" and h.resolve_fsn("Bee (disorder)") == "B"
    with pytest.raises(FsnError): h.resolve_fsn("Bee")            # synonym, not FSN
def test_cache_roundtrip(tmp_path):
    a = load_rf2(FIX, cache_dir=tmp_path); b = load_rf2(FIX, cache_dir=tmp_path)
    assert a.parents("C") == b.parents("C") and any(tmp_path.glob("snomed_20990101*.pkl"))
def test_direction_helpers(fake_h):
    assert fake_h.is_descendant_or_self(BRCA, MALIG)
    assert not fake_h.is_descendant_or_self(MALIG, BRCA)
    assert fake_h.is_descendant_or_self(MALIG, MALIG)
    assert MALIG in fake_h.ancestors(BRCA) and BRCA not in fake_h.ancestors(BRCA)
    assert BRCA in fake_h.ancestors_or_self(BRCA)
    assert not fake_h.is_descendant_or_self(NEO_BREAST, MALIG)
def test_check_floors_rejects_unknown(fake_h, tmp_path):
    from semgen.config import load_config, ConfigError
    c = load_config("config/generalization.yaml")
    check_floors(c, fake_h)
    with pytest.raises(ConfigError, match="floor"):
        check_floors(c.model_copy(update={"floors": ("123",)}), fake_h)

@pytest.mark.snomed
def test_real_direction(real_h):
    assert real_h.is_descendant_or_self(BRCA, MALIG) and not real_h.is_descendant_or_self(MALIG, BRCA)
    assert real_h.is_descendant_or_self(T2DM, DM)
    for c in ("709044004", "233703007", RA, T2DM): assert not real_h.is_descendant_or_self(c, MALIG)
    assert real_h.parents(BRCA) == {NEO_BREAST, MAL_THORAX}
    assert real_h.parents("703228009") == {"254637007"}
    assert real_h.resolve_fsn("Left ventricular ejection fraction (observable entity)") == LVEF
    assert real_h.release == "20260201" and real_h.edition == "International"
```

- [ ] **Step 3: Run** `uv run pytest tests/test_snomed.py -v` → FAIL (`ModuleNotFoundError: semgen.snomed`).

- [ ] **Step 4: Implement `src/semgen/snomed.py`.** Polars `read_csv(separator="\t", infer_schema=False, quote_char=None)`. Release date from the file name `_INT_(\d{8})`; edition `"International"` when the name contains `_INT_`. Cache: pickle to `cache_dir/snomed_<release>.pkl` (default `data/cache`). `ancestors` uses `functools.cache` or an explicit memo dict. Add fixtures `fake_h` (built with `from_maps` from the conftest IS-A table; RA_OLD_PARENT inactive) and session-scoped `real_h` (skips if `default_rf2_dir()` is missing).

- [ ] **Step 5: Run** `uv run pytest tests/test_snomed.py -v` → 6 passed (first real run builds the cache and takes about a minute).

- [ ] **Step 6: Commit** `feat: RF2 loader with inferred IS-A, FSN lookup, direction helpers and cache`.

---

### Task 4: Motif JSON loader and exact FSN resolution

**Files:**
- Create: `src/semgen/motif_io.py`, `data/motifs/synthetic_motifs.json`, `tests/test_motif_io.py`
- Modify: `tests/conftest.py` (add `fake_m1`, `fake_m2`, `real_motifs`)

**Interfaces:**
- Consumes: `Motif`, `Interval` (Task 1); `Hierarchy.resolve_fsn` (Task 3).
- Produces: `load_motifs(path, h: Hierarchy) -> list[Motif]`; `parse_motif(raw: dict, h: Hierarchy|None) -> Motif` (with `h=None`, codes must already be filled); `MotifError(Exception)`.

- [ ] **Step 1: Write `data/motifs/synthetic_motifs.json`** = the methodology's M1–M4 with D15 changes. Input format kept from the methodology: `"value": {"interval": [a,b], "unit": u}` and `"time": {"window": [a,b], "unit": "d"}` (both closed); `"attrs": {name: {"interval": [...], "unit": ...}}`. Context codes: `ENSG00000077097` (TOP2B), `ENSG00000146648` (EGFR), `REACT:R-HSA-PLACEHOLDER-1`, `REACT:R-HSA-PLACEHOLDER-2`, `MESH:PLACEHOLDER-LACTIC-ACIDOSIS`, `MESH:PLACEHOLDER-DILI`.

- [ ] **Step 2: Write the failing tests** in `tests/test_motif_io.py`

```python
from semgen.motif_io import parse_motif, MotifError
import pytest, copy
def base():  # minimal valid motif, codes already filled
    return {"motif_id": "T", "anchor": "n1",
            "nodes": [{"id": "P", "type": "Patient", "role": "patient"},
                      {"id": "n1", "type": "Disorder", "code": "1", "polarity": "present", "role": "anchor"},
                      {"id": "n2", "type": "Disorder", "code": "2", "polarity": "absent", "role": "modifier"}],
            "edges": [{"s": "P", "t": "n1", "rel": "has_condition", "prov": "asserted"},
                      {"s": "P", "t": "n2", "rel": "has_condition", "prov": "asserted"}]}
def test_absent_node_must_be_patient_leaf():
    d = base(); d["edges"].append({"s": "n1", "t": "n2", "rel": "x", "prov": "asserted"})
    with pytest.raises(MotifError, match="absent"): parse_motif(d, None)
@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d["edges"].append({"s": "P", "t": "zz", "rel": "r", "prov": "asserted"}), "unknown node"),
    (lambda d: d.update(anchor="nX"), "anchor"),
    (lambda d: d["edges"].pop(0), "anchor"),
    (lambda d: d["edges"].append({"s": "P", "t": "n1", "rel": "other", "prov": "asserted"}), "parallel"),
    (lambda d: d["nodes"][1].update(attrs={"age_at_dx": {"interval": [92, 92], "unit": "a"}}), "90"),
])
def test_structural_rejections(mutate, msg):
    d = base(); mutate(d)
    with pytest.raises(MotifError, match=msg): parse_motif(d, None)
def test_window_becomes_closed_interval():
    d = base(); d["nodes"].append({"id": "n3", "type": "Substance", "code": "3", "polarity": "present", "role": "exposure"})
    d["edges"] += [{"s": "P", "t": "n3", "rel": "administered_drug", "prov": "asserted"},
                   {"s": "n3", "t": "n1", "rel": "followed_by", "prov": "asserted", "time": {"window": [23, 23], "unit": "d"}}]
    w = parse_motif(d, None).edge("n3", "n1").window
    assert (w.lo, w.hi, w.lo_closed, w.hi_closed, w.unit) == (23, 23, True, True, "d")

@pytest.mark.snomed
def test_real_motifs_resolve(real_motifs):
    ids = {m.motif_id: m for m in real_motifs}
    assert set(ids) == {"M1", "M2", "M3", "M4"}
    assert ids["M2"].node("n1").code == "44054006" and ids["M2"].node("n2").code == "46635009"
    assert ids["M3"].node(ids["M3"].anchor).code == "703228009"
    assert ids["M4"].node("n3").code == "364571000119101" and ids["M4"].node("n3").value.unit == "xULN"
```

- [ ] **Step 3: Run** `uv run pytest tests/test_motif_io.py -v` → FAIL (`ModuleNotFoundError: semgen.motif_io`).

- [ ] **Step 4: Implement `src/semgen/motif_io.py`.** Check order: unknown endpoints → anchor exists → patient→anchor edge exists → parallel `(s,t)` → absent nodes have exactly one incident edge and it is `P→node` → `age_at_dx` with finite `hi` and `lo >= 90` → resolve null codes with `h.resolve_fsn(label)` (error names the label). Error messages contain the words matched above. Add `fake_m1`/`fake_m2` (Python dicts → `parse_motif(d, None)` using conftest codes, M1 n4/n5 context with OptimusKG ids) and session `real_motifs` fixtures.

- [ ] **Step 5: Run** `uv run pytest tests/test_motif_io.py -v` → 8 passed.

- [ ] **Step 6: Commit** `feat: motif loader with exact active-FSN resolution and structural checks`.

---

### Task 5: Motif canonicalization and hashing

**Files:**
- Create: `src/semgen/canonical.py`, `tests/test_canonical.py`

**Interfaces:**
- Consumes: `Motif` (Task 1).
- Produces: `canonical_json(m: Motif) -> str`; `motif_hash(m: Motif) -> str` (first 16 hex chars of SHA-256 of `canonical_json`).

- [ ] **Step 1: Write the failing tests**

```python
from hypothesis import given, strategies as st
from semgen.canonical import canonical_json, motif_hash
def test_hash_is_short_hex(fake_m1): h = motif_hash(fake_m1); assert len(h) == 16 and int(h, 16) >= 0
def test_label_does_not_change_hash(fake_m1):
    n = fake_m1.node("n1"); assert motif_hash(fake_m1.replace_node(n.model_copy(update={"label": "x"}))) == motif_hash(fake_m1)
def test_code_change_changes_hash(fake_m1):
    n = fake_m1.node("n1"); assert motif_hash(fake_m1.replace_node(n.model_copy(update={"code": "1"}))) != motif_hash(fake_m1)
@given(st.permutations(range(6)), st.permutations(range(6)))
def test_order_independent(fake_m1, pn, pe):
    m = fake_m1.model_copy(update={"nodes": tuple(fake_m1.nodes[i] for i in pn), "edges": tuple(fake_m1.edges[i] for i in pe)})
    assert canonical_json(m) == canonical_json(fake_m1)
```

(Use `settings(suppress_health_check=[HealthCheck.function_scoped_fixture])` on the Hypothesis test.)

- [ ] **Step 2: Run** `uv run pytest tests/test_canonical.py -v` → FAIL (import error).

- [ ] **Step 3: Implement.** Sort nodes by `id` and edges by `(s, t, rel)`; drop `label` (display only); `json.dumps(..., sort_keys=True, separators=(",", ":"))`; numbers serialised with `repr`-stable floats (`float(x)` then `json`).

- [ ] **Step 4: Run** `uv run pytest tests/test_canonical.py -v` → 4 passed.

- [ ] **Step 5: Commit** `feat: canonical motif JSON and stable hash`.

---

### Task 6: Concept lift operator

**Files:**
- Create: `src/semgen/operators/__init__.py`, `src/semgen/operators/base.py`, `src/semgen/operators/concept_lift.py`, `tests/test_op_concept_lift.py`
- Modify: `tests/conftest.py` (add `ctx`, `real_ctx`)

**Interfaces:**
- Consumes: `Hierarchy` (Task 3), `GenConfig` (Task 2), `Motif` (Task 1).
- Produces (base, shared by Tasks 6–11):
  - `GenContext(hierarchy: Hierarchy, config: GenConfig)` frozen dataclass.
  - `ChangeRecord(op: str, target: str, field: str, before: Any, after: Any, evidence: dict)` frozen; JSON-serialisable.
  - `Move(child: Motif, change: ChangeRecord)`.
  - `Blocked(op: str, target: str, reason: str, detail: dict)`.
  - `OperatorResult(moves: list[Move], blocked: list[Blocked])`.
  - `Operator = Callable[[Motif, GenContext], OperatorResult]`.
  - `is_absent_touching(motif, edge) -> bool`; `CLINICAL_TYPES = {"Disorder","Substance","Observable","Procedure","Finding"}`.
- Produces: `concept_lift(motif, ctx) -> OperatorResult`. Op name `"concept_lift"`. Blocked reasons: `no_floor`, `carries_value`, `concept_dependent_attr`, `at_floor`, `outside_floor`, `inactive_parent`.

- [ ] **Step 1: Write the failing tests**

```python
from semgen.operators.concept_lift import concept_lift
from semgen.model import Interval
from tests.conftest import *
def reasons(r): return {(b.target, b.reason) for b in r.blocked}
def test_breast_cancer_lifts_only_inside_floor(ctx, fake_m1):
    r = concept_lift(fake_m1, ctx)
    lifted = {(mv.change.target, mv.change.after) for mv in r.moves}
    assert ("n1", MAL_THORAX) in lifted and ("n1", NEO_BREAST) not in lifted
    assert ("n1", "outside_floor") in reasons(r)
    mv = next(m for m in r.moves if m.change.target == "n1")
    assert mv.change.before == BRCA and mv.change.evidence["floors"] == [MALIG]
def test_drug_with_dependent_dose_is_blocked(ctx, fake_m1):
    r = concept_lift(fake_m1, ctx)
    assert ("n2", "concept_dependent_attr") in reasons(r) and not any(m.change.target == "n2" for m in r.moves)
def test_drug_without_attrs_has_no_floor(ctx, fake_m2):
    assert ("n3", "no_floor") in reasons(concept_lift(fake_m2, ctx))        # metformin
def test_node_with_value_is_never_lifted(ctx, fake_m1):
    assert ("n3", "carries_value") in reasons(concept_lift(fake_m1, ctx))
def test_absent_context_patient_never_touched(ctx, fake_m1, fake_m2):
    assert "n2" not in {m.change.target for m in concept_lift(fake_m2, ctx).moves}   # absent T1DM
    assert not {m.change.target for m in concept_lift(fake_m1, ctx).moves} & {"P", "n4", "n5"}
def test_t2dm_lifts_to_dm_then_stops_at_floor(ctx, fake_m2):
    mv = next(m for m in concept_lift(fake_m2, ctx).moves if m.change.target == "n1"); assert mv.change.after == DM
    assert ("n1", "at_floor") in reasons(concept_lift(mv.child, ctx))
def test_lift_requires_every_applicable_floor(ctx):
    from semgen.snomed import Hierarchy
    from semgen.operators.base import GenContext
    h = Hierarchy.from_maps({"X": {"Y", DM}, "Y": {MALIG}, MALIG: {DISEASE}, DM: {DISEASE}, DISEASE: {ROOT}},
                            {}, {"X", "Y", MALIG, DM, DISEASE, ROOT})
    m = one_node_motif("X")                       # helper in conftest: P -has_condition-> n1(anchor, code)
    r = concept_lift(m, GenContext(hierarchy=h, config=ctx.config))
    assert r.moves == [] and ("n1", "outside_floor") in reasons(r)
def test_inactive_parent_skipped(ctx, fake_h):
    from semgen.operators.base import GenContext
    c = GenContext(hierarchy=fake_h, config=ctx.config.model_copy(update={"floors": (DISEASE,)}))
    r = concept_lift(one_node_motif(RA), c)
    assert [m.change.after for m in r.moves] == [DISEASE] and ("n1", "inactive_parent") in reasons(r)
def test_unflagged_attr_blocks(ctx, fake_m2):
    n = fake_m2.node("n1"); m = fake_m2.replace_node(n.model_copy(update={"attrs": {"mystery": Interval.point(1, "x")}}))
    assert ("n1", "concept_dependent_attr") in reasons(concept_lift(m, ctx))
def test_input_not_mutated(ctx, fake_m1):
    from semgen.canonical import canonical_json
    before = canonical_json(fake_m1); concept_lift(fake_m1, ctx); assert canonical_json(fake_m1) == before
```

(Add `one_node_motif(code) -> Motif` to `tests/conftest.py`: nodes `P` and `n1` (Disorder, anchor, present, `code`), one asserted `P→n1 has_condition` edge. Import `Interval` from `semgen.model`.)

- [ ] **Step 2: Run** `uv run pytest tests/test_op_concept_lift.py -v` → FAIL (import error).

- [ ] **Step 3: Implement `base.py`, then `concept_lift`.** For each node, in id order: skip unless `polarity == "present"`, `type in CLINICAL_TYPES`, role not `context`/`patient`. Check in this order, emitting one `Blocked` and moving on: `value` set → `carries_value`; any attr with `attr_is_concept_dependent` → `concept_dependent_attr`; applicable floors `F = [f for f in config.floors if h.is_descendant_or_self(code, f)]` empty → `no_floor`; `code in F` → `at_floor`. Then for each parent `p` in sorted `h.parents(code)`: inactive → `inactive_parent`; not under every floor in `F` → `outside_floor` (detail names the escaped floor); else a `Move` with `evidence={"floors": F, "parent_fsn": h.fsn(p), "depth_before": h.depth(code), "depth_after": h.depth(p)}`. `ALL_OPERATORS` in `operators/__init__.py` starts as `[concept_lift]`.

- [ ] **Step 4: Run** `uv run pytest tests/test_op_concept_lift.py -v` → 10 passed.

- [ ] **Step 5: Commit** `feat: concept lift with every-floor rule, value/attr blockers and blocked log`.

---

### Task 7: Attribute removal operator

**Files:**
- Create: `src/semgen/operators/attribute_removal.py`, `tests/test_op_attribute_removal.py`
- Modify: `src/semgen/operators/__init__.py` (append)

**Interfaces:**
- Consumes: base (Task 6).
- Produces: `attribute_removal(motif, ctx) -> OperatorResult`. Op `"attribute_removal"`. `field` is `"value"` or `"attrs.<name>"`; `after` is `None`.

- [ ] **Step 1: Write the failing tests**

```python
from semgen.operators.attribute_removal import attribute_removal
from semgen.model import Interval
def test_m1_removals(ctx, fake_m1):
    got = {(m.change.target, m.change.field) for m in attribute_removal(fake_m1, ctx).moves}
    assert got == {("n1", "attrs.age_at_dx"), ("n2", "attrs.cumulative_dose"), ("n3", "value")}
def test_child_lacks_only_that_field(ctx, fake_m1):
    mv = next(m for m in attribute_removal(fake_m1, ctx).moves if m.change.field == "value")
    assert mv.child.node("n3").value is None and mv.child.node("n1").attrs == fake_m1.node("n1").attrs
    assert mv.change.before["lo"] == 38
def test_absent_nodes_skipped(ctx, fake_m2):
    n = fake_m2.node("n2"); m = fake_m2.replace_node(n.model_copy(update={"value": Interval.point(1, "x")}))
    assert all(mv.change.target != "n2" for mv in attribute_removal(m, ctx).moves)
```

- [ ] **Step 2: Run** `uv run pytest tests/test_op_attribute_removal.py -v` → FAIL (import error).

- [ ] **Step 3: Implement.** Present, non-patient nodes in id order; one move per attr (sorted) and one for `value`. `before` = `Interval.to_json()`.

- [ ] **Step 4: Run** → 3 passed. **Step 5: Commit** `feat: attribute removal operator`.

---

### Task 8: Numeric range coarsening operator

**Files:**
- Create: `src/semgen/operators/range_coarsening.py`, `tests/test_op_range_coarsening.py`
- Modify: `src/semgen/operators/__init__.py` (append)

**Interfaces:**
- Consumes: `GenConfig.value_ladder_for`, `attr_ladder_for`, `Ladder.next_rung` (Task 2); base (Task 6).
- Produces: `range_coarsening(motif, ctx) -> OperatorResult`. Op `"range_coarsening"`; `field` as in Task 7; `evidence={"ladder": name}`. Blocked reasons: `no_ladder`, `unit_mismatch`.

- [ ] **Step 1: Write the failing tests**

```python
from semgen.operators.range_coarsening import range_coarsening
from semgen.model import Interval
def step(ctx, m, target, field):
    return next(mv for mv in range_coarsening(m, ctx).moves if (mv.change.target, mv.change.field) == (target, field))
def test_m1_first_steps(ctx, fake_m1):
    got = {(mv.change.target, mv.change.field): (mv.change.after["lo"], mv.change.after["hi"]) for mv in range_coarsening(fake_m1, ctx).moves}
    assert got == {("n3", "value"): (0, 40), ("n1", "attrs.age_at_dx"): (65, 80), ("n2", "attrs.cumulative_dose"): (250, None)}
def test_lvef_walk_to_end(ctx, fake_m1):
    m, walk = fake_m1, []
    while True:
        mvs = [mv for mv in range_coarsening(m, ctx).moves if (mv.change.target, mv.change.field) == ("n3", "value")]
        if not mvs: break
        m = mvs[0].child; walk.append((m.node("n3").value.lo, m.node("n3").value.hi))
    assert walk == [(0, 40), (0, 50), (0, 55)]
def test_value_outside_every_rung(ctx, fake_m1):
    n = fake_m1.node("n3"); m = fake_m1.replace_node(n.model_copy(update={"value": Interval.point(120, "%")}))
    assert not [mv for mv in range_coarsening(m, ctx).moves if mv.change.target == "n3"]
def test_unit_mismatch_blocked(ctx, fake_m1):
    n = fake_m1.node("n3"); m = fake_m1.replace_node(n.model_copy(update={"value": Interval.point(38, "fraction")}))
    assert any(b.reason == "unit_mismatch" for b in range_coarsening(m, ctx).blocked)
def test_absent_nodes_skipped(ctx, fake_m2):
    assert all(mv.change.target != "n2" for mv in range_coarsening(fake_m2, ctx).moves)
```

- [ ] **Step 2: Run** → FAIL (import error).

- [ ] **Step 3: Implement.** Present non-patient nodes, id order. Node `value` uses `value_ladder_for(node.code)`; each attr uses `attr_ladder_for(name)`. Ladder missing → `no_ladder`; unit differs → `unit_mismatch`; `next_rung` `None` → nothing.

- [ ] **Step 4: Run** → 5 passed. **Step 5: Commit** `feat: numeric range coarsening on laminar ladders`.

---

### Task 9: Temporal coarsening operator

**Files:**
- Create: `src/semgen/operators/temporal_coarsening.py`, `tests/test_op_temporal_coarsening.py`
- Modify: `src/semgen/operators/__init__.py` (append)

**Interfaces:**
- Consumes: `GenConfig.time_ladder` (Task 2); base (Task 6).
- Produces: `temporal_coarsening(motif, ctx) -> OperatorResult`. Op `"temporal_coarsening"`; `target = "s->t"`; `field = "window"`.

- [ ] **Step 1: Write the failing tests**

```python
from semgen.operators.temporal_coarsening import temporal_coarsening
def test_walk_23_days(ctx, fake_m1):
    m, walk = fake_m1, []
    while (mvs := temporal_coarsening(m, ctx).moves):
        m = mvs[0].child; w = m.edge("n2", "n3").window; walk.append((w.lo, w.hi))
    assert walk == [(0, 30), (0, 90), (0, 365), (0, None)]
def test_lower_bound_never_negative_and_direction_kept(ctx, fake_m1):
    for mv in temporal_coarsening(fake_m1, ctx).moves:
        e = mv.child.edge("n2", "n3"); assert e.window.lo >= 0 and mv.child.edge("n3", "n2") is None
def test_180_days_jumps_to_365(ctx, fake_m2):
    assert temporal_coarsening(fake_m2, ctx).moves[0].change.after["hi"] == 365
def test_edges_without_window_untouched(ctx, fake_m1):
    assert {mv.change.target for mv in temporal_coarsening(fake_m1, ctx).moves} == {"n2->n3"}
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (edges with a window, sorted by key; skip edges touching absent nodes). **Step 4: Run** → 4 passed. **Step 5: Commit** `feat: temporal coarsening (co-occurs removed)`.

---

### Task 10: Relation relaxation operator

**Files:**
- Create: `src/semgen/operators/relation_relaxation.py`, `tests/test_op_relation_relaxation.py`
- Modify: `src/semgen/operators/__init__.py` (append)

**Interfaces:**
- Consumes: `GenConfig.relations` (Task 2); base (Task 6).
- Produces: `relation_relaxation(motif, ctx) -> OperatorResult`. Op `"relation_relaxation"`; `target="s->t"`; `field="rel"`.

- [ ] **Step 1: Write the failing tests**

```python
from semgen.operators.relation_relaxation import relation_relaxation
from semgen.model import Edge
def test_m1_administered_drug(ctx, fake_m1):
    (mv,) = relation_relaxation(fake_m1, ctx).moves
    assert (mv.change.target, mv.change.before, mv.change.after) == ("P->n2", "administered_drug", "exposed_to_drug")
def test_only_rel_changes(ctx, fake_m1):
    (mv,) = relation_relaxation(fake_m1, ctx).moves
    a, b = fake_m1.edge("P", "n2"), mv.child.edge("P", "n2")
    assert a.model_dump(exclude={"rel"}) == b.model_dump(exclude={"rel"})
def test_has_finding_fixture(ctx, fake_m1):
    m = fake_m1.replace_edge(Edge(s="P", t="n1", rel="has_finding", prov="asserted"))
    assert any(mv.change.after == "has_observation" for mv in relation_relaxation(m, ctx).moves)
def test_context_edges_never_relaxed(ctx, fake_m1):
    m = fake_m1.replace_edge(fake_m1.edge("n2", "n4").model_copy(update={"rel": "administered_drug"}))
    assert all(mv.change.target != "n2->n4" for mv in relation_relaxation(m, ctx).moves)
def test_edge_into_absent_node_never_relaxed(ctx, fake_m2):
    m = fake_m2.replace_edge(fake_m2.edge("P", "n2").model_copy(update={"rel": "has_finding"}))
    assert all(mv.change.target != "P->n2" for mv in relation_relaxation(m, ctx).moves)
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (asserted edges only, sorted by key, skip absent-touching, one step via `relations.parent`). **Step 4: Run** → 5 passed. **Step 5: Commit** `feat: relation relaxation on asserted edges only`.

---

### Task 11: Edge removal with orphan-node cleanup

**Files:**
- Create: `src/semgen/operators/edge_removal.py`, `tests/test_op_edge_removal.py`
- Modify: `src/semgen/operators/__init__.py` (append; final order: lift, attribute removal, range, temporal, relation, edge removal)

**Interfaces:**
- Consumes: base (Task 6); `Motif.without` (Task 1).
- Produces: `edge_removal(motif, ctx) -> OperatorResult`. Op `"edge_removal"`; `target="s->t"`; `field="edge"`; `evidence={"removed_nodes": [...], "removed_edges": [...]}` (sorted). Blocked reasons: `protected_anchor_edge`, `touches_absent`, `no_asserted_left`, `would_drop_protected`.

- [ ] **Step 1: Write the failing tests**

```python
from semgen.operators.edge_removal import edge_removal
def by_target(r): return {mv.change.target: mv for mv in r.moves}
def test_gene_pathway_edge_drops_pathway(ctx, fake_m1):
    mv = by_target(edge_removal(fake_m1, ctx))["n4->n5"]
    assert "n5" not in mv.child.node_ids and "n4" in mv.child.node_ids
def test_drug_gene_edge_drops_gene_and_pathway(ctx, fake_m1):
    mv = by_target(edge_removal(fake_m1, ctx))["n2->n4"]
    assert mv.change.evidence["removed_nodes"] == ["n4", "n5"]
def test_patient_drug_edge_cascades(ctx, fake_m1):
    c = by_target(edge_removal(fake_m1, ctx))["P->n2"].child
    assert {"n2", "n4", "n5"}.isdisjoint(c.node_ids) and "n3" in c.node_ids and c.edge("n2", "n3") is None
def test_followed_by_removal_keeps_both_nodes(ctx, fake_m1):
    c = by_target(edge_removal(fake_m1, ctx))["n2->n3"].child
    assert {"n2", "n3"} <= c.node_ids
def test_protected_edges(ctx, fake_m1, fake_m2):
    assert "P->n1" not in by_target(edge_removal(fake_m1, ctx))
    r2 = edge_removal(fake_m2, ctx)
    assert "P->n2" not in by_target(r2) and any(b.reason == "touches_absent" for b in r2.blocked)
def test_last_asserted_edge_kept(ctx, fake_m1):
    m = fake_m1
    while (mvs := [mv for mv in edge_removal(m, ctx).moves]): m = mvs[0].child
    assert any(e.prov == "asserted" for e in m.edges) and m.anchor in m.node_ids
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement.** For each edge (sorted key): skip `P→anchor` (`protected_anchor_edge`) and absent-touching (`touches_absent`). Remove the edge; if `s == P`, also remove node `t` and all its edges. Then BFS from `P` over the remaining edges ignoring direction; drop unreached nodes and their edges. Reject the result (`would_drop_protected`) if the anchor or any absent node is gone, or (`no_asserted_left`) if no asserted edge remains.

- [ ] **Step 4: Run** → 6 passed. **Step 5: Commit** `feat: edge removal with patient-edge cascade and orphan cleanup`.

---

### Task 12: Independent generalization-order checker

**Files:**
- Create: `src/semgen/order.py`, `tests/test_order.py`

**Interfaces:**
- Consumes: `Motif`, `Interval.contains` (Task 1); `Hierarchy.is_descendant_or_self` (Task 3); `RelationHierarchy.leq` (Task 2); `GenContext` (Task 6). **Must not import anything from `semgen.operators` except `GenContext`, and must not read `ChangeRecord`s.**
- Produces: `OrderResult(ok: bool, reason: str|None=None, where: str|None=None)`; `check_order(specific: Motif, general: Motif, ctx) -> OrderResult`. Reasons: `extra_node`, `type_changed`, `role_changed`, `polarity_changed`, `concept_not_broader`, `context_code_changed`, `absent_not_narrower`, `value_not_contained`, `value_added`, `attr_not_contained`, `attr_added`, `extra_edge`, `relation_not_broader`, `provenance_changed`, `window_not_contained`, `window_added`.

- [ ] **Step 1: Write the failing tests** (Check 4 of the methodology, on the fake hierarchy)

```python
from semgen.order import check_order
from semgen.model import Interval, Edge
from tests.conftest import *
def test_identity_both_ways(ctx, fake_m1):
    assert check_order(fake_m1, fake_m1, ctx).ok
def bad(ctx, s, g, reason): r = check_order(s, g, ctx); assert not r.ok and r.reason == reason
def test_sibling_drug(ctx, fake_m1):
    bad(ctx, fake_m1, fake_m1.replace_node(fake_m1.node("n2").model_copy(update={"code": DAUNO})), "concept_not_broader")
def test_narrowed_or_moved_lvef(ctx, fake_m1):
    wide = fake_m1.replace_node(fake_m1.node("n3").model_copy(update={"value": Interval(lo=0, hi=40, hi_closed=False, unit="%")}))
    bad(ctx, wide, wide.replace_node(wide.node("n3").model_copy(update={"value": Interval(lo=38, hi=39, unit="%")})), "value_not_contained")
    bad(ctx, fake_m1, fake_m1.replace_node(fake_m1.node("n3").model_copy(update={"value": Interval(lo=40, hi=50, hi_closed=False, unit="%")})), "value_not_contained")
def test_reversed_edge(ctx, fake_m1):
    base = fake_m1.without(set(), {("n2", "n3")})
    flipped = fake_m1.edge("n2", "n3").model_copy(update={"s": "n3", "t": "n2"})
    bad(ctx, fake_m1, base.model_copy(update={"edges": base.edges + (flipped,)}), "extra_edge")
def test_context_promoted_to_asserted(ctx, fake_m1):
    bad(ctx, fake_m1, fake_m1.replace_edge(fake_m1.edge("n2", "n4").model_copy(update={"prov": "asserted"})), "provenance_changed")
def test_absent_lifted(ctx, fake_m2):
    bad(ctx, fake_m2, fake_m2.replace_node(fake_m2.node("n2").model_copy(update={"code": DM})), "absent_not_narrower")
def test_value_added_fails_and_removed_passes(ctx, fake_m1):
    no_val = fake_m1.replace_node(fake_m1.node("n3").model_copy(update={"value": None}))
    assert check_order(fake_m1, no_val, ctx).ok
    bad(ctx, no_val, fake_m1, "value_added")
def test_every_single_operator_move_verifies(ctx, fake_m1, fake_m2):
    from semgen.operators import ALL_OPERATORS
    for m in (fake_m1, fake_m2):
        for op in ALL_OPERATORS:
            for mv in op(m, ctx).moves:
                r = check_order(m, mv.child, ctx); assert r.ok, (mv.change, r)
```

Plus a Hypothesis test `test_random_chains_stay_ordered`: draw a chain of up to 5 moves from `fake_m1` (each step picks an index into the concatenated moves of `ALL_OPERATORS`; stop when none) and assert `check_order(fake_m1, end, ctx).ok` and, for every consecutive pair, `check_order(prev, next, ctx).ok`.

- [ ] **Step 2: Run** `uv run pytest tests/test_order.py -v` → FAIL (import error).

- [ ] **Step 3: Implement `check_order`** in the order of D9: node-id subset (`extra_node`) → per kept node (type, role, polarity, then code rule by polarity and role, then value, then attrs) → per general edge (`specific.edge(s,t)` exists else `extra_edge`; `relations.leq(spec.rel, gen.rel)`; equal `prov`; window). First failure returns `OrderResult(False, reason, where)` with `where` = node id or `"s->t"`. Context nodes (`role == "context"`) compare codes by equality.

- [ ] **Step 4: Run** → 9 passed (including the Hypothesis test).

- [ ] **Step 5: Commit** `feat: independent identity-map generalization-order checker`.

---

### Task 13: Neighbor generation

**Files:**
- Create: `src/semgen/lattice.py` (first part), `tests/test_neighbors.py`

**Interfaces:**
- Consumes: `ALL_OPERATORS`, base (Tasks 6–11); `check_order` (Task 12); `motif_hash` (Task 5).
- Produces:
  - `PolicyViolation(Exception)`, `GeneralizationOrderError(Exception)`.
  - `guard(parent: Motif, child: Motif, change: ChangeRecord, ctx) -> None`: raises `PolicyViolation` if patient or anchor node missing; any absent node or edge touching it differs from the parent; any kept context edge differs from the parent; a `concept_lift` change is rejected unless `ctx.floors.check_lift(change.before, change.after).ok` is True and `ctx.hierarchy.is_active(change.after)` (Amended by Stage 1).
  - `Neighbor(child: Motif, child_hash: str, changes: tuple[ChangeRecord, ...])` — `changes[0]` is the first operator (fixed order) that produced this child; the rest are alternatives.
  - `neighbors(motif, ctx) -> tuple[list[Neighbor], list[Blocked]]`.

- [ ] **Step 1: Write the failing tests**

```python
from semgen.lattice import neighbors, guard, PolicyViolation, GeneralizationOrderError
import semgen.lattice as L, pytest
from semgen.canonical import motif_hash
def test_unique_children_and_parent_excluded(ctx, fake_m1):
    ns, _ = neighbors(fake_m1, ctx)
    hs = [n.child_hash for n in ns]; assert len(hs) == len(set(hs)) and motif_hash(fake_m1) not in hs
def test_same_child_from_two_operators_keeps_both(ctx, fake_m1, monkeypatch):
    from semgen.operators.base import OperatorResult, Move, ChangeRecord
    child = fake_m1.replace_node(fake_m1.node("n3").model_copy(update={"value": None}))
    def op(name): return lambda m, c: OperatorResult([Move(child, ChangeRecord(name, "n3", "value", None, None, {}))], [])
    monkeypatch.setattr(L, "ALL_OPERATORS", [op("first"), op("second")])
    (n,), _ = neighbors(fake_m1, ctx)
    assert [c.op for c in n.changes] == ["first", "second"]
def test_order_failure_stops_loudly(ctx, fake_m1, monkeypatch):
    monkeypatch.setattr(L, "check_order", lambda s, g, c: L.OrderResult(False, "forced", "n1"))
    with pytest.raises(GeneralizationOrderError, match="forced"): neighbors(fake_m1, ctx)
def test_guard_rejects_touching_absent(ctx, fake_m2):
    child = fake_m2.without({"n2"}, {("P", "n2")})
    with pytest.raises(PolicyViolation): guard(fake_m2, child, None, ctx)
def test_blocked_collected(ctx, fake_m1):
    _, blocked = neighbors(fake_m1, ctx)
    assert {("concept_lift", "n3", "carries_value")} <= {(b.op, b.target, b.reason) for b in blocked}
```

(`lattice.py` must read `ALL_OPERATORS` and `check_order` as module attributes at call time, so the two monkeypatches above take effect.)

- [ ] **Step 2: Run** → FAIL (import error).

- [ ] **Step 3: Implement.** For each operator in `ALL_OPERATORS` order: collect `blocked`; for each move compute `child_hash`; skip if equal to the parent hash; run `guard`; run `check_order(parent, child, ctx)` and raise `GeneralizationOrderError(f"{reason} at {where}: {change}")` on failure; merge by `child_hash` preserving first-seen order. `lattice.py` imports `check_order` as a module-level name (so the monkeypatch works).

- [ ] **Step 4: Run** → 5 passed. **Step 5: Commit** `feat: neighbors with policy guard, order proof and dedup`.

---

### Task 14: BFS lattice enumeration and deduplication

**Files:**
- Modify: `src/semgen/lattice.py` (add enumeration)
- Create: `tests/test_lattice.py`

**Interfaces:**
- Consumes: `neighbors`, `Neighbor`, `check_order`, `motif_hash`.
- Produces:
  - `Candidate(hash: str, depth: int, motif: Motif)`.
  - `LatticeEdge(parent: str, child: str, changes: tuple[ChangeRecord, ...])`.
  - `Lattice(root: str, candidates: dict[str, Candidate], edges: list[LatticeEdge], blocked: list[tuple[str, Blocked]])` (blocked keyed by the candidate hash it came from).
  - `enumerate_lattice(root: Motif, ctx, max_depth: int|None=None) -> Lattice` (default `ctx.config.max_depth`).

- [ ] **Step 1: Write the failing tests**

```python
from semgen.lattice import enumerate_lattice
from semgen.order import check_order
def test_depth_zero_is_root_only(ctx, fake_m1):
    lat = enumerate_lattice(fake_m1, ctx, 0); assert list(lat.candidates) == [lat.root] and lat.edges == []
def test_depth1_matches_neighbors(ctx, fake_m1):
    from semgen.lattice import neighbors
    lat = enumerate_lattice(fake_m1, ctx, 1); assert len(lat.candidates) == 1 + len(neighbors(fake_m1, ctx)[0])
def test_no_duplicates_and_min_depth(ctx, fake_m1):
    lat = enumerate_lattice(fake_m1, ctx, 3)
    for e in lat.edges: assert lat.candidates[e.child].depth <= lat.candidates[e.parent].depth + 1
    assert len({(e.parent, e.child) for e in lat.edges}) == len(lat.edges)
def test_root_to_every_candidate_is_ordered(ctx, fake_m1, fake_m2):
    for m in (fake_m1, fake_m2):
        lat = enumerate_lattice(m, ctx, 3)
        for c in lat.candidates.values(): assert check_order(m, c.motif, ctx).ok
def test_m2_absent_constraint_never_changes(ctx, fake_m2):
    lat = enumerate_lattice(fake_m2, ctx, 4)
    for c in lat.candidates.values(): assert c.motif.node("n2") == fake_m2.node("n2") and c.motif.edge("P", "n2") == fake_m2.edge("P", "n2")
    assert not any(ch.target in ("n2", "P->n2") for e in lat.edges for ch in e.changes)
def test_deterministic(ctx, fake_m1):
    a, b = enumerate_lattice(fake_m1, ctx, 3), enumerate_lattice(fake_m1, ctx, 3)
    assert list(a.candidates) == list(b.candidates) and a.edges == b.edges
```

- [ ] **Step 2: Run** → FAIL (`ImportError: enumerate_lattice`).

- [ ] **Step 3: Implement.** Level-by-level BFS: `frontier` = list of hashes at depth d (insertion order). For each, call `neighbors`; new hashes get `depth d+1` and join the next frontier; every `(parent, child)` pair becomes one `LatticeEdge` (skip if already recorded). Expand only nodes with `depth < max_depth`. After BFS, assert `check_order(root, c.motif, ctx).ok` for every candidate (raise `GeneralizationOrderError` otherwise).

- [ ] **Step 4: Run** → 6 passed. **Step 5: Commit** `feat: deterministic BFS lattice with dedup and root proof`.

---

### Task 15: Candidate and lattice-edge exports

**Files:**
- Create: `src/semgen/export.py`, `src/semgen/__main__.py`, `tests/test_export.py`

**Interfaces:**
- Consumes: `Lattice` (Task 14), `canonical_json` (Task 5), `config_sha256` (Task 2), `Hierarchy.release/edition` (Task 3).
- Produces:
  - `run_header(ctx, config_path, max_depth) -> dict` with keys exactly: `snomed_release`, `snomed_edition`, `config_sha256`, `config_status`, `lvef_convention`, `temporal_semantics` (`"certain"`), `absent_semantics` (`"closed-world: no recorded fact that is the concept or any descendant"`), `max_depth`, `semgen_version`, plus the Stage 1 floor-provenance fields (from `ctx.floors.provenance` and `config.floor_source`): `floor_source`, `phecodex_commit`, `phecodex_sha256` (a dict of the 3 files), `icd10_map_refset`, `icd10_map_release`, `phecode_level`, `ccsr_check: "unavailable"` and `source_licences: {"phecodex": "unconfirmed"}` (Amended by Stage 1).
  - `write_lattice(lat: Lattice, motif_id: str, out_dir: Path, header: dict) -> dict[str, Path]` writing `out_dir/<motif_id>/run_header.json`, `candidates.jsonl` (`hash, depth, motif` = parsed canonical JSON), `edges.jsonl` (`parent, child, changes`), `blocked.jsonl` (`from, op, target, reason, detail`). Lines sorted by `(depth, hash)` / `(parent, child)` / `(from, op, target, reason)`.
  - CLI: `python -m semgen run --motifs PATH --config PATH [--rf2 DIR] [--phecodex DIR] [--depth N] --out DIR` → loads, verifies sources and builds the floor policy, enumerates each motif, writes files, prints one summary line per motif: `M1 depth=4 candidates=N edges=E blocked=B`.

- [ ] **Step 1: Write the failing tests**

```python
from semgen.export import write_lattice, run_header
from semgen.lattice import enumerate_lattice
import json
def test_files_and_header(tmp_path, ctx, fake_m1):
    lat = enumerate_lattice(fake_m1, ctx, 2)
    paths = write_lattice(lat, "M1", tmp_path, run_header(ctx, "config/generalization.yaml", 2))
    hdr = json.loads(paths["run_header"].read_text())
    assert hdr["temporal_semantics"] == "certain" and hdr["config_status"].startswith("DRAFT") and len(hdr["config_sha256"]) == 64
    rows = [json.loads(l) for l in paths["candidates"].read_text().splitlines()]
    assert len(rows) == len(lat.candidates) and rows[0]["depth"] == 0
    edge = json.loads(paths["edges"].read_text().splitlines()[0]); assert {"parent", "child", "changes"} <= set(edge)
def test_byte_identical_reruns(tmp_path, ctx, fake_m1):
    h = run_header(ctx, "config/generalization.yaml", 2)
    a = write_lattice(enumerate_lattice(fake_m1, ctx, 2), "M1", tmp_path / "a", h)
    b = write_lattice(enumerate_lattice(fake_m1, ctx, 2), "M1", tmp_path / "b", h)
    assert all(a[k].read_bytes() == b[k].read_bytes() for k in a)
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (no timestamps in files). **Step 4: Run** → 2 passed; then `uv run python -m semgen run --motifs data/motifs/synthetic_motifs.json --config config/generalization.yaml --depth 2 --out runs/dev` prints four summary lines. **Step 5: Commit** `feat: JSONL lattice export with run header and CLI`.

---

### Task 16: Synthetic patient containment tests

**Files:**
- Create: `tests/support/__init__.py`, `tests/support/matcher.py`, `tests/support/patients.py`, `tests/test_containment.py`

**Interfaces:**
- Consumes: `Motif`, `Hierarchy`, `RelationHierarchy` only. **Nothing from `semgen.order` or `semgen.operators`.**
- Produces (test-only):
  - `matches(pattern: Motif, patient: Motif, h: Hierarchy, rel: RelationHierarchy) -> bool`. Patient = a `Motif` with point values, no absent nodes. One-to-one backtracking over present pattern nodes (patient node → patient node); node test: same type, `h.is_descendant_or_self(fact.code, pat.code)` (context: equal code), pattern value/attrs contain the fact's point; every pattern edge `(s,t)` needs a patient edge between the images with `rel.leq(fact_rel, pat_rel)`, equal prov, pattern window contains the fact's window; each absent pattern node X: no patient node with `is_descendant_or_self(code, X)` (closed world).
  - `m1_patients() -> dict[str, Motif]` and `m2_patients() -> dict[str, Motif]` built by small edits of the root motif.

- [ ] **Step 1: Write the failing tests**

```python
from tests.support.matcher import matches
from tests.support.patients import m1_patients, m2_patients
from semgen.lattice import enumerate_lattice
M1_GOLD = {"exact", "extra_condition"}           # written BEFORE running anything
def test_m1_root_gold(ctx, fake_m1):
    got = {pid for pid, p in m1_patients(fake_m1).items() if matches(fake_m1, p, ctx.hierarchy, ctx.config.relations)}
    assert got == M1_GOLD
def test_matcher_is_one_to_one(ctx, fake_m1):
    from semgen.model import Node, Edge
    two = fake_m1.model_copy(update={
        "nodes": fake_m1.nodes + (Node(id="n9", type="Substance", role="exposure", code=ANTHRA),),
        "edges": fake_m1.edges + (Edge(s="P", t="n9", rel="administered_drug", prov="asserted"),)})
    two = two.replace_node(two.node("n2").model_copy(update={"code": ANTHRA, "attrs": {}}))
    assert not matches(two, m1_patients(fake_m1)["exact"], ctx.hierarchy, ctx.config.relations)   # one DOX fact, two pattern drugs
def test_closed_world_descendant_of_absent(ctx, fake_m2):
    ps = m2_patients(fake_m2); assert not matches(fake_m2, ps["has_t1dm"], ctx.hierarchy, ctx.config.relations)
def test_monotone_along_every_lattice_edge(ctx, fake_m1, fake_m2):
    for root, pats in ((fake_m1, m1_patients(fake_m1)), (fake_m2, m2_patients(fake_m2))):
        lat = enumerate_lattice(root, ctx, 3)
        sets = {h: {pid for pid, p in pats.items() if matches(c.motif, p, ctx.hierarchy, ctx.config.relations)} for h, c in lat.candidates.items()}
        bad = [(e.parent, e.child) for e in lat.edges if not sets[e.parent] <= sets[e.child]]
        assert bad == []
def test_self_match(ctx, fake_m1, fake_m2):
    for root in (fake_m1, fake_m2):
        patient = root.without({n.id for n in root.nodes if n.polarity == "absent"}, {e.key for e in root.edges if e.t in {n.id for n in root.nodes if n.polarity == "absent"}})
        for c in enumerate_lattice(root, ctx, 3).candidates.values():
            assert matches(c.motif, patient, ctx.hierarchy, ctx.config.relations)
def test_matcher_not_imported_by_production():
    import pathlib; assert not any("tests.support" in p.read_text() for p in pathlib.Path("src").rglob("*.py"))
```

M1 patients (exact list, ids are dict keys): `exact` (= root as a patient), `daunorubicin` (n2 → DAUNO), `lvef_45` (n3 value 45), `outcome_day_60` (window 60), `no_context_edges` (n4, n5 and their edges removed), `extra_condition` (adds an RA node + edge), `no_drug` (n2 and its edges removed), `age_72` (age 72). The root requires the context edges and the exact values, so only `exact` and `extra_condition` match it. M2 patients: `exact`, `has_t1dm` (adds T1DM node + edge), `egfr_70`, `day_400`.

- [ ] **Step 2: Run** `uv run pytest tests/test_containment.py -v` → FAIL (import error).

- [ ] **Step 3: Implement `matcher.py` and `patients.py`.** Backtracking over pattern nodes sorted by id with `P` first; candidate images are patient nodes not yet used.

- [ ] **Step 4: Run** → 6 passed.

- [ ] **Step 5: Commit** `test: reference matcher and containment/monotonicity tests on synthetic patients`.

---

### Task 17: Full integration tests and final verification

**Files:**
- Create: `tests/test_integration_real.py`, `README.md` (how to run; what is DRAFT; what is blocked and why)

**Interfaces:**
- Consumes: everything; `real_ctx`, `real_motifs` fixtures (marked `snomed`).

- [ ] **Step 1: Write the failing tests** (all `@pytest.mark.snomed`)

```python
import pytest
from semgen.lattice import enumerate_lattice
from semgen.order import check_order
pytestmark = pytest.mark.snomed
def lat_of(real_motifs, real_ctx, mid, d): return enumerate_lattice(next(m for m in real_motifs if m.motif_id == mid), real_ctx, d)
def changes(lat): return [c for e in lat.edges for c in e.changes]
@pytest.mark.parametrize("depth", [2, 4])
def test_all_motifs_zero_proof_failures(real_motifs, real_ctx, depth):
    for m in real_motifs:
        lat = enumerate_lattice(m, real_ctx, depth)
        assert all(check_order(m, c.motif, real_ctx).ok for c in lat.candidates.values())
def test_m1_check2(real_motifs, real_ctx):
    ch = changes(lat_of(real_motifs, real_ctx, "M1", 1))
    lifts = {(c.target, c.after) for c in ch if c.op == "concept_lift"}
    assert lifts == set()                                                    # Stage 1: both parents (126926005, 188361007) are outside_floor
    lat = lat_of(real_motifs, real_ctx, "M1", 1)
    assert {(b.target, b.detail["parent"]) for _, b in lat.blocked if b.op == "concept_lift" and b.reason == "outside_floor" and b.target == "n1"} == {("n1", "126926005"), ("n1", "188361007")}
    assert ("P->n2", "exposed_to_drug") in {(c.target, c.after) for c in ch if c.op == "relation_relaxation"}
def test_m2_check3(real_motifs, real_ctx):
    lat = lat_of(real_motifs, real_ctx, "M2", 4)
    assert {c.after for c in changes(lat) if c.op == "concept_lift" and c.target == "n1"} == set()   # Stage 1: DM blocked by 105401000119101
    assert not any(c.target in ("n2", "P->n2") for c in changes(lat))
def test_m3_anchor_lift(real_motifs, real_ctx):
    assert ("n1", "254637007") in {(c.target, c.after) for c in changes(lat_of(real_motifs, real_ctx, "M3", 1)) if c.op == "concept_lift"}
def test_m4_alt_and_ra_blocked(real_motifs, real_ctx):
    lat = lat_of(real_motifs, real_ctx, "M4", 1)
    assert ("n3", (3, 5)) in {(c.target, (c.after["lo"], c.after["hi"])) for c in changes(lat) if c.op == "range_coarsening"}
    assert ("concept_lift", "n1", "outside_floor") in {(b.op, b.target, b.reason) for _, b in lat.blocked}
def test_drug_lifts_blocked_without_floor(real_motifs, real_ctx):
    lat = lat_of(real_motifs, real_ctx, "M1", 1)
    assert not any(c.op == "concept_lift" and c.target == "n2" for c in changes(lat))
```

- [ ] **Step 2: Run** `uv run pytest tests/test_integration_real.py -v` → if any test fails, it is a real bug: fix it in the owning task's module with a new unit test first.

- [ ] **Step 3: Write `README.md`**: install (`uv sync`), run tests (`uv run pytest`, `-m "not snomed"` for fast runs), run CLI, the DRAFT warning, and a table of what is blocked and why (Amended by Stage 1, per S7/S8: Disorder lifts blocked `outside_floor` when a parent has a descendant outside the node's PhecodeX anchors, `unmapped` when the concept has no usable ICD-10→PhecodeX anchor, `inactive_parent`; Substance/Observable/Procedure/Finding lifts `no_floor`; `carries_value`; `concept_dependent_attr`; LVEF/ALT values block lifts, `cumulative_dose` concept-dependent, absent nodes untouched).

- [ ] **Step 4: Final verification**

Run: `uv run pytest -v` → all tests pass (the full run including `snomed` tests).
Run: `uv run python -m semgen run --motifs data/motifs/synthetic_motifs.json --config config/generalization.yaml --depth 4 --out runs/final` twice into two folders and `diff -r` them → no differences.
Expected: four summary lines, zero `GeneralizationOrderError`, zero `PolicyViolation`.

- [ ] **Step 5: Commit** `test: real-SNOMED integration checks; docs: README`.

---

## Self-review notes (done while writing)

- **Spec coverage:** six operators (Tasks 6–11), legality (operators + guard, Task 13), order proof (12), lattice (13–14), outputs with release and config hash (15), Checks 1–8 of the methodology: Check 1 → Task 3 real tests; Check 2 → Tasks 6–11 + 17; Check 3 → Tasks 14, 17; Check 4 → Task 12; Check 5 → Task 16; Check 6 → CLI summary line (Task 15); Check 7 (clinical spreadsheet) → out of scope for the POC (D1); Check 8 → the whole suite plus the determinism tests.
- **Dropped from the methodology on purpose:** derived-state substitution (out of scope there too), FalkorDB/rustworkx/Plotly (D1, D8), "co-occurs" (D6), the `[30,40)` LVEF rung and closed `≤49` bins (D5).
- **Type consistency:** `OperatorResult`, `Move`, `Blocked`, `ChangeRecord` (Task 6) are used unchanged in Tasks 7–15; `Neighbor.changes` and `LatticeEdge.changes` are both `tuple[ChangeRecord, ...]`.
