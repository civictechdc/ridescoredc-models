"""Fetch, build, score — the orchestration, with no model named anywhere.

Everything here works from what a model *declares*. Ask for `lts` and the
planner works back from its `requires` to the layers that supply those columns,
and from those layers to the sources that must be downloaded. Ask for
`ridescore_v1` and the same walk discovers that `lts` has to run first and that
crash records are needed after all.

    ridescore build --model lts
      requires  bike_facility_type, speed_limit, num_lanes, function
      base      covers all four
      layers    (none)
      sources   roads
      chain     lts

    ridescore build --model ridescore_v1
      requires  lts_level, crash_count_5yr, bike_facility_type
      lts_level from model lts, which is run first
      layers    crash_counts
      sources   roads, crashes, boundary
      chain     lts -> ridescore_v1

Adding a model changes none of this code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd

from ridescore import __version__, models, network, sources
from ridescore.models.base import Model
from ridescore.network.base import Layer
from ridescore.paths import RunPaths


@dataclass(frozen=True)
class Plan:
    """Everything a run needs, worked out before anything is downloaded."""

    model: str
    chain: tuple[Model, ...]
    layers: tuple[Layer, ...]
    sources: tuple[str, ...]

    @property
    def chain_names(self) -> tuple[str, ...]:
        return tuple(m.name for m in self.chain)

    @property
    def layer_names(self) -> tuple[str, ...]:
        return tuple(layer.name for layer in self.layers)

    @property
    def produces(self) -> tuple[str, ...]:
        return tuple(column for m in self.chain for column in m.produces)


def plan(model_name: str) -> Plan:
    """Work out what running `model_name` actually entails."""
    chain = models.resolve(model_name, network.columns_available())
    produced = {column for m in chain for column in m.produces}
    needed = {column for m in chain for column in m.requires} - produced
    layers, source_names = network.plan(needed)
    return Plan(model=model_name, chain=chain, layers=layers, sources=source_names)


def fetch(paths: RunPaths, run_plan: Plan, *, force: bool = False) -> dict[str, Path]:
    """Download only the sources this plan needs."""
    return sources.fetch(paths.ensure_data(), run_plan.sources, paths.run_date, force=force)


def source_files(paths: RunPaths, run_plan: Plan) -> dict[str, Path]:
    """Where the fetched sources should be, without fetching them."""
    return {name: sources.path_for(paths.data_dir, name) for name in run_plan.sources}


def build(paths: RunPaths, run_plan: Plan, *, area: str | None = None) -> gpd.GeoDataFrame:
    """Build the network and run every model in the chain over it, in order."""
    segments = network.build(source_files(paths, run_plan), run_plan.layers, area=area)

    for model in run_plan.chain:
        missing = [c for c in model.requires if c not in segments.columns]
        if missing:
            raise ValueError(
                f"model {model.name!r} needs {missing}, which the network did not produce. "
                "Check the layer that claims to supply them."
            )
        produced = model.score(segments)
        for column in model.produces:
            if column not in produced.columns:
                raise ValueError(
                    f"model {model.name!r} declares it produces {column!r} but did not."
                )
            segments[column] = produced[column]

    return segments


def write(
    paths: RunPaths,
    segments: gpd.GeoDataFrame,
    run_plan: Plan,
    *,
    area: str | None = None,
) -> dict[str, Path]:
    """Write the pre-database artifacts: the GeoJSON, and what the run was.

    GeoJSON because it is the format everything reads -- QGIS, a notebook,
    geopandas, a browser -- with no database and no credentials involved. The
    step that turns it into rows is a separate concern, and in production it is
    the one thing Kestra adds on top of exactly this command.
    """
    paths.ensure_outputs()
    segments.to_file(paths.segments, driver="GeoJSON")

    manifest = {
        "model": run_plan.model,
        "model_chain": list(run_plan.chain_names),
        "run_date": paths.stamp,
        "area": area,
        "sources": list(run_plan.sources),
        "layers": list(run_plan.layer_names),
        "segments": len(segments),
        "columns_produced": list(run_plan.produces),
        "ridescore_version": __version__,
        "summary": _summarise(segments, run_plan.produces),
    }
    paths.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {"segments": paths.segments, "manifest": paths.manifest}


def _summarise(segments: gpd.GeoDataFrame, columns: tuple[str, ...]) -> dict:
    """Enough of the distribution to notice a build that went wrong.

    A run that halves the segment count, or lands every street on one score, is
    a failure you want visible in the log rather than on the map a week later.
    """
    summary: dict[str, dict] = {}
    for column in columns:
        if column not in segments.columns:
            continue
        values = segments[column].dropna()
        if values.empty:
            summary[column] = {"count": 0}
            continue
        summary[column] = {
            "count": int(values.count()),
            "min": float(values.min()),
            "max": float(values.max()),
            "mean": round(float(values.mean()), 3),
            "distribution": {str(k): int(v) for k, v in values.value_counts().head(10).items()},
        }
    return summary
