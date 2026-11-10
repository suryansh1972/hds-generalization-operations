# Recursive SNOMED Ancestor Generalization — Implementation Plan

> **Status:** implemented. This plan amends `stage1-phecodex-floors.md` and `semantic-generalization-implementation.md`; see the README and the methodology amendment of 4 Nov 2026 for the final behaviour.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Red → green → refactor on every task.

**Goal:** Let concept lift climb the applicable SNOMED CT ancestor hierarchy to an explicit boundary, without PhecodeX as a prerequisite, and report honestly how far the search went.

**Architecture:** One-step lift, the policy guard, the order checker and BFS keep their roles. A required selector picks a floor policy: new DRAFT `snomed_boundary` (default) or existing `phecodex`. A per-node climb runs alongside the bounded lattice through the same acceptance gate, and every run reports how it terminated.

**Tech Stack:** unchanged. Python 3.12, uv, Pydantic v2, PyYAML, Polars, pytest, Hypothesis. No new dependencies.

**Spec:** this document's "Approved design" section. It amends `docs/plans/stage1-phecodex-floors.md` and `docs/plans/semantic-generalization-implementation.md` where they conflict; both stay in place as history.

---

## Approved design

### What the code inspection established

| Fact | Evidence |
|---|---|
| Lift already reads parents, one candidate per direct parent | `concept_lift.py:37` |
| BFS already recurses | With the floor stubbed out, M3 n1 lift targets go 1→2→4→8 over depths 1–4 |
| RF2 filter is correct | Active + inferred + IS-A; 628,834 rows; no inactive endpoints; root is the only parentless concept |
| Order checker direction is correct | `order.py:33`, reversed for absent at `order.py:40` |
| The only child traversal in `src/` is the PhecodeX floor | `floors.py:85` |
| There is no production phenotype matcher | Only test-only `tests/support/matcher.py` |
| Root cause 1: floor strictness | 1 of 22 direct-parent decisions across M1–M4 passes |
| Root cause 2: silent truncation | M1 has 615 candidates at depth 4, 2,534 at depth 8, nothing reported |
| PhecodeX is a run prerequisite, not a traversal prerequisite | `context.py:17`, `config.py:62`, `export.py:30-36`, `floor_report.py:22` |
| `cumulative_dose` is NOT protected from removal today | `attribute_removal.py` has no dependency check; `test_op_attribute_removal.py:8` pins removal; the methodology has no such rule |

### Decisions

| # | Decision |
|---|---|
| R1 | **Default floor.** `floor_policy.mode: snomed_boundary`. `phecodex` stays selectable. The key is required: a missing or unknown mode is a `ConfigError`. There is no unrestricted mode and no fallback. If the selected policy cannot be built or evaluated, the run fails or the lift is blocked. |
| R2 | **Descendant ceiling.** A candidate parent passes when `descendant_count(parent) <= max_descendants`. Initial value **2500**, configurable, DRAFT. `descendant_count` counts distinct, active, strict (self excluded), transitive descendants, so a concept reached by two IS-A paths counts once. It is a computational broadness heuristic, not a clinical rule. |
| R3 | **Excluded roots.** `excluded_ancestor_roots` lists `{fsn, reason}` entries. Each FSN must resolve to exactly one active concept, or construction raises `FsnError` (fail closed). A parent that is descendant-or-self of a resolved root is blocked. Initial entry: `Substance categorized by structure (substance)` with reason `Structural chemical grouping is not an accepted drug generalization boundary`. Mechanism and disposition groupers such as Antifolate are **not** excluded; this limitation is documented for future review. |
| R4 | **Semantic tag.** A parent must have the same FSN semantic tag as the child. A concept with no parseable tag fails closed (`no_semantic_tag`). This is in the approved design: real data has 7,519 disorder→finding edges and no finding→disorder edges. |
| R5 | **State-based lift eligibility.** A value or concept-dependent attribute present on the current motif blocks lifting. There is no historical blocking. A later lift must pass its own guard and order proof. |
| R6 | **Removal protection (rule change).** `attribute_removal` no longer removes a concept-dependent attribute, including unflagged attributes (which count as dependent). It logs `Blocked("attribute_removal", node, "concept_dependent_attr", {"attr": name})`. `guard` independently rejects the same removal with rule `dependent_attr_removed`. `value` removal stays permitted, so LVEF is the valid post-removal example. Range coarsening of `cumulative_dose` and whole-node removal through edge removal are unchanged. Consequence: doxorubicin with a dose can never be concept-lifted. |
| R7 | **Search limits.** `max_depth` (default 4) still bounds combined operations. New `max_candidates` (default 50000) bounds the combined lattice. There is no separate hierarchy-depth setting. |
| R8 | **Per-node climb.** From the root motif only, each liftable node follows accepted lifts on that node until none remain. Bounded by the finite acyclic ancestor set, so `max_depth` and `max_candidates` do not apply. Climb moves go through the same guard and order proof, and produce real candidates (`origin: "axis"`), edges and ChangeRecords. A node blocked at the root stays `policy_restricted`; the climb does not remove values to get past that. Post-removal lifts come from the bounded lattice. |
| R9 | **Termination.** Motif `status`: `exhausted`, `depth_limited` or `candidate_limited`. Only `exhausted` sets `complete: true`. Per-node status: `reached_floor`, `reached_hierarchy_top` or `policy_restricted`. |
| R10 | **PhecodeX keeps its behaviour.** Under `mode: phecodex` every existing decision is unchanged. The `floor_source` block stays where it is, since the fetch command also uses it, and is required only when the mode is `phecodex`. No similarity engine is built. The sole exception is the logged reason for a parentless node carrying a value or dependent attribute, which now reads `carries_value` or `concept_dependent_attr`; the lift stays blocked. |

