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
# network: OSM source
#
# The alternative to the DDOT blocks above, selected with `--source osm`. The
# filters and tag list are those of `notebooks/BaseData/OSM_BaseData.ipynb`,
# where the team settled what counts as the network. Nothing built from OSM is
# comparable with anything built from DDOT blocks: segment identity differs.
# ==========================================================================

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_TIMEOUT_S = 300

# Overpass refuses requests' default User-Agent with a 406, and its usage
# policy asks callers to say who they are.
OVERPASS_USER_AGENT = "ridescoredc-models (+https://github.com/civictechdc/ridescoredc-models)"

# The District of Columbia, OSM relation 162069. Overpass numbers an area as the
# relation id plus 3,600,000,000.
OSM_DC_AREA_ID = 3600162069

# Which OSM street types count as the network. Excluded: footway, steps, plain
# path, service (alleys, driveways, parking aisles), pedestrian, motorway.
OSM_HIGHWAY_TYPES = (
    "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link",
    "residential", "unclassified", "living_street", "cycleway",
)

# Bike trails. Many are not tagged highway=cycleway, so paths and footways are
# kept where OSM says bikes belong.
OSM_TRAIL_FILTERS = (
    '["highway"="path"]["bicycle"~"^(designated|yes|permissive)$"]',
    '["highway"="footway"]["bicycle"="designated"]',
)
OSM_TRAIL_BICYCLE = {
    "path": frozenset({"designated", "yes", "permissive"}),
    "footway": frozenset({"designated"}),
}

# Alleys are fetched only so that a street is split where an alley meets it,
# matching DDOT's SubBlocks. They are dropped before anything is scored.
OSM_SPLIT_ONLY_FILTERS = ('["highway"="service"]["service"="alley"]',)

# Way tags carried onto each segment. A segment never spans a change in any of
# them, so a bike lane that starts mid-block splits the block there.
OSM_RAW_TAGS = (
    "highway", "name", "access", "bicycle", "service", "oneway", "oneway:bicycle", "maxspeed",
    "lanes", "lanes:forward", "lanes:backward",
    "cycleway", "cycleway:left", "cycleway:left:buffer", "cycleway:left:oneway",
    "cycleway:left:width", "cycleway:right", "cycleway:right:buffer",
    "cycleway:right:oneway", "cycleway:right:width", "cycleway:both",
    "cycleway:both:buffer", "cycleway:both:width", "cycleway:buffer", "cycleway:width",
    "parking:left", "parking:right", "parking:both",
    "parking:lane:left", "parking:lane:right", "parking:lane:both",
    "parking:left:restriction", "parking:right:restriction", "parking:both:restriction",
    "tracktype", "turn:lanes", "turn:lanes:forward", "turn:lanes:backward",
    "width", "footway", "smoothness", "surface",
)

# The road's job, by OSM highway type, in the names the model scores. A `_link`
# takes its parent's class. Trails are "Local": the facility rule already makes
# them LTS 1, and "Other" would score their function as a freeway's.
OSM_FUNCTION = {
    "trunk": "Other Freeway and Expressway",
    "primary": "Principal/Primary Arterial",
    "secondary": "Minor Arterial",
    "tertiary": "Collector",
    "residential": "Local",
    "unclassified": "Local",
    "living_street": "Local",
    "cycleway": "Local",
    "path": "Local",
    "footway": "Local",
}

# Filled in when OSM has no `lanes` tag: travel lanes in both directions, as
# DDOT's TOTALTRAVELLANES counts them. A one-way local street gets one.
OSM_DEFAULT_LANES = {
    "trunk": 4,
    "primary": 4,
    "secondary": 2,
    "tertiary": 2,
    "residential": 2,
    "unclassified": 2,
    "living_street": 1,
    "link": 1,
    "trail": 0,
}
OSM_DEFAULT_LANES_ONEWAY_LOCAL = 1
OSM_DEFAULT_LANES_FALLBACK = 2

# Filled in when OSM has no `maxspeed` tag, in mph. DC's default on local
# streets has been 20 mph since 2021; arterials are mostly posted at 25.
# Trails carry no motor traffic.
OSM_DEFAULT_SPEED_MPH = {
    "trunk": 35,
    "primary": 25,
    "secondary": 25,
    "tertiary": 25,
    "residential": 20,
    "unclassified": 20,
    "living_street": 20,
    "link": 25,
    "trail": 0,
}
OSM_DEFAULT_SPEED_FALLBACK_MPH = 25

KMH_PER_MPH = 1.609344

# OSM has no pavement condition index. `smoothness` is the nearest thing it
# has; a segment without it is left empty and scored as the model scores any
# unknown pavement.
OSM_SMOOTHNESS_TO_PAVEMENT = {
    "excellent": "Excellent",
    "good": "Good",
    "intermediate": "Fair",
    "bad": "Poor",
    "very_bad": "Very Poor",
    "horrible": "Very Poor",
    "very_horrible": "Very Poor",
    "impassable": "Very Poor",
}

# OSM rarely records a width, and a missing width leaves the width score empty,
# which empties every user-weighted score in the map. So it is estimated from
# lanes and parking, in feet as DDOT's TOTALCROSSSECTIONWIDTH is.
FEET_PER_METRE = 3.28084
OSM_LANE_WIDTH_FT = 11
OSM_PARKING_WIDTH_FT = 8
OSM_TRAIL_WIDTH_FT = 10

# `parking:*` values meaning cars park on the carriageway at the kerb.
OSM_PARKING_ON_STREET = frozenset({
    "lane", "street_side", "on_street", "parallel", "diagonal", "perpendicular",
    "half_on_kerb", "on_kerb", "marked", "yes",
})

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
# 50 mph, and 100 - width goes negative on a wide road. A *missing* width
# produces no score at all, because 100 - NaN is NaN.
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
