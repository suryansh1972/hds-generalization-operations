import subprocess
import sys

import pytest

from semgen.floor_report import COLUMNS, floor_report, rows_to_tsv
from tests.conftest import (
    BIGUANIDE,
    BRCA,
    CKD,
    DISEASE,
    DM,
    DOX,
    GFR,
    LVEF,
    MAL_THORAX,
    MET,
    NEO_BREAST,
    T2DM,
    one_node_motif,
)


def _row(m, node, code, fsn, decision, parent=None, pf=None):
    return {"motif_id": m, "node": node, "code": code, "fsn": fsn, "decision": decision, "parent": parent,
            "parent_fsn": pf}


def test_fake_rows(ctx, fake_m1, fake_m2):
    """Rewritten (Task 1): was the PhecodeX rows (M1 n1 -> NEO_BREAST outside_floor, M2 n1 -> DM and n4 -> DISEASE
    outside_floor, M2 n3 unmapped, plus anchor columns); now the SNOMED-only rows without anchor columns."""
    h = ctx.hierarchy
    rows = floor_report([fake_m2, fake_m1], ctx)
    # Sorted by parent id: 126926005 (NEO_BREAST) before 188361007 (MAL_THORAX).
    # SNOMED-only: every parent below keeps the child's semantic tag, none is under the excluded structural
    # root, and the fake hierarchy is far below the descendant ceiling, so every reachable lift is allowed.
    # M1 n2 DOX has cumulative_dose (concept-dependent) -> concept_dependent_attr. n3/n5 carry a value. M2 n2 absent: skipped.
    assert rows == [
        _row("M1", "n1", BRCA, h.fsn(BRCA), "allowed", NEO_BREAST, h.fsn(NEO_BREAST)),
        _row("M1", "n1", BRCA, h.fsn(BRCA), "allowed", MAL_THORAX, h.fsn(MAL_THORAX)),
        _row("M1", "n2", DOX, h.fsn(DOX), "concept_dependent_attr"),
        _row("M1", "n3", LVEF, h.fsn(LVEF), "carries_value"),
        _row("M2", "n1", T2DM, h.fsn(T2DM), "allowed", DM, h.fsn(DM)),
        _row("M2", "n3", MET, h.fsn(MET), "allowed", BIGUANIDE, h.fsn(BIGUANIDE)),
        _row("M2", "n4", CKD, h.fsn(CKD), "allowed", DISEASE, h.fsn(DISEASE)),
        _row("M2", "n5", GFR, h.fsn(GFR), "carries_value"),
    ]


def test_deterministic(ctx, fake_m1, fake_m2):
    a, b = floor_report([fake_m1, fake_m2], ctx), floor_report([fake_m1, fake_m2], ctx)
    assert a == b and rows_to_tsv(a) == rows_to_tsv(b)


def test_tsv_header_and_shape(ctx, fake_m1, fake_m2):
    """Rewritten (Task 1): was the header with the four PhecodeX columns (anchors, blocking_descendant,
    blocking_fsn, anchor); now the SNOMED columns only (D13)."""
    rows = floor_report([fake_m1, fake_m2], ctx)
    lines = rows_to_tsv(rows).splitlines()
    assert lines[0] == "motif_id\tnode\tcode\tfsn\tdecision\tparent\tparent_fsn"
    assert len(lines) == len(rows) + 1 and all(l.count("\t") == len(COLUMNS) - 1 for l in lines)


@pytest.mark.snomed
def test_real_m3_allowed_and_m1_allowed(real_motifs, real_ctx):
    """Rewritten (Task 1): was M1 n1 outside_floor at both parents (PhecodeX blocking descendants); now both
    parents are allowed under snomed_boundary, matching the HEAD-generated golden real_lift/M1."""
    rows = floor_report(real_motifs, real_ctx)
    assert any(r["motif_id"] == "M3" and r["node"] == "n1" and r["decision"] == "allowed"
               and r["parent"] == "254637007" for r in rows)
    m1 = [r for r in rows if r["motif_id"] == "M1" and r["node"] == "n1"]
    assert [(r["decision"], r["parent"]) for r in m1] == [("allowed", "126926005"), ("allowed", "188361007")]


def test_cli_help():
    r = subprocess.run([sys.executable, "-m", "semgen.floor_report", "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "--motifs" in r.stdout


def test_rows_are_the_engine_decisions(ctx):
    """Rewritten (SNOMED-only lift): every row is the evaluator's own decision for that parent."""
    from tests.conftest import BRCA, DISEASE, MAL_THORAX, NEO_BREAST, RA, RA_OLD_PARENT
    rows = floor_report([one_node_motif(BRCA), one_node_motif(RA)], ctx)
    got = {(r["code"], r["parent"]): r["decision"] for r in rows}
    assert got == {(BRCA, MAL_THORAX): "allowed", (BRCA, NEO_BREAST): "allowed", (RA, DISEASE): "allowed",
                   (RA, RA_OLD_PARENT): "inactive_parent"}
    assert all(set(r) == set(COLUMNS) for r in rows)