### Amendments to earlier records

- Stage 1's "no SCTID in config" rule is kept: R3 uses an FSN resolved against the pinned release.
- S10's strict M2 ruling now applies to `mode: phecodex` only.
- D3 gains R5 and R6.

## Global Constraints

- Python >=3.12, no new dependencies, operators stay pure, output stays deterministic (byte-identical for the same inputs).
- **Do not commit.** The controller snapshots each task outside the repository. Commits happen only after the user approves.
- Every config value stays DRAFT. Never describe `snomed_boundary`, 2500 or any exclusion as clinically validated.
- No BioPathNet integration, no real patient data, no phenotype similarity engine. M1–M4 stay synthetic.
- Preserve polarity, absent-node handling, protected edges, provenance, temporal constraints, closed-world semantics, the identity-map proof, dedup and ChangeRecord behaviour.
- Concept lift must never call a descendant API. Descendant reads belong to floor policies.
- Run tests with `.venv/bin/python -m pytest`.
- A blocked lift's `detail` always includes `"parent"` when a parent was evaluated.

## Review Focus

1. **Stale RF2 cache.** A pickled `Hierarchy` from older code must not load without the new fields. Pinned in Task 1 (`test_old_cache_is_rebuilt`).
2. **Polyhierarchy double count.** A diamond must count its shared descendant once, and the shared ancestor's count must not reuse a memo from another traversal order. Pinned in Task 1 (`test_descendant_count_diamond_counts_once`).
3. **Removal loophole through an unflagged attribute.** An attribute with no YAML flag counts as dependent and must not be removable. Pinned in Task 3 (`test_unflagged_attr_not_removed`).
4. **Axis candidates and the root proof.** Candidates added by the climb must pass the final root proof like any other. Pinned in Task 7 (`test_axis_candidates_pass_root_proof`).
5. **`depth_limited` when frontier motifs have no moves.** A cap that lands exactly on a dead end is `exhausted`, not truncated. Pinned in Task 6 (`test_cap_on_dead_end_is_exhausted`).

---

### Task 1: Direction-aware hierarchy API

**Justification:** `children`, strict `descendants` and a safe descendant count do not exist. `descendants_or_self` memoises one frozenset per descendant, too heavy near *Disease*.

**Files:**
- Modify: `src/semgen/snomed.py`
- Modify: `tests/fixtures/rf2/sct2_Relationship_Snapshot_INT_20990101.txt`
- Test: `tests/test_snomed.py`

**Interfaces:**
- Produces on `Hierarchy`: `children(c) -> frozenset[str]`; `descendants(c) -> frozenset[str]` (strict, activity not filtered, same as `descendants_or_self(c) - {c}`); `descendant_count(c) -> int` (distinct active strict descendants; plain traversal; memoises integers only, in `_count_memo`); `semantic_tag(c) -> str | None`; attribute `characteristic_type = "inferred"`.
- Existing `parents`, `ancestors`, `ancestors_or_self`, `descendants_or_self`, `is_descendant_or_self` keep their signatures.

- [ ] **Step 1: Add fixture row and failing tests.** Add one active inferred non-IS-A row `C → D` (typeId `363698007`) to the RF2 fixture. Tests:

