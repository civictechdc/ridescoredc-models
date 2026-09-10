"""The attribute normalisation, one rule at a time.

The missing-value cases are the ones worth having: they are what the notebook
decided quietly, and what a later fix will change deliberately.
"""

from __future__ import annotations

import pytest

from ridescore import config
from ridescore.network import normalise


class TestFacility:
    @pytest.mark.parametrize(
        ("tags", "expected"),
        [
            ({"BIKELANE_PROTECTED": "IB"}, "protected_track"),
            ({"BIKELANE_DUAL_PROTECTED": "BD"}, "protected_track"),
            ({"BIKELANE_BUFFERED": "OB"}, "buffered_lane"),
            ({"BIKELANE_CONVENTIONAL": "IB"}, "painted_lane"),
            ({}, "none"),
            ({"BIKELANE_CONVENTIONAL": None}, "none"),
            ({"BIKELANE_CONVENTIONAL": "NO"}, "none"),
        ],
    )
    def test_classifies(self, tags, expected):
        assert normalise.classify_facility(tags) == expected

    def test_protected_wins_over_painted(self):
        """A street with both is protected, whichever order the fields come in."""
        tags = {"BIKELANE_PROTECTED": "IB", "BIKELANE_CONVENTIONAL": "IB"}
        assert normalise.classify_facility(tags) == "protected_track"


class TestFunction:
    def test_names_a_known_class(self):
        assert normalise.name_function(19) == "Local"

    def test_unknown_class_is_other(self):
        assert normalise.name_function(99) == config.FUNCTION_CLASS_DEFAULT
        assert normalise.name_function(None) == config.FUNCTION_CLASS_DEFAULT


class TestNumLanes:
    def test_keeps_a_real_count(self):
        assert normalise.num_lanes(4) == 4

    def test_zero_is_a_real_answer(self):
        """An alley with no marked travel lane is not an alley with unknown lanes."""
        assert normalise.num_lanes(0) == 0

    @pytest.mark.parametrize("missing", [-1, None, float("nan")])
    def test_missing_becomes_the_default(self, missing):
        assert normalise.num_lanes(missing) == config.DEFAULT_NUM_LANES


class TestSpeedLimit:
    def test_keeps_a_real_limit(self):
        assert normalise.speed_limit(30) == 30

    @pytest.mark.parametrize("missing", [0, None, float("nan")])
    def test_missing_becomes_the_default(self, missing):
        assert normalise.speed_limit(missing) == config.DEFAULT_SPEED_LIMIT

    def test_one_mph_is_discarded(self):
        """DEFECT, ported: the test is `> 1`, so a recorded 1 mph is thrown away."""
        assert normalise.speed_limit(1) == config.DEFAULT_SPEED_LIMIT


class TestParking:
    @pytest.mark.parametrize(("raw", "expected"), [(2, True), (1, True), (0, False), (None, False)])
    def test_presence(self, raw, expected):
        assert normalise.parking_presence(raw) is expected
