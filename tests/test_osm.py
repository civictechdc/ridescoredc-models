"""The OpenStreetMap source: a synthetic street grid, and a committed real extract.

The **grid** is written here rather than committed, so each street can say what
it is for. It sits where the committed DDOT crash extract has crashes, so the
crash join has something to find.

The **extract**, `tests/fixtures/osm_snapshot/`, is a real Overpass answer cut
down to the blocks around 14th and U St NW by `scripts/make_osm_fixture.py`. It
carries a golden file and worked examples, as the DDOT extract does.

Nothing here reaches the network. Without the `osm` extra this module is
skipped, and the DDOT pipeline's tests still run.

    row 0   n00 ── n01 ── n02          residential, no tags at all
             │      │      ├── 901 ── 902   an alley meets column 2 mid-block
            900     │      │
             │      │      │
    row 1   n10 ── n11 ── n12          primary, lanes=4, maxspeed=30 mph
             │      │      │
    row 2   n20 ── n21 ── n22          residential, buffered bike lane

    column 0: n00-900 painted lane, 900-n10 none (a tag change mid-block),
              n10-n20 one-way residential
    column 1: highway=cycleway
    column 2: residential, split at the alley
"""

from __future__ import annotations

import datetime as dt
import math
import shutil
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("osmnx")

from ridescore import build, config
from ridescore.network import osm_normalise, osm_segments
from ridescore.sources import http, osm
from ridescore.sources.cache import Snapshot

FIXTURES = Path(__file__).parent / "fixtures"
EXTRACT_DATE = dt.date(2026, 8, 5)

OSM_EXTRACT_DATE = dt.date(2026, 10, 3)
OSM_EXTRACT = FIXTURES / "osm_snapshot" / OSM_EXTRACT_DATE.isoformat()
OSM_EXPECTED = FIXTURES / "expected_osm_extract.csv"
TEXT_COLUMNS = [
    "segment_id",
    "route_id",
    "route_name",
    "function",
    "bike_facility_type",
    "slow_street",
    "pavement_condition",
]

XS = (-77.0266, -77.0256, -77.0246)
YS = (38.91726, 38.9181, 38.9190)


def _n(row: int, column: int) -> int:
    return 100 + 10 * row + column


NODES = {_n(r, c): (XS[c], YS[r]) for r in range(3) for c in range(3)}
NODES |= {
    900: (XS[0], (YS[0] + YS[1]) / 2),
    901: (XS[2], (YS[0] + YS[1]) / 2),
    902: (XS[2] + 0.0006, (YS[0] + YS[1]) / 2),
}

WAYS = [
    (1, [_n(0, 0), _n(0, 1), _n(0, 2)], {"highway": "residential", "name": "A Street"}),
    (
        2,
        [_n(1, 0), _n(1, 1), _n(1, 2)],
        {"highway": "primary", "name": "B Avenue", "lanes": "4", "maxspeed": "30 mph"},
    ),
    (
        3,
        [_n(2, 0), _n(2, 1), _n(2, 2)],
        {
            "highway": "residential",
            "name": "C Street",
            "cycleway:right": "lane",
            "cycleway:right:buffer": "yes",
        },
    ),
    (4, [_n(0, 0), 900], {"highway": "residential", "name": "1st Street", "cycleway:both": "lane"}),
    (5, [900, _n(1, 0)], {"highway": "residential", "name": "1st Street"}),
    (6, [_n(1, 0), _n(2, 0)], {"highway": "residential", "name": "1st Street", "oneway": "yes"}),
    (7, [_n(0, 1), _n(1, 1), _n(2, 1)], {"highway": "cycleway", "name": "Grid Trail"}),
    (8, [_n(0, 2), 901, _n(1, 2), _n(2, 2)], {"highway": "residential", "name": "3rd Street"}),
    (9, [901, 902], {"highway": "service", "service": "alley"}),
]

EXPECTED_SEGMENTS = 14


def osm_xml(ways=WAYS) -> str:
    nodes = "\n".join(
        f'  <node id="{i}" lat="{lat}" lon="{lon}" version="1"/>'
        for i, (lon, lat) in NODES.items()
    )
    body = []
    for way_id, refs, tags in ways:
        nds = "".join(f'<nd ref="{r}"/>' for r in refs)
        tag_xml = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items())
        body.append(f'  <way id="{way_id}" version="1">{nds}{tag_xml}</way>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6">\n'
        + nodes
        + "\n"
        + "\n".join(body)
        + "\n</osm>\n"
    )


def _snapshot(tmp_path, xml: str) -> Snapshot:
    path = tmp_path / EXTRACT_DATE.isoformat()
    path.mkdir(parents=True)
    extract = FIXTURES / "snapshot" / EXTRACT_DATE.isoformat()
    for name in ("crashes.json", "dc_boundary.geojson"):
        shutil.copy2(extract / name, path / name)
    (path / osm.FILENAME).write_text(xml)
    return Snapshot(path)


