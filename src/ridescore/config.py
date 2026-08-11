"""Every threshold, weight and lookup table the pipeline uses.

One file, so that a change is a diff in one place.

Sections are labelled with what owns them, because not all of these belong to
the same thing:

* **pipeline** — true regardless of the network or the model.
* **network** — how the canonical road network is built and what attributes it
  carries. Shared by every model.
* **model <name>** — how one model turns network attributes into scores.

They stay in one file while there is one model. The split follows the owners
above when there is a second consumer: the blend moves into that model's
declaration, and the rest into `models/<name>/` when a second model arrives.

Values are ported from `notebooks/data_processing.ipynb` **unchanged**,
including its defects. Each known defect is marked `DEFECT:` with the fix
deferred to its own change, so that the port can be compared against the
notebook's output before anything moves.
"""

# ==========================================================================
# pipeline
# ==========================================================================

CRS = "EPSG:4326"

# ArcGIS answers 202 with a short JSON body while it generates the file, and
# only then 200 with the data. The notebook tested `r.ok`, which is true for
# 202, so it parsed the placeholder as if it were the dataset.
FETCH_TIMEOUT_S = 120
FETCH_ATTEMPTS = 8
FETCH_RETRY_WAIT_S = 5

# ==========================================================================
# network: sources
# ==========================================================================

ROADS_URL = "https://opendata.arcgis.com/datasets/DCGIS::roadway-block.geojson"

CRASHES_URL = (
    "https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/"
    "Public_Safety_WebMercator/MapServer/24/query"
)
CRASHES_PAGE_SIZE = 1000

# The DC boundary. The notebook fetched this from Nominatim via
# `osmnx.geocode_to_gdf`, which is a live lookup that cannot be cached or
# reproduced. It is a published dataset, so it is fetched like any other input.
BOUNDARY_URL = "https://opendata.arcgis.com/datasets/DCGIS::washington-dc-boundary.geojson"

# ==========================================================================
# network: attribute normalisation
# ==========================================================================

DEFAULT_NUM_LANES = 1
DEFAULT_SPEED_LIMIT = 25

# A lane count of -1 is the source's "unknown". Zero is a real answer and is
# kept: an alley with no marked travel lane scores 100, which is deliberate.
NUM_LANES_MIN_VALID = -1

# DEFECT (fix after the port): the test is "> 1", not "> 0", so a recorded
# speed limit of exactly 1 mph is discarded and replaced by the default.
SPEED_LIMIT_MIN_VALID = 1

# DEFECT (fix after the port): only the outbound speed limit is read.
# SPEEDLIMITS_IB is ignored, and the two can differ.
SPEED_LIMIT_FIELD = "SPEEDLIMITS_OB"

# The key a score hangs off. ROUTEID names a *route* -- Eastern Ave NW is one
# ROUTEID over 40-odd blocks -- so it cannot key a per-block score. BLOCKKEY is
# the source's own identifier for the block itself, and is unique across all
# 13,833 of them. OBJECTID is unique too but is a serial the publisher reassigns,
# which is the same trap as keying feedback to `ogc_fid`.
#
# This is not a claim that a block keeps its BLOCKKEY across DDOT republications.
# Segment identity across rebuilds is a separate piece of work; this is the best
# the source offers today and it beats a row number.
SEGMENT_ID_FIELD = "BLOCKKEY"

FUNCTION_CLASS_NAMES = {
    11: "Interstate",
    12: "Other Freeway and Expressway",
    14: "Principal/Primary Arterial",
    16: "Minor Arterial",
    17: "Collector",
    19: "Local",
}
FUNCTION_CLASS_DEFAULT = "Other"

BIKELANE_PRESENT_CODES = frozenset({"IB", "OB", "BD"})

# ==========================================================================
# network: crash join
#
# The count of crashes near a segment is an attribute of the street, like its
# speed limit -- any model may use it. Turning that count into a score is the
# model's business, and lives further down.
# ==========================================================================

# DECIDED: five years counted back from the run date, moving with each run. The
# run date is an explicit input, never read from the clock.
CRASH_YEARS_BACK = 5

CRASH_BUFFER_M = 10

# The crash record's own fields. A crash is "serious" or "fatal" by what it did
# to a cyclist, not to everyone involved -- the query already restricts to
# crashes that hurt one.
CRASH_DATE_FIELD = "REPORTDATE"
CRASH_TIMEZONE = "America/New_York"
CRASH_SERIOUS_FIELD = "major_injuries_bicyclist"
CRASH_FATAL_FIELD = "fatal_bicyclist"

