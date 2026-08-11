"""Where a run reads and writes.

One layout, used identically by a notebook, a laptop and a Kestra flow:

    <root>/<model>/data/<run-date>/       what was fetched
    <root>/<model>/outputs/<run-date>/    what was produced

    runs/
    └── lts/
        ├── data/2026-08-10/
        │     roads.geojson  crashes.geojson  boundary.geojson
        └── outputs/2026-08-10/
              lts.geojson  run.json

**Why per-model.** A modeler working on `bikeability` cannot corrupt the
`lts` outputs someone else is looking at, and "delete my run and start again"
is `rm -rf runs/bikeability`. Self-contained beats clever when the audience is
a beginner on their first afternoon.

**Why dated.** Comparing a street to its own past self means re-running old
inputs through today's model. A cache that overwrote itself destroys every
comparison point, so nothing here ever deletes a snapshot.

**Why `--data-root` is separate from `--root`.** Fetched sources are identical
for every model -- the roads are the roads. Locally the default keeps each
model self-contained, but pointing `--data-root` at one shared directory makes
every model reuse a single download. That is exactly what a Kestra flow does:
outputs stay per-model on execution scratch, while `--data-root` points at the
Tier 2 host mount that survives between executions.

    ridescore fetch --model lts                                # runs/lts/data/<date>/
    ridescore fetch --model lts --data-root /data/raw          # /data/raw/<date>/
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path("runs")


@dataclass(frozen=True)
class RunPaths:
    """Every path a single run touches, derived once so nothing recomputes them."""

    root: Path
    model: str
    run_date: dt.date
    data_root: Path | None = None

    @property
    def stamp(self) -> str:
        return self.run_date.isoformat()

    @property
    def model_dir(self) -> Path:
        return self.root / self.model

    @property
    def data_dir(self) -> Path:
        """Fetched sources. Shared across models when `data_root` is given."""
        if self.data_root is not None:
            return self.data_root / self.stamp
        return self.model_dir / "data" / self.stamp

    @property
    def outputs_dir(self) -> Path:
        """Produced artifacts. Always per-model."""
        return self.model_dir / "outputs" / self.stamp

    # -- the individual files ------------------------------------------------

    @property
    def roads(self) -> Path:
        return self.data_dir / "roads.geojson"

    @property
    def crashes(self) -> Path:
        return self.data_dir / "crashes.geojson"

    @property
    def boundary(self) -> Path:
        return self.data_dir / "boundary.geojson"

    @property
    def segments(self) -> Path:
        """The scored segments -- the pre-database artifact."""
        return self.outputs_dir / f"{self.model}.geojson"

    @property
    def manifest(self) -> Path:
        """What this run was, so a number found later can be interpreted."""
        return self.outputs_dir / "run.json"

    # -- creation ------------------------------------------------------------

    def ensure_data(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir

    def ensure_outputs(self) -> Path:
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        return self.outputs_dir


def resolve_run_date(run_date: dt.date | dt.datetime | None) -> dt.date:
    """Today, only if nobody said otherwise -- and only ever read once.

    The clock is never consulted mid-build. A run that spans midnight must
    fetch, score and record against a single date, or its crash window moves
    underneath it.
    """
    if run_date is None:
        return dt.date.today()
    if isinstance(run_date, dt.datetime):
        return run_date.date()
    return run_date
