"""lts — level of traffic stress, 1 (calm) to 4 (hostile).

Physical characteristics only: no crash history. "Would you let a twelve-year-old
ride here?", not "has anyone been hurt here?"

A model in its own right, and an input to others -- `ridescore_v1` maps its
output through a lookup for 60% of the published blend, and a low-stress network
for BNA would consume it directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ridescore.models.base import Model
from ridescore.models.lts.rules import lts_level

if TYPE_CHECKING:
    import pandas as pd


def _score(segments: pd.DataFrame) -> pd.DataFrame:
    import pandas as pd

    return pd.DataFrame(
        {
            "lts_level": segments.apply(
                lambda r: lts_level(
                    r.bike_facility_type,
                    float(r.speed_limit),
                    float(r.num_lanes),
                    r.function,
                ),
                axis=1,
            )
        },
        index=segments.index,
    )


MODEL = Model(
    name="lts",
    produces=("lts_level",),
    # The *filled* speed and lane values, not the raw ones. The network is
    # responsible for having filled them before any model runs.
    requires=("bike_facility_type", "speed_limit", "num_lanes", "function"),
    score=_score,
    description="Level of traffic stress, 1 (calm) to 4 (hostile).",
)

__all__ = ["MODEL", "lts_level"]