@pytest.fixture
def grid(tmp_path) -> Snapshot:
    return _snapshot(tmp_path, osm_xml())


@pytest.fixture
def segments(grid):
    return osm_segments.segments_from_xml(osm.path(grid))


def _by_name(frame, name):
    return frame[frame["name" if "name" in frame else "route_name"] == name]


class TestSegmentation:
    def test_one_segment_per_stretch_between_intersections(self, segments):
        assert len(segments) == EXPECTED_SEGMENTS

    def test_alleys_split_streets_and_are_then_dropped(self, segments):
        assert not (segments["highway"] == "service").any()
        assert len(_by_name(segments, "3rd Street")) == 3

    def test_a_tag_change_mid_block_splits_the_block(self, segments):
        first = _by_name(segments, "1st Street")
        assert len(first) == 3
        assert first["cycleway:both"].eq("lane").sum() == 1

    def test_ids_are_unique_and_prefixed(self, segments):
        assert segments["segment_id"].is_unique
        assert segments["segment_id"].str.startswith("osm:").all()

    def test_ids_do_not_depend_on_drawing_direction(self, tmp_path, segments):
        reversed_ways = [(i, list(reversed(refs)), tags) for i, refs, tags in WAYS]
        flipped = osm_segments.segments_from_xml(
            osm.path(_snapshot(tmp_path / "flipped", osm_xml(reversed_ways)))
        )
        assert sorted(flipped["segment_id"]) == sorted(segments["segment_id"])

    def test_segment_id_sorts_its_end_nodes(self):
        assert osm_segments.segment_id(7, 3, 0) == osm_segments.segment_id(3, 7, 0) == "osm:3-7-0"


class TestTagRules:
    @pytest.mark.parametrize(
        ("raw", "mph"),
        [("25 mph", 25), ("40", 25), ("30 mph;25 mph", 30), ("signals", None), (None, None)],
    )
    def test_maxspeed(self, raw, mph):
        parsed = osm_normalise.parse_maxspeed(raw)
        assert math.isnan(parsed) if mph is None else parsed == mph

    @pytest.mark.parametrize(("raw", "lanes"), [("2", 2), ("2;3", 3), (None, None)])
    def test_lanes(self, raw, lanes):
        parsed = osm_normalise.parse_lanes(raw)
        assert math.isnan(parsed) if lanes is None else parsed == lanes

    @pytest.mark.parametrize(
        ("tags", "facility"),
        [
            ({"highway": "cycleway"}, "protected_track"),
            ({"highway": "path", "bicycle": "designated"}, "protected_track"),
            ({"highway": "residential", "cycleway:left": "track"}, "protected_track"),
            (
                {"highway": "primary", "cycleway:right": "lane", "cycleway:right:buffer": "yes"},
                "buffered_lane",
            ),
            (
                {"highway": "primary", "cycleway:right": "lane", "cycleway:right:buffer": "no"},
                "painted_lane",
            ),
            ({"highway": "primary", "cycleway": "lane"}, "painted_lane"),
            (
                {"highway": "primary", "cycleway:left": "lane", "cycleway:right": "track"},
                "protected_track",
            ),
            ({"highway": "primary", "cycleway": "shared_lane"}, "none"),
            ({"highway": "primary", "cycleway:right": "separate"}, "none"),
            ({"highway": "residential"}, "none"),
        ],
    )
    def test_facility(self, tags, facility):
        assert osm_normalise.classify_facility(tags) == facility

    def test_function_of_a_link_is_its_parent(self):
        assert osm_normalise.name_function({"highway": "primary_link"}) == (
            "Principal/Primary Arterial"
        )

    def test_unknown_highway_is_other(self):
        assert osm_normalise.name_function({"highway": "raceway"}) == "Other"

    def test_defaults_fill_lanes_and_speed_by_highway_type(self):
        tags = {"highway": "residential"}
        assert osm_normalise.num_lanes(tags) == 2
        assert osm_normalise.speed_limit(tags) == 20
        assert osm_normalise.num_lanes({**tags, "oneway": "yes"}) == 1
        assert osm_normalise.num_lanes({"highway": "cycleway"}) == 0

    def test_tagged_values_win_over_defaults(self):
        tags = {"highway": "residential", "lanes": "3", "maxspeed": "15 mph"}
        assert osm_normalise.num_lanes(tags) == 3
        assert osm_normalise.speed_limit(tags) == 15

    @pytest.mark.parametrize(
        ("smoothness", "condition"),
        [
            ("excellent", "Excellent"),
            ("intermediate", "Fair"),
            ("horrible", "Very Poor"),
            (None, None),
        ],
    )
    def test_pavement_from_smoothness(self, smoothness, condition):
        assert osm_normalise.pavement_condition({"smoothness": smoothness}) == condition

    def test_parking_sides(self):
        assert osm_normalise.parking_sides({"parking:both": "lane"}) == 2
        assert osm_normalise.parking_sides({"parking:lane:right": "parallel"}) == 1
        assert osm_normalise.parking_sides({"parking:left": "no"}) == 0

    def test_width_tagged_in_metres_is_given_in_feet(self):
        assert osm_normalise.road_width({"highway": "residential", "width": "10"}) == 32.8

    def test_width_is_estimated_from_lanes_and_parking(self):
        tags = {"highway": "residential", "parking:both": "lane"}
        assert osm_normalise.road_width(tags) == 2 * 11 + 2 * 8


