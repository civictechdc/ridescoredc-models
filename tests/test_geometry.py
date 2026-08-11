"""Geometry preparation, including the two defects it carries."""

from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString

from ridescore.network import geometry

CRS = "EPSG:4326"


def frame(lines: list[LineString], ids: list[str] | None = None) -> gpd.GeoDataFrame:
    ids = ids or [str(i) for i in range(len(lines))]
    return gpd.GeoDataFrame({"segment_id": ids}, geometry=lines, crs=CRS)


class TestRounding:
    def test_rounds_longitude_and_latitude(self):
        line = LineString([(-77.0123456789, 38.9123456789), (-77.02, 38.92)])
        rounded = geometry.round_linestring(line, 5)
        assert rounded.coords[0][:2] == (-77.01235, 38.91235)

    def test_keeps_z_untouched(self):
        line = LineString([(-77.0123456789, 38.9123456789, 12.3456), (-77.02, 38.92, 15.0)])
        rounded = geometry.round_linestring(line, 5)
        assert rounded.coords[0] == (-77.01235, 38.91235, 12.3456)

    def test_survives_plain_2d(self):
        """The notebook unpacked every coordinate as x, y, z and failed here."""
        line = LineString([(-77.01, 38.91), (-77.02, 38.92)])
        assert geometry.round_linestring(line, 5).has_z is False


class TestDuplicates:
    def test_keeps_the_first_of_each_shape(self):
        shape = LineString([(-77.01, 38.91), (-77.02, 38.92)])
        other = LineString([(-77.03, 38.93), (-77.04, 38.94)])
        kept = geometry.drop_duplicate_geometries(frame([shape, other, shape], ["a", "b", "c"]))
        assert list(kept["segment_id"]) == ["a", "b"]


class TestShortSegments:
    def test_drops_a_segment_shorter_than_the_threshold(self):
        """DEFECT, ported: this drops the feature, so the block exists at no zoom."""
        tiny = LineString([(-77.01, 38.91), (-77.010005, 38.91)])
        long = LineString([(-77.02, 38.92), (-77.03, 38.93)])
        kept = geometry.drop_short_segments(frame([tiny, long], ["tiny", "long"]), min_length_m=8)
        assert list(kept["segment_id"]) == ["long"]


class TestSimplify:
    def test_removes_a_vertex_that_is_all_but_collinear(self):
        line = LineString([(-77.00, 38.90), (-77.005, 38.9000001), (-77.01, 38.90)])
        simplified = geometry.simplify(frame([line]), tolerance_m=4)
        assert len(simplified.geometry.iloc[0].coords) == 2

    def test_comes_back_in_wgs84(self):
        line = LineString([(-77.00, 38.90), (-77.01, 38.91)])
        assert geometry.simplify(frame([line]), tolerance_m=4).crs == CRS
