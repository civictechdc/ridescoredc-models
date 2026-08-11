"""Parameters owned by ridescore_v1 — the published blend — and nothing else."""

LTS_TO_SCORE = {1: 100, 2: 75, 3: 40, 4: 10}
LTS_TO_SCORE_DEFAULT = 10

# A bonus capped at 10, so facility contributes at most 1 point of the final
# 100. Facility type already drives LTS, so this is a tie-breaker rather than a
# third opinion. Not to be confused with factors.FACILITY_TO_SCORE, which is a
# full 0-100 column for the tile function.
FACILITY_BONUS = {
    "protected_track": 10,
    "separated_lane": 10,
    "buffered_lane": 5,
    "painted_lane": 3,
    "shared": 0,
    "none": 0,
}

# DECIDED: the crash score stays normalised against each run's own data. This
# makes the score *relative* -- a street can move because the rest of the city
# moved. The derived value is recorded in run.json so a score can be
# interpreted later.
CRASH_NORMALISATION_QUANTILE = 0.95

# The published blend. Must sum to 1.0.
W_LTS = 0.6
W_CRASH = 0.3
W_FACILITY = 0.1