class TestBuild:
    @pytest.fixture
    def built(self, grid):
        return build.build(grid, EXTRACT_DATE, source="osm")

    def test_writes_the_same_columns_as_the_ddot_network(self, built):
        assert tuple(built.road_segment.columns) == build.ROAD_SEGMENT_COLUMNS
        assert built.source == "osm"

    def test_every_segment_is_scored(self, built):
        assert len(built.ridescore_v1_scores) == len(built.road_segment) == EXPECTED_SEGMENTS
        assert not built.ridescore_v1_scores.isna().any().any()

    def test_width_is_never_empty(self, built):
        assert built.road_segment["road_width"].notna().all()

    def test_raw_columns_show_what_osm_left_out(self, built):
        segments = built.road_segment.set_index("route_name")
        avenue = segments.loc["B Avenue"]
        assert (avenue["num_lanes_raw"] == 4).all()
        assert (avenue["speed_limit_raw"] == 30).all()
        street = segments.loc["A Street"]
        assert street["speed_limit_raw"].isna().all()
        assert (street["speed_limit"] == 20).all()

    def test_facilities_reach_the_scores(self, built):
        facility = built.road_segment.set_index("segment_id")["bike_facility_type"]
        lts = built.ridescore_v1_scores.set_index("segment_id")["lts_level"]
        trail = built.road_segment.loc[
            built.road_segment["route_name"] == "Grid Trail", "segment_id"
        ]
        assert (facility[trail] == "protected_track").all()
        assert (lts[trail] == 1).all()
        assert set(facility) == {"protected_track", "buffered_lane", "painted_lane", "none"}

    def test_crashes_are_counted_on_osm_geometry(self, built):
        assert built.road_segment["crash_count_5yr"].sum() > 0

    def test_two_builds_agree(self, grid):
        first = build.build(grid, EXTRACT_DATE, source="osm")
        second = build.build(grid, EXTRACT_DATE, source="osm")
        pd.testing.assert_frame_equal(first.road_segment, second.road_segment)
        pd.testing.assert_frame_equal(first.ridescore_v1_scores, second.ridescore_v1_scores)

    def test_unknown_source_is_refused(self, grid):
        with pytest.raises(build.BuildError):
            build.build(grid, EXTRACT_DATE, source="tiger")

    def test_missing_osm_file_says_to_fetch(self, extract, run_date):
        with pytest.raises(FileNotFoundError, match="fetch --source osm"):
            build.build(extract, run_date, source="osm")


class TestFetch:
    def test_query_covers_the_network_and_its_nodes(self):
        text = osm.query()
        assert f"area({config.OSM_DC_AREA_ID})" in text
        assert '["service"="alley"]' in text
        assert '["bicycle"="designated"]' in text
        assert "(._;>;);" in text

    def test_saves_a_complete_answer(self, tmp_path, monkeypatch):
        monkeypatch.setattr(http, "get", lambda url, params=None, **_: osm_xml().encode())
        snapshot = Snapshot(tmp_path / EXTRACT_DATE.isoformat())
        snapshot.path.mkdir()
        osm.fetch(snapshot)
        assert snapshot.has(osm.FILENAME)
        assert osm.FILENAME in snapshot.record()

    def test_refuses_an_answer_overpass_cut_short(self, tmp_path, monkeypatch):
        partial = (
            b'<?xml version="1.0"?><osm version="0.6"><remark> runtime error: Query timed '
            b'out in "query" at line 3 after 301 seconds. </remark></osm>'
        )
        monkeypatch.setattr(http, "get", lambda url, params=None, **_: partial)
        snapshot = Snapshot(tmp_path / EXTRACT_DATE.isoformat())
        snapshot.path.mkdir()
        with pytest.raises(http.FetchError, match="stopped before finishing"):
            osm.fetch(snapshot)
        assert not snapshot.has(osm.FILENAME)