```python
def test_non_isa_row_ignored(tmp_path):
    assert load_rf2(FIX, cache_dir=tmp_path).parents("C") == {"B"}

def test_parents_and_children_are_opposite_directions(fake_h):
    assert MAL_THORAX in fake_h.parents(BRCA) and BRCA in fake_h.children(MAL_THORAX)
    assert fake_h.children(BRCA) == frozenset() and BRCA not in fake_h.parents(MAL_THORAX)

def test_descendants_is_strict(fake_h):
    assert DM not in fake_h.descendants(DM) and fake_h.descendants(DM) == {T1DM, T2DM}

def test_descendant_count_diamond_counts_once():
    h = Hierarchy.from_maps({"L": {"A", "B"}, "A": {"T"}, "B": {"T"}, "T": set()}, {}, {"L", "A", "B", "T"})
    assert h.descendant_count("T") == 3 and h.descendant_count("A") == 1

def test_descendant_count_ignores_inactive():
    h = Hierarchy.from_maps({"X": {"T"}, "Y": {"T"}, "T": set()}, {}, {"X", "T"})
    assert h.descendant_count("T") == 1

def test_semantic_tag():
    h = Hierarchy.from_maps({}, {"A": "Foo (bar baz)", "B": "No tag"}, {"A", "B"})
    assert h.semantic_tag("A") == "bar baz" and h.semantic_tag("B") is None and h.semantic_tag("zzz") is None

def test_old_cache_is_rebuilt(tmp_path, monkeypatch):
    load_rf2(FIX, cache_dir=tmp_path)
    monkeypatch.setattr("semgen.snomed.CACHE_VERSION", "test-other")
    load_rf2(FIX, cache_dir=tmp_path)
    assert len(list(tmp_path.glob("*.pkl"))) == 2

def test_characteristic_type_recorded(tmp_path):
    assert load_rf2(FIX, cache_dir=tmp_path).characteristic_type == "inferred"
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_snomed.py -v` → the new-API tests FAIL with `AttributeError`; `test_non_isa_row_ignored` passes because the filter is already right (note this in the report).
- [ ] **Step 3: Implement.** Add a module constant `CACHE_VERSION = "2"` included in the cache signature list. Reset `_count_memo` in `__getstate__` and on cache load. Build the child index through one private helper shared by `children` and `descendants_or_self`. Tag regex: `\(([^()]+)\)$` on the FSN of an active concept. Replace the stale class docstring at `snomed.py:31` with one naming both directions and stating that lift uses upward reads only.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_snomed.py -v` → PASS, then the full suite → PASS.

### Task 2: Regression suite for traversal, branching and dedup

**Justification:** the behaviour is already correct, so nothing pins it. These tests must exist before later tasks change the search.

**Files:**
- Create: `tests/support/hierarchy_graph.py`, `tests/test_recursive_lift.py`

**Interfaces:**
- Produces in `tests/support/hierarchy_graph.py`: `graph_hierarchy() -> Hierarchy`; `AllowExcept(blocked: set[str])`, a floor policy stub whose `check_lift(child, parent)` fails with reason `outside_floor` and detail `{"parent": parent}` when `parent in blocked`, and whose `anchors` returns `frozenset()` and `provenance` returns `{"mode": "test"}`; `one_disorder_motif(code) -> Motif`.
- Graph, all FSNs tagged `(disorder)`:
  - `SPEC` parents `P1`, `P2`
  - `P1` parent `G`; `P2` parents `G`, `BLOCKED`
  - `BLOCKED` parent `ABOVE_BLOCKED`
  - `G` parent `C1`; `C1`→`C2`→`C3`→`C4`→`C5`→`ROOT` (`138875005`)
  - `ABOVE_BLOCKED` parent `ROOT`; `KID` parent `SPEC`
  - `INACTIVE` is a parent of `SPEC` and not active

- [ ] **Step 1: Write the tests** in `tests/test_recursive_lift.py`, each using `GenContext(graph_hierarchy(), load_config(CFG), AllowExcept(...))`:

| Test | Assertion |
|---|---|
| `test_first_step_is_direct_parents_never_children` | Depth-1 lift targets are exactly `{P1, P2}`: not `KID` (child), not `INACTIVE`, not `G` (grandparent) |
| `test_each_transition_is_one_direct_parent_step` | Every `concept_lift` change has `after in h.parents(before)` |
| `test_bfs_lifts_parents_of_generalized_concepts` | With `max_depth=3`, `G` and `C1` are reached |
| `test_all_branches_explored` | Both `P1→G` and `P2→G` edges exist |
| `test_converging_paths_dedupe_and_keep_histories` | One candidate for code `G`, at least two incoming edges, each with its own ChangeRecord `before` |
| `test_blocked_parent_not_bypassed` | `AllowExcept({"BLOCKED"})`: `ABOVE_BLOCKED` is never reached |
| `test_inactive_parent_blocked_not_lifted` | Reason `inactive_parent` is logged and `INACTIVE` is never a target |
| `test_lift_module_has_no_descendant_reads` | The source text of `operators/concept_lift.py` and `lattice.py` contains no `descendant` substring |
| `test_order_checker_rejects_child_direction` | `check_order` with the code moved to `KID` fails with `concept_not_broader` |

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_recursive_lift.py -v` → PASS (characterisation tests of correct code).
- [ ] **Step 3: Prove the tests can fail.** In a temporary copy under the scratch directory given in the dispatch, change `Hierarchy.parents` to return children and rerun; record which tests fail in the report. Do not change the worktree for this step.
- [ ] **Step 4: Run** the full suite → PASS.

