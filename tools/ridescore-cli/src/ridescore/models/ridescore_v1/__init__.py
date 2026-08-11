"""ridescore_v1 — the published blend of stress, crash history and facility.

This is what the live map serves. The column name `ridescore_v1` is a contract
with the `update_score` stored procedure in `schema/` and with the frontend, so
it is not renamed even where a different name would read better.

    ridescore_v1 = 0.6 x LTS + 0.3 x Crash + 0.1 x Facility

It consumes `models.lts` rather than reimplementing the stress rules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ridescore.models.base import Model

if TYPE_CHECKING:
    import pandas as pd


def _score(segments: pd.DataFrame) -> pd.DataFrame:
    raise NotImplementedError(
        "The ridescore_v1 blend is still in notebooks/archive/data_processing.ipynb "
        "(cell 24). Port it here, unchanged, and diff against the notebook's output "
        "before altering anything."
    )


MODEL = Model(
    name="ridescore_v1",
    produces=("ridescore_v1",),
    # lts_level comes from models.lts, which the registry runs first.
    requires=("lts_level", "crash_count_5yr", "bike_facility_type"),
    score=_score,
    description="The published 0-100 safety score served by the live map.",
)

__all__ = ["MODEL"]
