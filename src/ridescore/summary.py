"""What a run produced, in enough detail to judge it.

A successful run and a good run are different things. This exists so that a
change to a scoring rule can be judged before a database exists: the spread of
each score, how much of the network had to be filled in, and what moved since
last time.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ridescore import build, config, run_record
from ridescore.models.ridescore_v1.scores import SCORE_COLUMNS

# Attributes we fill in when the source does not say. A high share here is not
# an error, but it is the first thing to look at when a score looks too kind.
IMPUTED = {
    "speed_limit": lambda segments: segments["speed_limit_raw"].isna()
    | (segments["speed_limit_raw"] <= config.SPEED_LIMIT_MIN_VALID),
    "num_lanes": lambda segments: segments["num_lanes_raw"].isna()
    | (segments["num_lanes_raw"] <= config.NUM_LANES_MIN_VALID),
    "pavement_condition": lambda segments: segments["pavement_condition"].isna(),
    "road_width": lambda segments: segments["road_width"].isna(),
}


@dataclass
class Summary:
    counts: dict[str, int]
    length_km: float
    spread: pd.DataFrame
    imputed: dict[str, tuple[int, float]]
    lts: pd.Series
    derived: dict


def summarise(out: Path) -> Summary:
    segments = build.read(out, "road_segment")
    scores = build.read(out, "ridescore_v1_scores")
    crashes = build.read(out, "crashes")

    spread = scores[list(SCORE_COLUMNS)].describe().T[["count", "mean", "std", "min", "50%", "max"]]

    imputed = {}
    for name, test in IMPUTED.items():
        flagged = int(test(segments).sum())
        imputed[name] = (flagged, 100.0 * flagged / max(len(segments), 1))

    return Summary(
        counts={
            "road_segment": len(segments),
            "crashes": len(crashes),
            "ridescore_v1_scores": len(scores),
        },
        length_km=float(segments["len"].sum()) / 1000.0,
        spread=spread.round(1),
        imputed=imputed,
        lts=scores["lts_level"].value_counts().sort_index(),
        derived=run_record.read(out).get("derived", {}),
    )


def compare(current: Path, previous: Path) -> pd.DataFrame:
    """What moved between two runs, per score column.

    Joined on `segment_id`, so a street that appeared or disappeared is counted
    separately rather than shifting every mean underneath the comparison.
    """
    now = build.read(current, "ridescore_v1_scores").set_index("segment_id")
    before = build.read(previous, "ridescore_v1_scores").set_index("segment_id")
    shared = now.index.intersection(before.index)

    rows = []
    for column in SCORE_COLUMNS:
        delta = now.loc[shared, column].astype(float) - before.loc[shared, column].astype(float)
        rows.append(
            {
                "column": column,
                "changed": int((delta != 0).sum()),
                "mean_delta": round(float(delta.mean()), 3),
                "max_increase": round(float(delta.max()), 1),
                "max_decrease": round(float(delta.min()), 1),
            }
        )

    frame = pd.DataFrame(rows).set_index("column")
    frame.attrs["added"] = len(now.index.difference(before.index))
    frame.attrs["removed"] = len(before.index.difference(now.index))
    return frame
