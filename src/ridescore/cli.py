"""The `ridescore` command.

Three stages, each writing a file, so any one can be re-run without repeating
the one before it:

    ridescore fetch     download sources into the dated cache
    ridescore build     normalise, score, write artifacts
    ridescore run       both

and one for looking at what a run produced:

    ridescore inspect   how many segments, the spread of each score, what changed

Only the shape is here. Each stage lands in its own change.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(
    add_completion=False,
    help="Turn public DC data into scored bike-safety segments.",
)

DEFAULT_CACHE = Path("raw")
DEFAULT_OUT = Path("out")

Cache = Annotated[Path, typer.Option(help="Where dated snapshots are kept.")]
Out = Annotated[Path, typer.Option(help="Where the artifacts are written.")]
RunDate = Annotated[
    dt.datetime | None,
    typer.Option(
        formats=["%Y-%m-%d"],
        help="An explicit input, recorded in run.json. Never read from the clock mid-build.",
    ),
]
Area = Annotated[
    str | None,
    typer.Option(
        help="A bounding box or named neighbourhood instead of all of DC. "
        "Most scoring changes can be judged on a few hundred segments."
    ),
]


def _not_yet(stage: str) -> None:
    raise typer.Exit(
        typer.style(f"`ridescore {stage}` is not implemented yet.", fg=typer.colors.YELLOW)
    )


@app.command()
def fetch(cache: Cache = DEFAULT_CACHE, run_date: RunDate = None) -> None:
    """Download the roadway blocks, crash records and city boundary.

    Writes `raw/<date>/` and never deletes an older snapshot. Comparing a street
    against its own past self needs the older inputs re-run through today's
    model, so a cache that overwrote itself would destroy every comparison point.
    """
    _not_yet("fetch")


@app.command()
def build(
    cache: Cache = DEFAULT_CACHE,
    out: Out = DEFAULT_OUT,
    run_date: RunDate = None,
    area: Area = None,
) -> None:
    """Normalise, score, and write the artifacts. Reads no network."""
    _not_yet("build")


@app.command()
def run(
    cache: Cache = DEFAULT_CACHE,
    out: Out = DEFAULT_OUT,
    run_date: RunDate = None,
    area: Area = None,
) -> None:
    """Fetch, then build."""
    _not_yet("run")


@app.command()
def inspect(
    out: Out = DEFAULT_OUT,
    against: Annotated[Path | None, typer.Option(help="A previous run to compare with.")] = None,
) -> None:
    """Summarise what a run produced, and what changed since last time."""
    _not_yet("inspect")


if __name__ == "__main__":
    app()