### Task 3: Protect dependent attributes from removal

**Justification:** R6. Without it, a prohibited removal would enable a lift.

**Files:**
- Modify: `src/semgen/operators/attribute_removal.py`, `src/semgen/lattice.py` (`guard`), `src/semgen/operators/base.py` (docstring)
- Test: `tests/test_op_attribute_removal.py`, `tests/test_neighbors.py`, `tests/test_recursive_lift.py`

**Interfaces:**
- Produces: `attribute_removal` skips dependent attributes and returns `Blocked("attribute_removal", node.id, "concept_dependent_attr", {"attr": name})`. `guard` raises `PolicyViolation` with rule `dependent_attr_removed` when a node kept in the child has lost a dependent attribute.

- [ ] **Step 1: Write failing tests.** Update `test_m1_removals` to expect `{("n1", "attrs.age_at_dx"), ("n3", "value")}`. Add:

```python
def test_dose_removal_blocked_and_logged(ctx, fake_m1):
    res = attribute_removal(fake_m1, ctx)
    assert all(m.change.field != "attrs.cumulative_dose" for m in res.moves)
    b = next(x for x in res.blocked if x.target == "n2")
    assert (b.op, b.reason, b.detail) == ("attribute_removal", "concept_dependent_attr", {"attr": "cumulative_dose"})

def test_unflagged_attr_not_removed(ctx, fake_m1):
    n = fake_m1.node("n1")
    m = fake_m1.replace_node(n.model_copy(update={"attrs": {"mystery": Interval.point(1, "x")}}))
    res = attribute_removal(m, ctx)
    assert all(x.change.field != "attrs.mystery" for x in res.moves)
    assert any(b.detail == {"attr": "mystery"} for b in res.blocked)

def test_guard_rejects_dependent_attr_removal(ctx, fake_m1):          # tests/test_neighbors.py
    n = fake_m1.node("n2")
    child = fake_m1.replace_node(n.model_copy(update={"attrs": {}}))
    with pytest.raises(PolicyViolation, match="dependent_attr_removed"):
        guard(fake_m1, child, None, ctx)
```

In `tests/test_recursive_lift.py`, using a graph-based motif with one Substance node carrying `cumulative_dose` and one Observable node carrying a value, and `AllowExcept(set())`:

| Test | Assertion |
|---|---|
| `test_value_bearing_observable_not_lifted` | Root `concept_lift` logs `carries_value` for it |
| `test_dependent_attr_substance_not_lifted` | Root `concept_lift` logs `concept_dependent_attr` for it |
| `test_prohibited_removal_never_enables_lift` | In a depth-4 lattice no lift ever targets the dose-bearing node |
| `test_lift_after_permitted_value_removal` | Depth-2 lattice has a path `value` removal → `concept_lift` for the observable, and the lifted candidate has `value is None` |
| `test_post_removal_transitions_are_recorded_and_proven` | Each edge on that path has a ChangeRecord and `check_order(parent, child, ctx).ok` |

- [ ] **Step 2: Run** the three test files → the removal, guard and `test_prohibited_removal_never_enables_lift` tests FAIL for the expected reason (dose removal still happens). `test_lift_after_permitted_value_removal` already passes; note it.
- [ ] **Step 3: Implement.** Use `ctx.config.attr_is_concept_dependent`. In `guard`, compare attribute names for nodes in `parent.node_ids & child.node_ids`, independent of the operator's ChangeRecord. Whole-node removal must stay legal. Do not change `range_coarsening`.
- [ ] **Step 4: Run** the full suite. Fix tests that relied on dose removal, and list each one and why in the report. A `test_containment` non-vacuity failure means another strict edge must be asserted, not that the rule should be relaxed.

### Task 4: `SnomedBoundaryPolicy`

**Justification:** R2–R4; runs need a boundary with no PhecodeX.

**Files:**
- Create: `src/semgen/snomed_floor.py`, `tests/test_snomed_floor.py`
- Modify: `src/semgen/config.py`, `config/generalization.yaml`, `tests/test_config.py`

**Interfaces:**
- Consumes: Task 1's `descendant_count`, `semantic_tag`, `characteristic_type`.
- Produces in `config.py`:
  - `ExcludedRoot(fsn: str, reason: str)`
  - `SnomedBoundaryConfig(max_descendants: int, characteristic_type: Literal["inferred"], excluded_ancestor_roots: tuple[ExcludedRoot, ...])`, with `max_descendants >= 1`
  - `FloorPolicyConfig(mode: Literal["snomed_boundary", "phecodex"], snomed_boundary: SnomedBoundaryConfig | None)`
  - `GenConfig.floor_policy: FloorPolicyConfig` (required), `GenConfig.floor_source: FloorSourceConfig | None`, `GenConfig.max_candidates: int`
  - `ConfigError` when `floor_policy` is missing, the mode is unknown, the selected mode's block is missing, `characteristic_type` is not `inferred`, or `max_candidates < 1`
