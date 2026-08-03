"""Level of traffic stress, 1 (calm) to 4 (hostile).

A faithful port of the rules table in `notebooks/data_processing.ipynb`. Ported
as written, including the discrepancy noted in `config.LTS_NO_FACILITY_SPEED_2`:
the repository README documents the no-facility local-street rule as 25 mph, the
notebook implements 20.
"""

from ridescore import config


def lts_level(facility: str, speed: float, lanes: float, function: str = "") -> int:
    """Classify one segment.

    `speed` and `lanes` are the *filled-in* values, not the raw ones -- a missing
    lane count has already become `config.DEFAULT_NUM_LANES` and a missing speed
    limit `config.DEFAULT_SPEED_LIMIT` by the time this is called.
    """
    road_function = (function or "").lower()

    if facility == "protected_track":
        return 1

    if facility in {"buffered_lane", "painted_lane"}:
        if speed <= config.LTS_MARKED_LANE_SPEED_2 and lanes <= config.LTS_MARKED_LANE_LANES_2:
            return 2
        if speed <= config.LTS_MARKED_LANE_SPEED_3 and lanes <= config.LTS_MARKED_LANE_LANES_3:
            return 3
        return config.LTS_WORST

    if facility == "none":
        on_local = road_function in config.LTS_NO_FACILITY_FUNCTIONS
        few_lanes = lanes <= config.LTS_NO_FACILITY_LANES
        if speed <= config.LTS_NO_FACILITY_SPEED_2 and few_lanes and on_local:
            return 2
        if speed <= config.LTS_NO_FACILITY_SPEED_3 and few_lanes and on_local:
            return 3
        return config.LTS_WORST

    return config.LTS_WORST
