"""`weights.toml` is data the model acts on, so it is checked like input."""

from __future__ import annotations

import pytest

from ridescore.models.ridescore_v1 import weights


def test_the_committed_weights_load():
    loaded = weights.load()
    assert loaded.as_dict() == {"lts": 0.6, "crash": 0.3, "facility": 0.1}


def test_weights_must_sum_to_one():
    with pytest.raises(weights.WeightsError, match="sum to"):
        weights.parse("[weights]\nlts = 0.6\ncrash = 0.3\nfacility = 0.5\n")


def test_a_missing_weight_is_an_error():
    """Rather than defaulting to zero, which would silently drop a component."""
    with pytest.raises(weights.WeightsError, match="missing: facility"):
        weights.parse("[weights]\nlts = 0.7\ncrash = 0.3\n")


def test_a_weight_for_nothing_is_an_error():
    with pytest.raises(weights.WeightsError, match="nothing that is scored: pavement"):
        weights.parse("[weights]\nlts = 0.6\ncrash = 0.3\nfacility = 0.1\npavement = 0.0\n")


def test_an_empty_file_is_an_error():
    with pytest.raises(weights.WeightsError, match="no \\[weights\\] table"):
        weights.parse("")