- Produces in `snomed_floor.py`: `SnomedBoundaryPolicy(hierarchy: Hierarchy, cfg: SnomedBoundaryConfig)`, satisfying the `FloorPolicy` protocol. `anchors(c)` returns `frozenset()`.
- Reasons, checked in this order, all with `"parent"` in `detail`:
  1. `inactive_parent`
  2. `no_semantic_tag` (`child_tag`, `parent_tag`)
  3. `semantic_tag_changed` (`child_tag`, `parent_tag`)
  4. `excluded_ancestor_root` (`excluded_root`, `excluded_fsn`, `reason`)
  5. `above_descendant_ceiling` (`descendant_count`, `ceiling`)
- An accepted decision has `detail == {"descendant_count": n, "ceiling": c, "semantic_tag": t}`.
- `provenance` returns `{"mode": "snomed_boundary", "status": "DRAFT — computational heuristic, not clinically validated", "max_descendants": ..., "characteristic_type": ..., "semantic_tag_rule": "parent must keep the child's FSN semantic tag", "excluded_ancestor_roots": [{"concept_id", "fsn", "reason"}, ...], "snomed_release": ..., "snomed_edition": ...}`.

YAML, added above `floor_source`, with `max_candidates: 50000` next to `max_depth`:

```yaml
# Floor policy: which rule bounds concept lift. Required; there is no unrestricted mode.
# snomed_boundary is a DRAFT computational policy, not a clinically validated boundary.
floor_policy:
  mode: snomed_boundary          # snomed_boundary | phecodex
  snomed_boundary:
    max_descendants: 2500        # DRAFT broadness heuristic, not a clinical rule
    characteristic_type: inferred
    excluded_ancestor_roots:
      - fsn: "Substance categorized by structure (substance)"
        reason: "Structural chemical grouping is not an accepted drug generalization boundary"
```

- [ ] **Step 1: Write failing tests** in `tests/test_snomed_floor.py`, with a small synthetic hierarchy that carries FSNs:

| Test | Assertion |
|---|---|
| `test_1296_descendants_accepted` | Star parent with exactly 1,296 active children passes at ceiling 2500, `detail["descendant_count"] == 1296` |
| `test_exact_ceiling_accepted` | Count equal to the ceiling passes |
| `test_over_ceiling_blocked` | Count 2,501 gives `above_descendant_ceiling` |
| `test_polyhierarchy_counted_once` | A descendant reachable by two paths: count matches distinct ids and the ceiling decision uses it |
| `test_structural_root_and_subtree_blocked` | Lifts into the root and into a concept below it give `excluded_ancestor_root` with the resolved id and FSN |
| `test_unrelated_substance_branch_allowed` | A mechanism grouper outside the subtree passes |
| `test_multi_parent_substance_keeps_allowed_branch` | Substance with one structural and one mechanism parent: only the mechanism lift passes |
| `test_unresolved_root_fails_closed` | Unknown FSN raises `FsnError` at construction |
| `test_ambiguous_root_fails_closed` | An FSN shared by two active concepts raises `FsnError` |
| `test_retired_root_fails_closed` | An FSN on an inactive concept raises `FsnError` |
| `test_semantic_tag_change_blocked` | Disorder→finding gives `semantic_tag_changed` |
| `test_missing_tag_fails_closed` | No tag gives `no_semantic_tag`, never `ok` |
| `test_inactive_parent_blocked` | `inactive_parent` |
| `test_provenance_is_draft_and_complete` | Status starts with `DRAFT`; threshold, release, edition, characteristic type and the resolved root are present |
| `test_blocked_set_is_upward_closed` (Hypothesis) | On random DAGs with an empty exclusion list and a single tag: if a parent is blocked by the ceiling, each of its ancestors is too |

In `tests/test_config.py`: `test_default_mode_is_snomed_boundary`, `test_phecodex_mode_loads`, and parametrised rejections for a missing key, an unknown mode, a missing block, `characteristic_type: stated`, `max_descendants: 0` and `max_candidates: 0`. Add `test_floor_source_optional_under_snomed_boundary`, and `test_floor_source_required_under_phecodex`.

- [ ] **Step 2: Run** the two test files → FAIL (import error, then config errors).
- [ ] **Step 3: Implement.** No wiring into `build_context` yet: `build_context` still constructs the PhecodeX policy, so existing tests keep passing. `sources.main` must raise `ConfigError`-style failure output if `floor_source` is missing rather than crash with `AttributeError`.
- [ ] **Step 4: Run** the full suite → PASS.

### Task 5: Floor selection, run header and CLI wiring

**Justification:** R1, R10; removes the four hard-wired PhecodeX points.

