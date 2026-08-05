"""RideScore v1: seven component scores and the blend, each 0-100.

Every rule is a function of one value, so each can be tested on its own and read
without a dataframe in mind. `score()` applies them.

Several carry defects the port keeps deliberately; each is marked here and in
`config`, and fixing one is its own change because it moves published numbers.
"""

from __future__ import annotations

from collections.abc import Iterable

import geopandas as gpd
import pandas as pd

from ridescore import config
from ridescore.models.ridescore_v1 import lts
from ridescore.models.ridescore_v1.weights import Weights

# The columns this model produces, in the order they are written.
SCORE_COLUMNS = (
    "lts_level",
    "lts_score",
    "s_lts",
    "s_crash",
    "s_facility",
    "speedlimit_score",
    "num_lanes_score",
    "facility_score",
    "function_score",
    "road_width_score",
    "pavement_condition_score",
    "ridescore_v1",
)


def p95(values: Iterable) -> int:
    """The 95th percentile crash count, never below 1.

    Never below 1 because it is a divisor: a city with no crashes at all would
    otherwise divide by zero. Computed from each run's own data, so the crash
    score is relative to that run -- which is why `run.json` records it.
    """
    ordered = sorted(int(value) for value in values if pd.notnull(value))
    if not ordered:
        return 1
    index = round(0.95 * (len(ordered) - 1))
    return max(ordered[index], 1)


def crash_inv(count: float, p95_crashes: int) -> float:
    """Crashes, inverted: no crashes is 100, the 95th percentile or worse is 0."""
    share = float(count) / float(p95_crashes)
    return 100.0 * (1.0 - min(max(share, 0.0), 1.0))


def lts_to_score(level: float) -> int:
    return config.LTS_TO_SCORE.get(int(level), config.LTS_TO_SCORE_DEFAULT)


def facility_bonus(facility: str) -> int:
    """The small credit the blend gives for having any facility at all."""
    return config.FACILITY_BONUS.get(facility, 0)


def speedlimit_to_score(speed: float) -> float:
    """DEFECT (fix after the port): unbounded. Goes negative above 50 mph."""
    return config.SPEED_LIMIT_SCORE_INTERCEPT - (config.SPEED_LIMIT_SCORE_SLOPE * speed)


def num_lanes_to_score(lanes: float) -> int:
    """Scored on the *raw* lane count, not the filled-in one.

    DEFECT (fix after the port): a missing count scores 10 -- as bad as an
    eight-lane road -- while the stress rules treat the same missing value as a
    quiet residential street. See `config.NUM_LANES_TO_SCORE_DEFAULT`.
    """
    if lanes is None or pd.isna(lanes):
        return config.NUM_LANES_TO_SCORE_DEFAULT
    return config.NUM_LANES_TO_SCORE.get(int(lanes), config.NUM_LANES_TO_SCORE_DEFAULT)


def facility_to_score(facility: str) -> int:
    return config.FACILITY_TO_SCORE.get(facility, config.FACILITY_TO_SCORE_DEFAULT)


def function_to_score(road_function: str) -> int:
    return config.FUNCTION_TO_SCORE.get(road_function, config.FUNCTION_TO_SCORE_DEFAULT)


def road_width_to_score(width: float) -> float:
    """DEFECT (fix after the port): unbounded, and a *missing* width scores 100
    -- the best possible. See `config.ROAD_WIDTH_SCORE_INTERCEPT`."""
    return config.ROAD_WIDTH_SCORE_INTERCEPT - width


def pavement_condition_to_score(condition: str) -> int:
    return config.PAVEMENT_TO_SCORE.get(condition, config.PAVEMENT_TO_SCORE_DEFAULT)


def assign_lts(segments: gpd.GeoDataFrame) -> pd.Series:
    """Stress level per segment, from the filled-in speed and lane count."""
    return segments.apply(
        lambda row: lts.lts_level(
            row.bike_facility_type,
            int(row.speed_limit),
            int(row.num_lanes),
            row.function,
        ),
        axis=1,
    )


def score(segments: gpd.GeoDataFrame, weights: Weights, *, p95_crashes: int) -> pd.DataFrame:
    """Every score column for every segment, keyed the same way as the input."""
    scores = pd.DataFrame(index=segments.index)

    scores["lts_level"] = assign_lts(segments)
    scores["lts_score"] = scores["lts_level"].map(lts_to_score)

    # The blend's three inputs. `s_lts` is the same number as `lts_score`; the
    # notebook computed it twice and both names reached the database.
    scores["s_lts"] = scores["lts_score"]
    scores["s_crash"] = segments["crash_count_5yr"].map(
        lambda count: crash_inv(count, p95_crashes)
    )
    scores["s_facility"] = segments["bike_facility_type"].map(facility_bonus).fillna(0)

    scores["speedlimit_score"] = segments["speed_limit"].map(speedlimit_to_score)
    scores["num_lanes_score"] = segments["num_lanes_raw"].map(num_lanes_to_score)
    scores["facility_score"] = segments["bike_facility_type"].map(facility_to_score)
    scores["function_score"] = segments["function"].map(function_to_score)
    scores["road_width_score"] = segments["road_width"].map(road_width_to_score)
    scores["pavement_condition_score"] = segments["pavement_condition"].map(
        pavement_condition_to_score
    )

    scores["ridescore_v1"] = (
        weights.lts * scores["s_lts"]
        + weights.crash * scores["s_crash"]
        + weights.facility * scores["s_facility"]
    ).round(config.BLEND_DECIMALS)

    return scores[list(SCORE_COLUMNS)]
