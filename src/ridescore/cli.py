"""The `ridescore` command.

Three stages, each writing a file, so any one can be re-run without repeating
the one before it:

    ridescore fetch     download sources into the dated cache
    ridescore build     normalise, score, write artifacts
    ridescore run       both

and one for looking at what a run produced:

    ridescore inspect   how many segments, the spread of each score, what changed
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Annotated

import typer

from ridescore import build as build_stage
from ridescore import run_record, summary
from ridescore.sources import boundary, crashes, roads
from ridescore.sources import cache as source_cache

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
Refresh = Annotated[
    bool,
    typer.Option("--refresh", help="Download again even if today's snapshot already has the file."),
]


def _run_date(given: dt.datetime | None) -> dt.date:
    """The run date, read from the clock exactly once and only if not given."""
    return given.date() if given is not None else dt.date.today()


def _fail(message: str) -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


@app.command()
def fetch(
    cache: Cache = DEFAULT_CACHE,
    run_date: RunDate = None,
    refresh: Refresh = False,
) -> None:
    """Download the roadway blocks, crash records and city boundary.

    Writes `raw/<date>/` and never deletes an older snapshot. Comparing a street
    against its own past self needs the older inputs re-run through today's
    model, so a cache that overwrote itself would destroy every comparison point.
    """
    when = _run_date(run_date)
    snapshot = source_cache.open_snapshot(cache, when)

    for name, download in (
        ("roadway blocks", lambda: roads.fetch(snapshot, refresh=refresh)),
        ("crashes", lambda: crashes.fetch(snapshot, when, refresh=refresh)),
        ("city boundary", lambda: boundary.fetch(snapshot, refresh=refresh)),
    ):
        typer.echo(f"  {name} ...")
        download()

    typer.secho(f"Snapshot {snapshot.path}", fg=typer.colors.GREEN)
    for filename, entry in sorted(snapshot.record().items()):
        typer.echo(f"  {filename:<26} {entry['bytes']:>10,} bytes  {entry['sha256'][:12]}")


@app.command()
def build(
    cache: Cache = DEFAULT_CACHE,
    out: Out = DEFAULT_OUT,
    run_date: RunDate = None,
) -> None:
    """Normalise, score, and write the artifacts. Reads no network."""
    when = _run_date(run_date)

    try:
        snapshot = source_cache.latest_snapshot(cache, on_or_before=when)
    except FileNotFoundError as error:
        _fail(str(error))

    typer.echo(f"Reading {snapshot.path}")
    try:
        built = build_stage.build(snapshot, when)
    except build_stage.BuildError as error:
        _fail(str(error))

    written = build_stage.write(built, out)
    run_record.write(run_record.record(built, snapshot, when), out)

    typer.secho(f"Wrote {out}", fg=typer.colors.GREEN)
    for dataset, path in written.items():
        typer.echo(f"  {path.name:<28} {built.counts()[dataset]:>8,} rows")
    typer.echo(f"  {run_record.FILENAME}")


@app.command()
def run(
    cache: Cache = DEFAULT_CACHE,
    out: Out = DEFAULT_OUT,
    run_date: RunDate = None,
    refresh: Refresh = False,
) -> None:
    """Fetch, then build."""
    when = _run_date(run_date)
    fetch(cache=cache, run_date=dt.datetime.combine(when, dt.time()), refresh=refresh)
    build(cache=cache, out=out, run_date=dt.datetime.combine(when, dt.time()))


@app.command()
def inspect(
    out: Out = DEFAULT_OUT,
    against: Annotated[Path | None, typer.Option(help="A previous run to compare with.")] = None,
) -> None:
    """Summarise what a run produced, and what changed since last time."""
    try:
        report = summary.summarise(out)
    except FileNotFoundError as error:
        _fail(f"Nothing to inspect in {out}: {error}")

    typer.secho(f"{out}", fg=typer.colors.GREEN, bold=True)
    for dataset, count in report.counts.items():
        typer.echo(f"  {dataset:<24} {count:>8,} rows")
    typer.echo(f"  {'network length':<24} {report.length_km:>8,.1f} km")

    typer.echo("\nDerived this run")
    for key, value in report.derived.items():
        typer.echo(f"  {key:<24} {value}")

    typer.echo("\nStress levels")
    for level, count in report.lts.items():
        typer.echo(f"  LTS {level}                    {count:>8,}")

    typer.echo("\nFilled in because the source did not say")
    for name, (count, share) in report.imputed.items():
        typer.echo(f"  {name:<24} {count:>8,}  ({share:.1f}%)")

    typer.echo("\nScore spread")
    typer.echo(report.spread.to_string())

    if against is not None:
        changed = summary.compare(out, against)
        typer.echo(f"\nAgainst {against}")
        added, removed = changed.attrs["added"], changed.attrs["removed"]
        typer.echo(f"  segments added {added:,}, removed {removed:,}")
        typer.echo(changed.to_string())


if __name__ == "__main__":
    app()