**Files:**
- Modify: `src/semgen/context.py`, `src/semgen/export.py`, `src/semgen/__main__.py`, `src/semgen/floor_report.py`, `src/semgen/floors.py`, `src/semgen/operators/base.py`
- Test: `tests/test_export.py`, `tests/test_floor_report.py`, `tests/test_integration_real.py`, new `tests/test_floor_selection.py`

**Interfaces:**
- Consumes: Task 4's config and policy.
- Produces: `build_context(config_path, rf2_dir=None, phecodex_dir=None, floor_mode: str | None = None) -> GenContext`. `floor_mode` overrides `floor_policy.mode`; `load_config`'s validation rules apply to the resulting mode.
- CLI: `--floor-policy {snomed_boundary,phecodex}` on `semgen run` and `semgen.floor_report`. `--phecodex` combined with an effective mode of `snomed_boundary` exits 1 with a clear error.
- `PhecodeFloorPolicy.provenance` gains `"mode": "phecodex"`, keeping its existing keys.
- `run_header(ctx, config_path, max_depth)` always includes `"floor_policy": ctx.floors.provenance` and `"max_candidates"`. `snomed_release`, `snomed_edition`, `config_status` stay. The legacy keys `floor_source`, `phecode_level`, `icd10_map_refset`, `icd10_map_release`, `phecodex_commit`, `phecodex_sha256`, `ccsr_check`, `source_licences` appear only under `mode: phecodex`.
- Update the `FloorPolicy` protocol docstring and `base.py`'s list of blocked reasons.

- [ ] **Step 1: Write failing tests** in `tests/test_floor_selection.py`:

| Test | Assertion |
|---|---|
| `test_default_context_uses_snomed_boundary` | RF2 fixture; `build_context` policy is `SnomedBoundaryPolicy` with no PhecodeX directory present |
| `test_snomed_mode_does_not_touch_phecodex` | `verify_phecodex` and `load_icd10_map` monkeypatched to raise; build still succeeds |
| `test_phecodex_mode_selectable` | `floor_mode="phecodex"` gives `PhecodeFloorPolicy` (marked `phecodex`/`snomed`) |
| `test_phecodex_missing_files_fail_not_fallback` | `floor_mode="phecodex"` with an empty dir raises `SourceError` |
| `test_header_records_snomed_policy_and_draft` | `config_status` starts `DRAFT`; `floor_policy` has mode, DRAFT status, threshold, characteristic type, release, resolved exclusion id and FSN; no `phecodex_commit` key |
| `test_header_phecodex_keeps_legacy_keys` | Existing exact-key set plus `floor_policy`, `max_candidates` |
| `test_cli_phecodex_flag_conflict_exit_1` | Usage conflict message, no traceback |

The RF2 fixture lacks the excluded FSN, so these tests use a temporary config with `excluded_ancestor_roots: []` or a fixture concept. Do not add the real concept to the fixture.

In `tests/test_integration_real.py`, `real_ctx` and CLI end-to-end tests stay PhecodeX-based: pass `--floor-policy phecodex` in existing CLI tests that assert PhecodeX results. `real_ctx` keeps its directly injected `real_floors`.

- [ ] **Step 2: Run** the listed tests → FAIL for the expected reasons.
- [ ] **Step 3: Implement.** `build_context` dispatches on the effective mode and builds only that policy. `floor_report` catches `FsnError`. Its `_anchors` decision set stays unchanged, so `snomed_boundary` rows have empty anchors.
- [ ] **Step 4: Run** the full suite → PASS. Then run `python -m semgen run` on M1–M4 in both modes to a scratch `--out` and record the printed lines.

### Task 6: Termination reporting

**Justification:** R7, R9; truncation is currently silent.

**Files:**
- Modify: `src/semgen/lattice.py`, `src/semgen/export.py`, `src/semgen/__main__.py`
- Test: `tests/test_lattice.py`, `tests/test_export.py`

**Interfaces:**
- Produces: `Lattice` gains `status: str = "unknown"`, `unexpanded: int = 0`. `enumerate_lattice(root, ctx, max_depth=None, max_candidates=None)`; `max_candidates` defaults to `ctx.config.max_candidates` and is validated like `max_depth`.
- Candidate budget: once the table holds `max_candidates` candidates, a neighbor that would add a new candidate is dropped with its edge, and the search stops after the current frontier motif. Edges between existing candidates from that motif are kept. Order stays deterministic.
- Status rules: budget hit → `candidate_limited`. Otherwise, if any remaining frontier motif has at least one neighbor → `depth_limited`. Otherwise → `exhausted`. `unexpanded` is the frontier size when limited, else 0. The check stops at the first motif with a neighbor.
- Produces: `write_lattice` writes `termination.json` (paths key `termination`): `{"status", "complete", "max_depth", "max_candidates", "unexpanded_frontier", "candidates"}`. `complete` is `status == "exhausted"`.
- CLI line: `M1 depth=4 candidates=... edges=... blocked=... status=depth_limited`.

