"""The component scores and the blend.

Each defect the port keeps has a test asserting the defective behaviour, so that
fixing one shows up as a failing test rather than as a silently moved score.
"""

from __future__ import annotations

import math

import pytest

from ridescore.models.ridescore_v1 import scores


class TestP95:
    def test_is_the_95th_percentile(self):
        assert scores.p95(list(range(101))) == 95

    def test_never_below_one(self):
        """It is a divisor, and a city with no crashes must not divide by zero."""
        assert scores.p95([0, 0, 0]) == 1

    def test_empty_is_one(self):
        assert scores.p95([]) == 1

    def test_ignores_missing(self):
        assert scores.p95([1, None, float("nan"), 100]) == scores.p95([1, 100])


class TestCrashInv:
    def test_no_crashes_scores_full_marks(self):
        assert scores.crash_inv(0, 4) == 100.0

    def test_the_95th_percentile_scores_zero(self):
        assert scores.crash_inv(4, 4) == 0.0

    def test_worse_than_the_95th_is_clamped(self):
        assert scores.crash_inv(400, 4) == 0.0

    def test_halfway(self):
        assert scores.crash_inv(2, 4) == 50.0


class TestComponentScores:
    @pytest.mark.parametrize(("level", "expected"), [(1, 100), (2, 75), (3, 40), (4, 10)])
    def test_stress_maps_to_a_score(self, level, expected):
        assert scores.lts_to_score(level) == expected

    def test_an_unknown_stress_level_scores_worst(self):
        assert scores.lts_to_score(9) == 10

    def test_speed_is_linear(self):
        assert scores.speedlimit_to_score(25) == 50

    def test_speed_score_goes_negative(self):
        """DEFECT, ported: unbounded above 50 mph."""
        assert scores.speedlimit_to_score(60) == -20

    def test_width_score_goes_negative(self):
        """DEFECT, ported: unbounded on a wide road."""
        assert scores.road_width_to_score(118) == -18

    def test_a_missing_width_produces_no_score(self):
        """DEFECT, ported: 100 - NaN is NaN, so a street nobody measured gets no score."""
        assert math.isnan(scores.road_width_to_score(float("nan")))

    def test_lanes_are_scored_on_the_raw_count(self):
        assert scores.num_lanes_to_score(2) == 75

    @pytest.mark.parametrize("missing", [None, float("nan")])
    def test_a_missing_lane_count_scores_as_an_eight_lane_road(self, missing):
        """DEFECT, ported: 10, while the stress rules read the same value as 1 lane."""
        assert scores.num_lanes_to_score(missing) == 10

    def test_an_unknown_lane_count_scores_the_same(self):
        assert scores.num_lanes_to_score(11) == 10

    @pytest.mark.parametrize(
        ("facility", "score", "bonus"),
        [("protected_track", 100, 10), ("buffered_lane", 75, 5), ("painted_lane", 50, 3),
         ("none", 0, 0), ("something else", 0, 0)],
    )
    def test_facility_scores_and_bonuses(self, facility, score, bonus):
        assert scores.facility_to_score(facility) == score
        assert scores.facility_bonus(facility) == bonus

    def test_function_scores(self):
        assert scores.function_to_score("Local") == 100
        assert scores.function_to_score("Interstate") == 0
        assert scores.function_to_score("not a road type") == 0

    def test_pavement_scores(self):
        assert scores.pavement_condition_to_score("Excellent") == 100
        assert scores.pavement_condition_to_score("Very Poor") == 0

    def test_unknown_pavement_scores_the_middle(self):
        """Not a defect: an unmeasured surface is assumed average rather than bad."""
        assert scores.pavement_condition_to_score(None) == 50