# Carried through to `crashes`. The source has some ninety columns; these are
# the ones the notebook kept.
CRASH_KEEP_COLUMNS = (
    "report_date",
    "address",
    "major_injuries_bicyclist",
    "minor_injuries_bicyclist",
    "unknown_injuries_bicyclist",
    "fatal_bicyclist",
    "total_bicycles",
    "bicyclists_impaired",
    "total_vehicles",
    "total_pedestrians",
)

# Source field -> the name it is given in `crashes`.
CRASH_FIELD_NAMES = {
    "REPORTDATE_": "report_date",
    "ADDRESS": "address",
    "MAJORINJURIES_BICYCLIST": "major_injuries_bicyclist",
    "MINORINJURIES_BICYCLIST": "minor_injuries_bicyclist",
    "UNKNOWNINJURIES_BICYCLIST": "unknown_injuries_bicyclist",
    "FATAL_BICYCLIST": "fatal_bicyclist",
    "TOTAL_BICYCLES": "total_bicycles",
    "BICYCLISTSIMPAIRED": "bicyclists_impaired",
    "TOTAL_VEHICLES": "total_vehicles",
    "TOTAL_PEDESTRIANS": "total_pedestrians",
}

# DEFECT (fix after the port): the buffer is applied in Web Mercator, where a
# unit at DC's latitude is about 0.78 of a real metre -- so this is roughly
# 7.8 m on the ground, not 10. Changes which crashes attach to which street.
CRASH_BUFFER_CRS = "EPSG:3857"

# ==========================================================================
# network: output geometry
# ==========================================================================

SIMPLIFY_TOLERANCE_M = 4
COORDINATE_DECIMALS = 5
MIN_SEGMENT_LENGTH_M = 8

# ==========================================================================
# model ridescore_v1: stress rules
#
# NOTE: the repository README documents the "no facility, local street" rule as
# speed <= 25, but the notebook implements speed <= 20. The code is ported as
# written; the discrepancy is recorded here so the decision is deliberate.
# ==========================================================================

LTS_MARKED_LANE_SPEED_2 = 25
LTS_MARKED_LANE_LANES_2 = 2
LTS_MARKED_LANE_SPEED_3 = 30
LTS_MARKED_LANE_LANES_3 = 3

LTS_NO_FACILITY_SPEED_2 = 20
LTS_NO_FACILITY_SPEED_3 = 30
LTS_NO_FACILITY_LANES = 2
LTS_NO_FACILITY_FUNCTIONS = frozenset({"local"})

LTS_WORST = 4

# ==========================================================================
# model ridescore_v1: component scores, 0-100
# ==========================================================================

LTS_TO_SCORE = {1: 100, 2: 75, 3: 40, 4: 10}
LTS_TO_SCORE_DEFAULT = 10

FACILITY_BONUS = {
    "protected_track": 10,
    "separated_lane": 10,
    "buffered_lane": 5,
    "painted_lane": 3,
    "shared": 0,
    "none": 0,
}

FACILITY_TO_SCORE = {
    "protected_track": 100,
    "buffered_lane": 75,
    "painted_lane": 50,
    "none": 0,
}
FACILITY_TO_SCORE_DEFAULT = 0

NUM_LANES_TO_SCORE = {0: 100, 1: 100, 2: 75, 3: 50, 4: 25, 5: 25, 6: 0, 7: 0, 8: 0, 10: 0}
# DEFECT (fix after the port): a missing lane count scores 10 here -- i.e. as bad
# as an eight-lane road -- while the stress rules above treat the same missing
# value as DEFAULT_NUM_LANES (1), a quiet residential street.
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
SPEED_LIMIT_SCORE_INTERCEPT = 100
SPEED_LIMIT_SCORE_SLOPE = 2
ROAD_WIDTH_SCORE_INTERCEPT = 100

# DECIDED: the crash score stays normalised against each run's own data. The
# derived value is recorded in run.json so a score can be interpreted later.
CRASH_NORMALISATION_QUANTILE = 0.95

# ==========================================================================
# model ridescore_v1: the published blend
#
# The three weights are not here. They are the definition of what RideScore is,
# rather than machinery of the calculation, and a change to one should be a
# one-line diff reviewable without reading any Python. They live in
# `models/ridescore_v1/weights.toml`.
# ==========================================================================

# The blend is rounded to this many decimals, as the notebook did.
BLEND_DECIMALS = 1
