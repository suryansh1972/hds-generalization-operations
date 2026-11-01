import subprocess
import sys

import pytest

from semgen.floor_report import COLUMNS, floor_report, rows_to_tsv
from tests.conftest import BRCA, CKD, DM, DOX, MAL_THORAX, NEO_BREAST, T1DM, T2DM


def _row(m, node, code, fsn, decision, parent=None, anchors="", bd=None, bf=None, anchor=None, pf=None):
    return {"motif_id": m, "node": node, "code": code, "fsn": fsn, "decision": decision, "parent": parent,
            "parent_fsn": pf, "anchors": anchors, "blocking_descendant": bd, "blocking_fsn": bf, "anchor": anchor}


def test_fake_rows(ctx, fake_m1, fake_m2):
    h = ctx.hierarchy
    rows = floor_report([fake_m2, fake_m1], ctx)
    # Sorted by parent id: 126926005 (NEO_BREAST) before 188361007 (MAL_THORAX). FSNs are None in the fake tables.
    # M1 n1: BRCA anchors CA_105+CA_130. NEO_BREAST (D24 -> BI_999) is outside CA_105 at once.
    # MAL_THORAX (C50.9) and its descendant BRCA are inside both anchors -> allowed.
    # M1 n2 DOX has cumulative_dose (concept-dependent, checked before type) -> concept_dependent_attr. n3 carries a value (and is no Disorder) -> carries_value.
    # M2 n1: T2DM anchor EM_202.2; parent DM (E14 -> EM_202) is not inside EM_202.2; the smallest failing
    #   descendant id is T1DM 46635009 (E10 -> EM_202, EM_202.1). n4 CKD: parent DISEASE; smallest id that is
    #   outside GU_582.2 is NEO_BREAST 126926005 (D24 -> BI_999). n3 Substance no_floor. n5 value. n2 absent: skipped.
    assert rows == [
        _row("M1", "n1", BRCA, h.fsn(BRCA), "outside_floor", NEO_BREAST, "CA_105;CA_130",
             NEO_BREAST, h.fsn(NEO_BREAST), "CA_105", h.fsn(NEO_BREAST)),
        _row("M1", "n1", BRCA, h.fsn(BRCA), "allowed", MAL_THORAX, "CA_105;CA_130", pf=h.fsn(MAL_THORAX)),
        _row("M1", "n2", DOX, h.fsn(DOX), "concept_dependent_attr"),
        _row("M1", "n3", "250908004", h.fsn("250908004"), "carries_value"),
        _row("M2", "n1", T2DM, h.fsn(T2DM), "outside_floor", DM, "EM_202.2", T1DM, h.fsn(T1DM), "EM_202.2", h.fsn(DM)),
        _row("M2", "n3", "372567009", h.fsn("372567009"), "no_floor"),
        _row("M2", "n4", CKD, h.fsn(CKD), "outside_floor", "64572001", "GU_582.2",
             NEO_BREAST, h.fsn(NEO_BREAST), "GU_582.2", h.fsn("64572001")),
        _row("M2", "n5", "80274001", h.fsn("80274001"), "carries_value"),
    ]


def test_deterministic(ctx, fake_m1, fake_m2):
    a, b = floor_report([fake_m1, fake_m2], ctx), floor_report([fake_m1, fake_m2], ctx)
    assert a == b and rows_to_tsv(a) == rows_to_tsv(b)


def test_tsv_header_and_shape(ctx, fake_m1, fake_m2):
    rows = floor_report([fake_m1, fake_m2], ctx)
    lines = rows_to_tsv(rows).splitlines()
    assert lines[0] == ("motif_id\tnode\tcode\tfsn\tdecision\tparent\tparent_fsn\tanchors\t"
                        "blocking_descendant\tblocking_fsn\tanchor")
    assert len(lines) == len(rows) + 1 and all(l.count("\t") == len(COLUMNS) - 1 for l in lines)


@pytest.mark.snomed
@pytest.mark.phecodex
def test_real_m3_allowed_and_m1_blocked(real_motifs, real_ctx):
    rows = floor_report(real_motifs, real_ctx)
    assert any(r["motif_id"] == "M3" and r["node"] == "n1" and r["decision"] == "allowed"
               and r["parent"] == "254637007" for r in rows)
    m1 = [r for r in rows if r["motif_id"] == "M1" and r["node"] == "n1"]
    assert [(r["decision"], r["parent"], r["blocking_descendant"]) for r in m1] == [
        ("outside_floor", "126926005", "1080431000119107"),
        ("outside_floor", "188361007", "105041000119109")]


def test_cli_help():
    r = subprocess.run([sys.executable, "-m", "semgen.floor_report", "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "--motifs" in r.stdout
