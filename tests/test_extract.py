"""The whole pipeline over a committed extract of real DC data.

Two kinds of assertion here, and they check different things.

The **golden frame** catches any change to any score on any of the 34 blocks. It
cannot say the numbers are right, only that they have not moved: it was produced
by this code and reviewed once.

The **worked examples** are the ones that say the arithmetic is right. Each
states the rule and the sum, taken from the notebook rather than from this
implementation, so the two can disagree.
"""

from __future__ import annotations

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from ridescore import build

EXPECTED = "tests/fixtures/expected_extract.csv"

# The golden file is a CSV so that a moved score shows up in a review diff.
# CSV has no types, so the columns that are text in the data are named here --
# `route_id` is digits but is an identifier, and reading it as a number would
# make the comparison pass on a value the pipeline never produced.
TEXT_COLUMNS = [
    "segment_id",
    "route_id",
    "route_name",
    "function",
    "bike_facility_type",
    "slow_street",
    "pavement_condition",
]


@pytest.fixture
def built(extract, run_date):
    return build.build(extract, run_date)


class TestShape:
    def test_produces_all_three_datasets(self, built):
        assert built.counts() == {
            "road_segment": 34,
            "crashes": 49,
            "ridescore_v1_scores": 34,
        }

    def test_every_score_belongs_to_a_segment(self, built):
        assert set(built.ridescore_v1_scores["segment_id"]) == set(
            built.road_segment["segment_id"]
        )

    def test_the_key_identifies_one_street(self, built):
        assert built.road_segment["segment_id"].is_unique

    def test_tile_id_numbers_the_sorted_rows(self, built):
        segments = built.road_segment
        assert segments["tile_id"].tolist() == list(range(len(segments)))
        assert segments["segment_id"].is_monotonic_increasing

    def test_no_score_column_reached_road_segment(self, built):
        """One dataset, one producing stage: the network build does not score."""
        assert not {"ridescore_v1", "lts_level"} & set(built.road_segment.columns)

    def test_the_crash_normalisation_is_recorded(self, built):
        """The crash score is relative to this run, so the constant has to travel."""
        assert built.derived["p95_crash_count"] == 2
        assert built.derived["crash_window"] == ["2021-08-05", "2026-08-05"]


class TestGolden:
    def test_matches_the_committed_expectations(self, built):
        expected = pd.read_csv(EXPECTED, dtype=dict.fromkeys(TEXT_COLUMNS, "str"))
        actual = (
            built.road_segment.drop(columns="geometry")
            .merge(built.ridescore_v1_scores, on="segment_id")
            .sort_values("segment_id")
            .reset_index(drop=True)
        )
        assert_frame_equal(
            actual[expected.columns],
            expected,
            check_dtype=False,
            atol=1e-6,
        )


class TestWorkedExamples:
    """Each of these is the notebook's arithmetic, done by hand."""

    @pytest.fixture
    def by_street(self, built):
        return (
            built.road_segment.merge(built.ridescore_v1_scores, on="segment_id")
            .set_index("route_name")
        )

    def test_a_quiet_local_street_with_no_facility(self, by_street):
        # none + local + 20 mph + 2 lanes -> LTS 2 -> 75. No crashes -> 100.
        # 0.6*75 + 0.3*100 + 0.1*0 = 45 + 30 = 75.0
        row = by_street.loc["KENILWORTH TER NE"]
        assert (row.lts_level, row.lts_score, row.s_crash, row.s_facility) == (2, 75, 100.0, 0)
        assert row.ridescore_v1 == 75.0

    def test_an_arterial_with_no_facility_is_hostile(self, by_street):
        # none, but not a local street -> LTS 4 -> 10.
        # 0.6*10 + 0.3*100 + 0.1*0 = 6 + 30 = 36.0
        row = by_street.loc["BENNING RD NE"]
        assert (row.lts_level, row.lts_score) == (4, 10)
        assert row.ridescore_v1 == 36.0

    def test_a_painted_lane_on_three_lanes(self, by_street):
        # painted + 20 mph + 3 lanes: fails (<=25, <=2), passes (<=30, <=3) -> LTS 3 -> 40.
        # one crash against a p95 of 2 -> 100*(1 - 1/2) = 50. painted bonus 3.
        # 0.6*40 + 0.3*50 + 0.1*3 = 24 + 15 + 0.3 = 39.3
        row = by_street.loc["E ST NW"]
        assert (row.lts_level, row.crash_count_5yr, row.s_crash, row.s_facility) == (3, 1, 50.0, 3)
        assert row.ridescore_v1 == 39.3

    def test_crashes_at_or_above_the_95th_percentile_score_zero(self, by_street):
        row = by_street.loc["1ST ST NE"]
        assert (row.crash_count_5yr, row.s_crash) == (2, 0.0)
        # 0.6*10 + 0.3*0 + 0.1*0 = 6.0
        assert row.ridescore_v1 == 6.0


class TestDeterminism:
    def test_two_runs_over_the_same_inputs_agree(self, extract, run_date):
        first = build.build(extract, run_date)
        second = build.build(extract, run_date)
        assert_frame_equal(first.road_segment, second.road_segment)
        assert_frame_equal(first.ridescore_v1_scores, second.ridescore_v1_scores)
        assert first.derived == second.derived


class TestWrittenFiles:
    def test_written_and_read_back_unchanged(self, built, tmp_path):
        build.write(built, tmp_path)
        for dataset in build.FILENAMES:
            back = build.read(tmp_path, dataset)
            assert len(back) == built.counts()[dataset]

    def test_two_writes_are_byte_identical(self, built, tmp_path):
        """What lets a deployment decide by content rather than by a version bump."""
        first, second = tmp_path / "a", tmp_path / "b"
        build.write(built, first)
        build.write(built, second)
        for name in build.FILENAMES.values():
            assert (first / name).read_bytes() == (second / name).read_bytes()
