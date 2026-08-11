"""Thresholds and lookups owned by the **pipeline** and the **network**.

Not models. A model owns its own parameters, in its own package:

    models/lts/config.py            the stress rules
    models/ridescore_v1/config.py   the published blend

and `factors.py` owns the per-factor columns the tile function re-weights.
This file holds only what is true regardless of which model is running: where
the data comes from, how a raw attribute becomes a normalised one, and what
shape the output geometry takes.

Values are ported from `notebooks/archive/data_processing.ipynb` **unchanged**,
including its defects. Each known defect is marked `DEFECT:` with the fix
deferred to its own change, so that the port can be compared against the
notebook's output before anything moves.
"""

# ==========================================================================
# pipeline
# ==========================================================================

CRS = "EPSG:4326"

# ==========================================================================
# network: sources
#
# NOTE: every field name below is a DDOT roadway-block attribute. If the
# network moves to OSM segmentation, this whole section is replaced -- but
# nothing under models/ is, because a model consumes normalised values and
# never sees a source field name.
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

# DEFECT (fix after the port): the test is "> 1", not "> 0", so a recorded
# speed limit of exactly 1 mph is discarded and replaced by the default.
SPEED_LIMIT_MIN_VALID = 1

# DEFECT (fix after the port): only the outbound speed limit is read.
# SPEEDLIMITS_IB is ignored, and the two can differ.
SPEED_LIMIT_FIELD = "SPEEDLIMITS_OB"

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
# model's business, and lives in that model's package.
# ==========================================================================

# DECIDED: five years counted back from the run date, moving with each run. The
# run date is an explicit input, never read from the clock.
CRASH_YEARS_BACK = 5

CRASH_BUFFER_M = 10

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
