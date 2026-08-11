"""Parameters owned by the LTS model, and nothing else.

NOTE: the repository README documents the "no facility, local street" rule as
speed <= 25, but the notebook implements speed <= 20. The code is ported as
written; the discrepancy is recorded here so the decision is deliberate.
"""

LTS_MARKED_LANE_SPEED_2 = 25
LTS_MARKED_LANE_LANES_2 = 2
LTS_MARKED_LANE_SPEED_3 = 30
LTS_MARKED_LANE_LANES_3 = 3

LTS_NO_FACILITY_SPEED_2 = 20
LTS_NO_FACILITY_SPEED_3 = 30
LTS_NO_FACILITY_LANES = 2
LTS_NO_FACILITY_FUNCTIONS = frozenset({"local"})

LTS_WORST = 4
