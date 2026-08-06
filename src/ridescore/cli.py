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
    run_record.write(run_record.record(built, snapshot, when, root=Path.cwd()), out)

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


# ==========================================================================
# prototype: a second geography, a loader, descriptions, a manifest
#
# Everything below is the demo. It is grouped here rather than spread through
# the file so that it is obvious what is prototype and what is pipeline.
# ==========================================================================

DEFAULT_DSN = "postgres://postgres:localdev@localhost:5433/db"
DEFAULT_DESCRIPTIONS = Path("descriptions")
DEFAULT_PRESENTATION = Path("presentation.yaml")

Dsn = Annotated[str, typer.Option(envvar="RIDESCORE_DSN", help="Where to load.")]
Descriptions = Annotated[Path, typer.Option(help="Where the dataset descriptions live.")]

DEMO_DATASETS = ["road_segment", "ridescore_v1_scores", "crashes", "bna_census_block"]


@app.command("build-bna")
def build_bna(
    export_dir: Annotated[Path, typer.Option(help="A bikescore export for one city.")],
    out: Out = DEFAULT_OUT,
) -> None:
    """Wrap the BNA export as a dataset. Reads no network, scores nothing."""
    from ridescore.demo import bna

    try:
        blocks = bna.build(export_dir)
    except FileNotFoundError as error:
        _fail(str(error))

    path = bna.write(blocks, out)
    typer.secho(f"Wrote {path}", fg=typer.colors.GREEN)
    typer.echo(f"  {len(blocks):,} census blocks")


@app.command()
def describe(
    out: Out = DEFAULT_OUT,
    descriptions: Descriptions = DEFAULT_DESCRIPTIONS,
) -> None:
    """Check each dataset against the description its stage published."""
    from ridescore.demo import descriptions as desc
    from ridescore.demo import load as loader

    failed = False
    for dataset in DEMO_DATASETS:
        path = out / f"{dataset}.parquet"
        if not path.exists():
            typer.secho(f"  {dataset:<22} not built", fg=typer.colors.YELLOW)
            continue

        problems = desc.check(desc.load(dataset, descriptions), loader.read(path))
        if problems:
            failed = True
            typer.secho(f"  {dataset:<22} {len(problems)} problem(s)", fg=typer.colors.RED)
            for problem in problems:
                typer.echo(f"      {problem}")
        else:
            described = desc.load(dataset, descriptions)
            typer.secho(
                f"  {dataset:<22} {len(described.attributes):>3} attributes, agrees",
                fg=typer.colors.GREEN,
            )

    if failed:
        raise typer.Exit(1)


@app.command()
def load(
    out: Out = DEFAULT_OUT,
    dsn: Dsn = DEFAULT_DSN,
    descriptions: Descriptions = DEFAULT_DESCRIPTIONS,
) -> None:
    """Write the datasets into PostGIS, with the table shape taken from the data."""
    import psycopg

    from ridescore.demo import descriptions as desc
    from ridescore.demo import load as loader

    try:
        loaded = loader.load(out, dsn, DEMO_DATASETS)
    except FileNotFoundError as error:
        _fail(f"Nothing to load: {error}")
    except desc.DescriptionError as error:
        _fail(str(error))
    except psycopg.OperationalError as error:
        _fail(f"Cannot reach the database at {dsn}:\n  {error}")

    with psycopg.connect(dsn) as connection:
        loader.create_join_view(
            connection,
            view="road_segment_scored",
            geometry="road_segment",
            scores="ridescore_v1_scores",
            key="segment_id",
        )
        connection.commit()

    typer.secho("Loaded", fg=typer.colors.GREEN)
    for dataset, rows in loaded.items():
        typer.echo(f"  {dataset:<22} {rows:>8,} rows")
    typer.echo("  road_segment_scored    (view)")


@app.command()
def manifest(
    to: Annotated[Path, typer.Option(help="Where to write manifest.json.")],
    presentation: Annotated[Path, typer.Option(help="This deployment's presentation.")] = (
        DEFAULT_PRESENTATION
    ),
    descriptions: Descriptions = DEFAULT_DESCRIPTIONS,
) -> None:
    """Resolve the presentation against the descriptions into a manifest."""
    import json

    from ridescore.demo import manifest as manifest_stage

    try:
        resolved = manifest_stage.generate(presentation, descriptions)
    except (KeyError, ValueError) as error:
        _fail(f"Cannot resolve the presentation: {error}")

    to.parent.mkdir(parents=True, exist_ok=True)
    to.write_text(json.dumps(resolved, indent=2) + "\n")

    typer.secho(f"Wrote {to}", fg=typer.colors.GREEN)
    for layer in resolved["layers"]:
        visible = "shown" if layer["default_visible"] else "hidden"
        typer.echo(f"  {layer['id']:<16} {layer['render']['template']:<12} {visible}")


if __name__ == "__main__":
    app()
