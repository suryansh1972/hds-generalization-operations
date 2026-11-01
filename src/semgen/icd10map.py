"""SNOMED CT -> ICD-10 extended map loader (usable targets only: TRUE / OTHERWISE TRUE with a target)."""
from __future__ import annotations

import re
from pathlib import Path

import polars as pl

MAP_GLOB = "der2_iisssccRefset_ExtendedMapSnapshot_*_*.txt"


class Icd10Map:
    """Usable ICD-10 targets per SNOMED concept."""

    def __init__(self, targets: dict[str, frozenset[str]], release: str, refset_id: str) -> None:
        self._targets = targets
        self.release = release
        self.refset_id = refset_id

    @classmethod
    def from_maps(
        cls, targets: dict[str, set[str]], release: str = "TEST", refset_id: str = "447562003"
    ) -> Icd10Map:
        return cls({c: frozenset(t) for c, t in targets.items()}, release, refset_id)

    def targets(self, c: str) -> frozenset[str]:
        return self._targets.get(c, frozenset())


def load_icd10_map(terminology_dir: str | Path, refset_id: str, rules: tuple[str, ...]) -> Icd10Map:
    map_dir = Path(terminology_dir).parent / "Refset" / "Map"
    hits = sorted(map_dir.glob(MAP_GLOB))
    if len(hits) != 1:
        raise FileNotFoundError(
            f"expected exactly one {MAP_GLOB} in {map_dir}, found {len(hits)}"
        )
    path = hits[0]
    m = re.search(r"_(\d{8})\.txt$", path.name)
    release = m.group(1) if m else "UNKNOWN"
    df = pl.read_csv(
        path,
        separator="\t",
        infer_schema=False,
        quote_char=None,
        columns=["active", "refsetId", "referencedComponentId", "mapRule", "mapTarget"],
    ).filter(
        (pl.col("active") == "1")
        & (pl.col("refsetId") == refset_id)
        & pl.col("mapRule").is_in(list(rules))
        & pl.col("mapTarget").is_not_null()
        & (pl.col("mapTarget") != "")
    )
    acc: dict[str, set[str]] = {}
    for c, t in zip(df["referencedComponentId"].to_list(), df["mapTarget"].to_list()):
        acc.setdefault(c, set()).add(t)
    return Icd10Map({c: frozenset(t) for c, t in acc.items()}, release, refset_id)