- [ ] **Step 1: Write failing tests.**

| Test | Assertion |
|---|---|
| `test_depth_cap_with_moves_is_depth_limited` | Long chain, small depth: `depth_limited`, `unexpanded >= 1` |
| `test_cap_on_dead_end_is_exhausted` | One-step graph, `max_depth` equal to its true height: `exhausted`, `unexpanded == 0` |
| `test_depth_zero_with_moves_is_depth_limited` | `max_depth=0` |
| `test_full_exploration_is_exhausted` | Large depth on a small motif: `exhausted` |
| `test_candidate_budget_is_reported` | `max_candidates=3`: `candidate_limited`, `len(candidates) <= 3` |
| `test_budget_run_is_deterministic` | Two runs are equal |
| `test_termination_json_written` | File content, and `complete` is `False` when limited |
| `test_chain_longer_than_depth_is_not_claimed_complete` | Graph chain above `max_depth`: `complete` is `False` |

Update `test_cli_end_to_end`'s regex to include ` status=\w+`.

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the full suite → PASS.

### Task 7: Per-node climb

**Justification:** R8. No depth setting can reach deep ancestors, because the combined lattice multiplies across nodes.

**Files:**
- Modify: `src/semgen/lattice.py`, `src/semgen/operators/concept_lift.py`, `src/semgen/export.py`
- Test: `tests/test_recursive_lift.py`, `tests/test_export.py`

**Interfaces:**
- Produces: `is_liftable(node) -> bool` in `concept_lift.py`, the existing skip condition inverted and reused by the operator.
- Produces: a private `_accept(parent, move, ctx) -> None` in `lattice.py` running `guard` then `check_order` and raising as today. `neighbors` and the climb both use it.
- Produces: `Candidate.origin: str = "lattice"`. `NodeAxis(node: str, status: str, reached: tuple[str, ...], stopped_by: tuple[str, ...])` with sorted codes and sorted distinct reasons. `Lattice.axes: dict[str, NodeAxis]`, empty by default.
- `enumerate_lattice` runs the climb after BFS and before the root proof, for each liftable node of `root` in id order. Levels go breadth-first. A new candidate gets `depth = parent depth + 1`, `origin="axis"`. An existing candidate keeps its depth and origin. Edges use the shared `seen_pairs`. Blocked entries from a motif the BFS already expanded are not added twice.
- Reason groups:
  - Boundary: `outside_floor`, `above_descendant_ceiling`, `semantic_tag_changed`, `excluded_ancestor_root`, `inactive_parent`
  - Top: `no_parent`
  - Restriction: everything else
- Node status: any Restriction reason → `policy_restricted`; else any Top reason → `reached_hierarchy_top`; else `reached_floor`.
- The climb ignores `max_depth` and `max_candidates`. It does not change `Lattice.status`, because that describes the combined lattice.
- `candidates.jsonl` rows gain `origin`. `termination.json` gains `"axes": {node: {"status", "reached", "stopped_by"}}`.

- [ ] **Step 1: Write failing tests** in `tests/test_recursive_lift.py`:

| Test | Assertion |
|---|---|
| `test_climb_reaches_past_max_depth` | `max_depth=2`: `C5` is a candidate, `origin == "axis"`, `status == "depth_limited"` still |
| `test_climb_is_one_step_edges` | Every step on the chain is a one-parent ChangeRecord |
| `test_climb_explores_all_branches` | Both `P1` and `P2` routes reach `G`; `axes["n1"].reached` contains both |
| `test_climb_does_not_bypass_blocked` | `AllowExcept({"BLOCKED"})`: `ABOVE_BLOCKED` is not reached and `outside_floor` is in `stopped_by` |
| `test_climb_stops_at_floor_status` | Block `C3`: status `reached_floor`, `C4` unreached |
| `test_climb_to_top_status` | Nothing blocked: `reached_hierarchy_top` |
| `test_value_node_is_policy_restricted` | Observable with a value: `policy_restricted`, `reached == ()` |
| `test_climb_skips_absent_and_context_nodes` | Those ids are not in `axes` |
| `test_axis_candidates_pass_root_proof` | Force `check_order` failure on an axis-only candidate: raises `GeneralizationOrderError` |
| `test_climb_guard_failure_raises` | A monkeypatched failing guard raises rather than dropping the move |
| `test_climb_deterministic` | Two runs produce equal candidates, edges, blocked and axes |

In `tests/test_export.py`, `test_axes_in_termination_json` and `test_origin_in_candidates`.

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** Extract `_accept` first without behaviour change, then add the climb. **Step 4: Run** the full suite → PASS.

### Task 8: Real-data integration in both modes

**Justification:** the Stage 4 end-to-end proof on the pinned release.

