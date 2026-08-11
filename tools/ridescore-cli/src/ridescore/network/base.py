"""What a network layer has to declare.

The network is a **base** plus **optional layers**. The base turns road
geometry into normalised segments; every model needs it. Everything else is a
layer that adds columns, and a layer only runs when some model actually asked
for a column it produces.

That is the difference between a framework and one model's pipeline. Crash
counts felt like part of "the network" because the first two models used them
-- but LTS does not (it is physical characteristics only, no crash history),
and BNA will not either. Making them a layer means:

    ridescore fetch --model lts     downloads roads. Not crashes.
    ridescore fetch --model bna     will download destinations and census
                                    blocks, and still not crashes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import geopandas as gpd


@dataclass(frozen=True)
class Layer:
    """One optional enrichment of the segment table.

    `apply(segments, files)` returns a new frame with `produces` added. `files`
    maps source name to the path it was fetched to, and contains exactly the
    sources this layer declared.
    """

    name: str
    sources: tuple[str, ...]
    produces: tuple[str, ...]
    apply: Callable[[gpd.GeoDataFrame, dict[str, Path]], gpd.GeoDataFrame]
    description: str = ""
