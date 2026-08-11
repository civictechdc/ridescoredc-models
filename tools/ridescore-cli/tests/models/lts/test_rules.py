"""Boundaries of the stress rules table.

The boundaries are where the defects live, so each rule is tested at the value
that passes and the value that does not.
"""

import pytest

from ridescore.models.lts.rules import lts_level


def test_protected_track_is_always_calm():
    # No speed, lane count or road function can make a protected track worse.
    assert lts_level("protected_track", 55, 8, "Interstate") == 1


@pytest.mark.parametrize("facility", ["buffered_lane", "painted_lane"])
class TestMarkedLane:
    def test_calm_at_the_boundary(self, facility):
        assert lts_level(facility, 25, 2) == 2

    def test_one_mph_over_drops_a_level(self, facility):
        assert lts_level(facility, 26, 2) == 3

    def test_one_lane_over_drops_a_level(self, facility):
        assert lts_level(facility, 25, 3) == 3

    def test_middle_band_at_its_boundary(self, facility):
        assert lts_level(facility, 30, 3) == 3

    def test_beyond_the_middle_band(self, facility):
        assert lts_level(facility, 31, 3) == 4
        assert lts_level(facility, 30, 4) == 4

    def test_road_function_is_ignored_for_marked_lanes(self, facility):
        assert lts_level(facility, 25, 2, "Interstate") == 2


class TestNoFacility:
    def test_quiet_local_street(self):
        # 20, not 25 -- see the note in config.LTS_NO_FACILITY_SPEED_2.
        assert lts_level("none", 20, 2, "Local") == 2

    def test_one_mph_over_drops_a_level(self):
        assert lts_level("none", 21, 2, "Local") == 3

    def test_middle_band_at_its_boundary(self):
        assert lts_level("none", 30, 2, "Local") == 3

    def test_beyond_the_middle_band(self):
        assert lts_level("none", 31, 2, "Local") == 4

    def test_a_third_lane_is_hostile_regardless_of_speed(self):
        assert lts_level("none", 20, 3, "Local") == 4

    def test_not_local_is_hostile_regardless_of_speed(self):
        # A 20 mph arterial with no facility is still 4.
        assert lts_level("none", 20, 2, "Collector") == 4

    def test_road_function_match_is_case_insensitive(self):
        assert lts_level("none", 20, 2, "local") == 2
        assert lts_level("none", 20, 2, "LOCAL") == 2

    def test_missing_road_function(self):
        assert lts_level("none", 20, 2) == 4
        assert lts_level("none", 20, 2, None) == 4


def test_unknown_facility_is_treated_as_hostile():
    # 'shared' and 'separated_lane' appear in the facility bonus table but are
    # never produced by the classifier, so they fall through to the worst case.
    assert lts_level("shared", 20, 1, "Local") == 4
    assert lts_level("separated_lane", 20, 1, "Local") == 4


def test_filled_in_defaults_read_as_a_quiet_street():
    # A segment with no recorded lane count and no recorded speed limit arrives
    # here as (25, 1). This is the defect recorded in config: the same missing
    # lane count scores 10/100 in the lane-count component.
    from ridescore import config

    assert lts_level("none", config.DEFAULT_SPEED_LIMIT, config.DEFAULT_NUM_LANES, "Local") == 3
