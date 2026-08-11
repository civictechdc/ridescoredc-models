"""What a fetchable dataset has to declare.

A source is a named thing that lands one file in the run's data directory.
Nothing outside this package knows how it is fetched, and nothing knows the
full list -- a model asks for columns, and only the sources that can supply
them are ever downloaded.

That matters because models differ more than they look. LTS needs road
geometry and tags and nothing else. RideScore additionally needs crashes. BNA
will need destinations and census blocks and will not care about crashes at
all. Fetching all three because the first model happened to need them is how a
framework quietly becomes one model's framework.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Source:
    """One fetchable dataset.

    `fetch(dest, run_date, force)` must write `dest` and return it. It is
    local-first: if `dest` already exists and `force` is false, leave it alone.
    """

    name: str
    filename: str
    fetch: Callable[[Path, dt.date, bool], Path]
    description: str = ""
