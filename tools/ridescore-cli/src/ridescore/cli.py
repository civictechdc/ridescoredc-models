"""The `ridescore` command.

Model-agnostic: every command takes `--model` and looks it up in the registry.
Nothing here names a model, so adding one is a package plus a registry line.

    ridescore models                    what can be built, and what each needs
    ridescore fetch   --model lts       download only what that model requires
    ridescore build   --model lts       score it, write GeoJSON + run.json
    ridescore run     --model lts       both
    ridescore inspect --model lts       what the last run produced
    ridescore load    --model lts       GeoJSON -> Postgres (what Kestra adds)

Everything lands under one predictable layout:

    runs/<model>/data/<run-date>/       what was fetched
    runs/<model>/outputs/<run-date>/    what was produced

The same four commands run in a notebook, on a laptop, and inside a Kestra
flow. Only `--root` and `--data-root` differ.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Annotated

import typer

from ridescore import models, pipeline
from ridescore.paths import DEFAULT_ROOT, RunPaths, resolve_run_date

app = typer.Typer(
    add_completion=False,
    help="Turn public DC data into scored bike-safety segments.",
    no_args_is_help=True,
)

ModelOpt = Annotated[str, typer.Option("--model", "-m", help="Which registered model to run.")]
Root = Annotated[Path, typer.Option(help="Where runs/<model>/ lives.")]
DataRoot = Annotated[
    Path | None,
    typer.Option(
        help="Share fetched sources across models instead of keeping them per-model. "
        "A Kestra flow points this at the Tier 2 host mount."
    ),
]
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
        help="A bounding box 'minx,miny,maxx,maxy' in WGS84 instead of all of DC. "
        "Most scoring changes can be judged on a few hundred segments."
    ),
]


def _paths(model: str, root: Path, data_root: Path | None, run_date) -> RunPaths:
    if model not in models.names():
        raise typer.BadParameter(
            f"unknown model {model!r}. Registered: {', '.join(models.names())}"
        )
    return RunPaths(
        root=root, model=model, run_date=resolve_run_date(run_date), data_root=data_root
    )


def _echo_plan(run_plan: pipeline.Plan) -> None:
    typer.echo(f"model    {run_plan.model}")
    typer.echo(f"chain    {' -> '.join(run_plan.chain_names)}")
    typer.echo(f"layers   {', '.join(run_plan.layer_names) or '(none)'}")
    typer.echo(f"sources  {', '.join(run_plan.sources)}")


@app.command(name="models")
def list_models() -> None:
    """What can be built, and what each model would download."""
    for model in models.REGISTRY:
        run_plan = pipeline.plan(model.name)
        typer.echo(typer.style(model.name, bold=True))
        typer.echo(f"  {model.description}")
        typer.echo(f"  produces  {', '.join(model.produces)}")
        typer.echo(f"  chain     {' -> '.join(run_plan.chain_names)}")
        typer.echo(f"  sources   {', '.join(run_plan.sources)}")
        typer.echo("")


@app.command()
def fetch(
    model: ModelOpt,
    root: Root = DEFAULT_ROOT,
    data_root: DataRoot = None,
    run_date: RunDate = None,
    force: Annotated[bool, typer.Option(help="Re-download even if already cached.")] = False,
) -> None:
    """Download the sources this model needs, into the dated cache.

    Local-first: a file already present is left alone, so re-running is cheap.
    Never deletes an older snapshot -- comparing a street against its own past
    self needs the older inputs re-run through today's model.
    """
    paths = _paths(model, root, data_root, run_date)
    run_plan = pipeline.plan(model)
    _echo_plan(run_plan)
    typer.echo("")

    fetched = pipeline.fetch(paths, run_plan, force=force)
    for name, path in fetched.items():
        size = path.stat().st_size / 1_048_576 if path.exists() else 0
        typer.echo(f"  {name:<10} {size:>8.1f} MB  {path}")
    typer.echo(typer.style(f"\nfetched into {paths.data_dir}", fg=typer.colors.GREEN))


@app.command()
def build(
    model: ModelOpt,
    root: Root = DEFAULT_ROOT,
    data_root: DataRoot = None,
    run_date: RunDate = None,
    area: Area = None,
) -> None:
    """Normalise, score, and write the artifacts. Reads no network."""
    paths = _paths(model, root, data_root, run_date)
    run_plan = pipeline.plan(model)
    _echo_plan(run_plan)

    missing = [n for n, p in pipeline.source_files(paths, run_plan).items() if not p.exists()]
    if missing:
        raise typer.BadParameter(
            f"missing sources {missing} in {paths.data_dir}. "
            f"Run: ridescore fetch --model {model} --run-date {paths.stamp}"
        )

    segments = pipeline.build(paths, run_plan, area=area)
    written = pipeline.write(paths, segments, run_plan, area=area)

    typer.echo(f"\n{len(segments):,} segments")
    for name, path in written.items():
        typer.echo(f"  {name:<10} {path}")
    typer.echo(typer.style(f"\nbuilt into {paths.outputs_dir}", fg=typer.colors.GREEN))


@app.command()
def run(
    model: ModelOpt,
    root: Root = DEFAULT_ROOT,
    data_root: DataRoot = None,
    run_date: RunDate = None,
    area: Area = None,
    force: Annotated[bool, typer.Option(help="Re-download even if already cached.")] = False,
) -> None:
    """Fetch, then build."""
    fetch(model=model, root=root, data_root=data_root, run_date=run_date, force=force)
    build(model=model, root=root, data_root=data_root, run_date=run_date, area=area)


@app.command()
def inspect(
    model: ModelOpt,
    root: Root = DEFAULT_ROOT,
    run_date: RunDate = None,
) -> None:
    """Summarise what a run produced, from its run.json."""
    paths = _paths(model, root, None, run_date)
    if not paths.manifest.exists():
        raise typer.BadParameter(
            f"no run.json at {paths.manifest}. Run: ridescore build --model {model}"
        )
    typer.echo(paths.manifest.read_text(encoding="utf-8"))


@app.command()
def load(
    model: ModelOpt,
    root: Root = DEFAULT_ROOT,
    run_date: RunDate = None,
    dry_run: Annotated[
        bool, typer.Option(help="Report what would change and write nothing. On by default.")
    ] = True,
) -> None:
    """Write the built GeoJSON into Postgres.

    The one step that is not part of local modelling: everything above produces
    files, and this turns files into rows. In production it is a Kestra flow
    that runs it, with credentials from secrets, after the same build a modeler
    ran on their laptop.

    Replaces rows and nothing else. Schema is `schema/`'s job: this creates no
    table, alters no column, and must never go near the survey tables -- those
    hold live submissions written by the website.

    Connection comes from the standard `PG*` environment variables, never an
    argument, so a URL cannot end up in a shell history or an execution log.
    """
    paths = _paths(model, root, None, run_date)
    if not paths.segments.exists():
        raise typer.BadParameter(
            f"nothing to load: {paths.segments} is missing. "
            f"Run: ridescore build --model {model}"
        )
    raise typer.Exit(
        typer.style(
            f"`ridescore load` is not implemented yet. Would load {paths.segments} "
            f"({'dry run' if dry_run else 'for real'}).",
            fg=typer.colors.YELLOW,
        )
    )


if __name__ == "__main__":
    app()
