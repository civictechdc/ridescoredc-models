"""What a model has to declare to take part in a build.

Deliberately small. A model is a name, the columns it writes, the columns it
needs first, and one callable that turns segments into those columns. Anything
more elaborate becomes a thing contributors have to learn before they can
promote a notebook.

The point of the declaration is that `build` can iterate. The network is the
expensive part and it is built once, so every registered model scores the *same*
segments in one pass -- which makes comparing a candidate against the published
score free rather than a separate run.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


@dataclass(frozen=True)
class Model:
    """One scoring model.

    `score` takes the segment table and returns **only** the columns named in
    `produces`, indexed the same way. It must not mutate its argument: two
    models scoring the same segments in one pass cannot be allowed to see each
    other's half-finished work.
    """

    name: str
    produces: tuple[str, ...]
    score: Callable[[pd.DataFrame], pd.DataFrame]
    requires: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        overlap = set(self.produces) & set(self.requires)
        if overlap:
            raise ValueError(f"{self.name}: cannot both require and produce {sorted(overlap)}")