@pytest.fixture(scope="module")
def extract_built():
    return build.build(Snapshot(OSM_EXTRACT), OSM_EXTRACT_DATE, source="osm")


class TestCommittedExtract:
    """The whole pipeline over a real OSM extract around 14th and U St NW."""

    @pytest.fixture
    def built(self, extract_built):
        return extract_built

    @pytest.fixture
    def by_segment(self, built):
        return built.road_segment.merge(built.ridescore_v1_scores, on="segment_id").set_index(
            "segment_id"
        )

    def test_shape(self, built):
        assert built.counts() == {
            "road_segment": 156,
            "crashes": 67,
            "ridescore_v1_scores": 156,
        }
        assert built.road_segment["segment_id"].is_unique
        assert built.derived["p95_crash_count"] == 4

    def test_covers_every_facility_type(self, built):
        assert set(built.road_segment["bike_facility_type"]) == {
            "protected_track",
            "buffered_lane",
            "painted_lane",
            "none",
        }

    def test_matches_the_committed_expectations(self, built):
        """A golden file: produced by this code and reviewed once. It says the
        numbers have not moved; the worked examples below say they are right."""
        expected = pd.read_csv(OSM_EXPECTED, dtype=dict.fromkeys(TEXT_COLUMNS, "str"))
        actual = (
            built.road_segment.drop(columns="geometry")
            .merge(built.ridescore_v1_scores, on="segment_id")
            .sort_values("segment_id")
            .reset_index(drop=True)
        )
        # OSM leaves some text columns wholly empty (no slow streets), which the
        # build holds as None and the CSV reads back as NaN; compare them as empties.
        def text_as_objects(frame):
            out = frame.copy()
            for column in TEXT_COLUMNS:
                out[column] = out[column].astype(object).where(out[column].notna(), None)
            return out

        pd.testing.assert_frame_equal(
            text_as_objects(actual[expected.columns]),
            text_as_objects(expected),
            check_dtype=False,
            atol=1e-6,
        )

    def test_an_untagged_local_street_takes_the_defaults(self, by_segment):
        # Waverly Ter NW: no lanes, no maxspeed -> 2 lanes, 20 mph. none + local
        # + <=20 + <=2 -> LTS 2 -> 75. No crashes -> 100.
        # 0.6*75 + 0.3*100 + 0.1*0 = 75.0. Its lane score is the missing-count
        # 10, not the 75 of two lanes (config.NUM_LANES_TO_SCORE_DEFAULT).
        row = by_segment.loc["osm:1379443774-3659231215-0"]
        assert math.isnan(row.num_lanes_raw) and math.isnan(row.speed_limit_raw)
        assert (row.num_lanes, row.speed_limit, row.lts_level) == (2, 20, 2)
        assert row.ridescore_v1 == 75.0
        assert row.num_lanes_score == 10

    def test_a_buffered_lane_on_three_lanes(self, by_segment):
        # 14th St NW: buffered + 25 mph + 3 lanes: fails (<=25, <=2), passes
        # (<=30, <=3) -> LTS 3 -> 40. 3 crashes against a p95 of 4 -> 25.
        # 0.6*40 + 0.3*25 + 0.1*5 = 24 + 7.5 + 0.5 = 32.0
        row = by_segment.loc["osm:49745282-11227525634-0"]
        assert (row.bike_facility_type, row.lts_level, row.crash_count_5yr) == (
            "buffered_lane",
            3,
            3,
        )
        assert row.ridescore_v1 == 32.0

    def test_a_cycle_track_is_lts_1(self, by_segment):
        # A separately mapped cycleway: protected -> LTS 1 -> 100, no crashes,
        # bonus 10. 0.6*100 + 0.3*100 + 0.1*10 = 91.0
        row = by_segment.loc["osm:11263137939-11263137940-0"]
        assert (row.bike_facility_type, row.lts_level, row.road_width) == (
            "protected_track",
            1,
            10.0,
        )
        assert row.ridescore_v1 == 91.0

    def test_an_arterial_with_no_facility_is_hostile(self, by_segment):
        # Florida Ave NW: none, not local -> LTS 4 -> 10. One crash -> 75.
        # 0.6*10 + 0.3*75 + 0.1*0 = 6 + 22.5 = 28.5
        row = by_segment.loc["osm:1796371548-11263137939-0"]
        assert (row.lts_level, row.crash_count_5yr) == (4, 1)
        assert row.ridescore_v1 == 28.5

    def test_two_writes_are_byte_identical(self, built, tmp_path):
        first, second = tmp_path / "a", tmp_path / "b"
        build.write(built, first)
        build.write(build.build(Snapshot(OSM_EXTRACT), OSM_EXTRACT_DATE, source="osm"), second)
        for name in build.FILENAMES.values():
            assert (first / name).read_bytes() == (second / name).read_bytes()
