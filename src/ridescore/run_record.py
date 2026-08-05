"""`run.json`: what a run used, and what it worked out for itself.

A score is only interpretable against the run that produced it. The crash
component is normalised against each run's own 95th percentile, so the same
street can score differently in two runs over identical inputs if the city's
crash distribution moved. That constant, the window it was taken over, and the
weights are therefore recorded here rather than left implicit.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import platform
import subprocess
from importlib import metadata
from pathlib import Path

from ridescore.build import Built
from ridescore.sources.cache import Snapshot

FILENAME = "run.json"


def _code_version() -> dict:
    try:
        version = metadata.version("ridescore")
    except metadata.PackageNotFoundError:  # running from a source tree
        version = "unknown"

    # A package installed from a wheel has no repository to ask.
    commit = None
    with contextlib.suppress(subprocess.SubprocessError, OSError):
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()

    return {"package": version, "commit": commit, "python": platform.python_version()}


def _lockfile_hash(root: Path) -> str | None:
    lockfile = root / "uv.lock"
    if not lockfile.exists():
        return None
    return hashlib.sha256(lockfile.read_bytes()).hexdigest()


def record(built: Built, snapshot: Snapshot, run_date: dt.date, *, root: Path) -> dict:
    return {
        "run_date": run_date.isoformat(),
        "built_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "code": _code_version(),
        "lockfile_sha256": _lockfile_hash(root),
        # Recorded rather than relied upon: nothing in the pipeline iterates a
        # set or a dict in a way that reaches the output, so two runs agree
        # whatever this is. It is here so that a future run that *does* depend
        # on it can be told apart from one that does not.
        "python_hash_seed": os.environ.get("PYTHONHASHSEED"),
        "sources": {
            "snapshot": snapshot.path.name,
            "files": snapshot.record(),
        },
        "derived": built.derived,
        "row_counts": built.counts(),
    }


def write(record_body: dict, out: Path) -> Path:
    path = out / FILENAME
    path.write_text(json.dumps(record_body, indent=2, sort_keys=True) + "\n")
    return path


def read(out: Path) -> dict:
    return json.loads((out / FILENAME).read_text())
