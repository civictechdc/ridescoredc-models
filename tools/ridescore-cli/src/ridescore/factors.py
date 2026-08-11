"""Per-factor 0-100 columns — the pipeline's half of the tile-function contract.

**This is not a model.** Nothing here decides how safe a street is. Each
function normalises exactly one recorded attribute onto 0-100 and the pipeline
writes the result into its own column. The *scoring* — combining them — happens
per request in the `update_score` stored procedure in `schema/`, because the
weights come from the sliders the person looking at the map is moving:

    speed limit ─┐
    lanes       ─┤
    facility    ─┼─→ precomputed columns ─→ update_score(z,x,y,{i_*}) ─→ user_score
    function    ─┤        (here)              (schema/, per request)
    road width  ─┤
    pavement    ─┘

So this file is a **cross-boundary contract**. The column names and the 0-100
convention are depended on by `schema/sql/wip-update_score_v2.sql`, by Martin,
and by the frontend's slider UI. Renaming one is a coordinated change across
three repositories, not a refactor.

Ported from `notebooks/archive/data_processing.ipynb` cell 27, unchanged.
"""

# The column each factor writes. Keep in step with the SELECT in update_score.
COLUMNS = (
    "speedlimit_score",
    "num_lanes_score",
    "facility_score",
    "function_score",
    "road_width_score",
    "pavement_condition_score",
)

# Note this is a *different* facility table from the one in
# models/ridescore_v1/config.py: that one is a small bonus capped at 10, this
# one is a full 0-100 factor. Two tables, two consumers, deliberately.
FACILITY_TO_SCORE = {
    "protected_track": 100,
    "buffered_lane": 75,
    "painted_lane": 50,
    "none": 0,
}
FACILITY_TO_SCORE_DEFAULT = 0

NUM_LANES_TO_SCORE = {0: 100, 1: 100, 2: 75, 3: 50, 4: 25, 5: 25, 6: 0, 7: 0, 8: 0, 10: 0}
# DEFECT (fix after the port): a missing lane count scores 10 here -- i.e. as bad
# as an eight-lane road -- while the stress rules in models/lts/ treat the same
# missing value as config.DEFAULT_NUM_LANES (1), a quiet residential street.
NUM_LANES_TO_SCORE_DEFAULT = 10

FUNCTION_TO_SCORE = {
    "Local": 100,
    "Collector": 75,
    "Minor Arterial": 50,
    "Principal/Primary Arterial": 25,
    "Other Freeway and Expressway": 0,
    "Interstate": 0,
    "Other": 0,
}
FUNCTION_TO_SCORE_DEFAULT = 0

PAVEMENT_TO_SCORE = {"Excellent": 100, "Good": 75, "Fair": 50, "Poor": 25, "Very Poor": 0}
PAVEMENT_TO_SCORE_DEFAULT = 50

# DEFECT (fix after the port): unbounded. 100 - 2*speed goes negative above
# 50 mph; 100 - width goes negative on a wide road, and a *missing* width
# scores 100 -- the best possible.
SPEED_LIMIT_SCORE_SLOPE = 2
ROAD_WIDTH_SCORE_INTERCEPT = 100