**Files:**
- Modify: `tests/test_integration_real.py`
- Test: same

**Interfaces:**
- Consumes: everything above. A session fixture `real_boundary_ctx(real_h)` builds `GenContext(real_h, load_config(_CONFIG_PATH), SnomedBoundaryPolicy(real_h, cfg.floor_policy.snomed_boundary))`.

- [ ] **Step 1: Write tests** marked `snomed` only, so they must not need PhecodeX:

| Test | Assertion |
|---|---|
| `test_ra_lifts_to_arthritis` | M4 climb from `69896004` reaches `3723001` |
| `test_ra_arthritis_within_ceiling_counts_distinct` | `real_h.descendant_count("3723001")` is 1,295 strict (1,296 with self) |
| `test_t2dm_climbs_multiple_levels` | M2 n1 reaches `73211009` and `126877002`, more than one level |
| `test_m3_climb_exceeds_depth_cap` | With `max_depth=4`, some M3 n1 candidate has `origin == "axis"` and `depth > 4`, and the motif `status != "exhausted"` |
| `test_no_finding_targets_for_disorders` | No M1–M4 disorder node reaches a `(finding)` concept |
| `test_structural_targets_rejected` | M3 n3 and M4 n2 never reach `18858006` or `36326009`; `excluded_ancestor_root` is logged |
| `test_mechanism_target_still_allowed` | M4 n2 can reach `372612001` Antifolate (documented limitation) |
| `test_dose_substance_stays_restricted` | M1 n2 is `policy_restricted` and doxorubicin is never lifted in the depth-4 lattice |
| `test_lvef_lift_after_value_removal` | M1 lattice at depth 2 has a lift of n3 only on a motif whose n3 value is gone |
| `test_every_edge_proven` | Over M1–M4 at depth 2, `check_order(parent, child).ok` on all edges, climb included |
| `test_containment_on_synthetic_patients` | Same matcher monotonicity check as `test_real_containment_depth4`, under this policy |
| `test_no_silent_completeness_claim` | Any motif with `status != "exhausted"` has `complete: False` in its termination data |

Existing PhecodeX tests stay and must keep passing. Update only expectations changed by R6, and list them.

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_integration_real.py -v` → PASS or expose real failures. A failure here is a defect to fix in the owning code, or a wrong expectation to correct with evidence in the report.
- [ ] **Step 3: Run** the full suite → PASS.

### Task 9: Documentation

**Justification:** README, methodology, config comments and old plans describe superseded behaviour.

**Files:**
- Modify: `README.md`, `docs/semantic-generalization-methodology.md`, `docs/plans/stage1-phecodex-floors.md`, `docs/plans/semantic-generalization-implementation.md`, `src/semgen/operators/concept_lift.py` (module docstring), `src/semgen/floors.py` (module docstring), `config/generalization.yaml` (header comment at line 3)

**Interfaces:** none.

- [ ] **Step 1: README.** Cover:
  - floor modes and `--floor-policy`
  - the `snomed_boundary` rule, stated as DRAFT and not clinically validated
  - new blocked reasons, including the `attribute_removal` one
  - `termination.json`, `origin`, statuses, and why `complete` may be false
  - the corrected M1–M4 table
  - run-header fields
  - the limitation that mechanism and disposition groupers such as Antifolate are not excluded
  - the limitation that a value or dose node's climb is not explored from the root
  - the rule that doxorubicin with a dose cannot be lifted
  - PhecodeX as an optional capability, for future cross-disease phenotype comparison, and not a patient-similarity engine
- [ ] **Step 2: Methodology.** Add a dated amendment section. Do not rewrite history. It records R1–R10, the distinction between generalization (ancestors) and phenotype matching (descendants), and termination semantics.
- [ ] **Step 3: Old plans.** Add one-line pointers: the amendment header in the main plan, and supersession notes on S10 and the no-`at_floor`/reasons list in Stage 1. D3 gains R5/R6.
- [ ] **Step 4: Verify.** `grep -rn "clinically validated\|clinically approved" README.md docs/semantic-generalization-methodology.md` shows only negated uses. Run the full suite → PASS.

---

## Task status

| Task | Status |
|---|---|
| 1 Hierarchy API | Approved |
| 2 Regression suite | Approved |
| 3 Removal protection | Approved |
| 4 SnomedBoundaryPolicy | Approved |
| 5 Selection and header | Approved |
| 6 Termination | Approved |
| 7 Per-node climb | Approved |
| 8 Real-data integration | Approved |
| 9 Documentation | Approved |

## Acceptance

- All nine tasks APPROVED by a fresh independent reviewer.
- Full suite passes, including `snomed` and `phecodex` tests, with no unexplained skips.
- Each of the user's 15 required tests and 13 Stage 4 checks maps to a named test above.
- No commit exists until the user approves.
