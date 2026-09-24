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


def _source_root() -> Path | None:
    """The repository this module was imported from, or None if there is none.

    Derived from the module's own location rather than from the working
    directory, so that a run started from anywhere records this repository
    rather than whichever one the shell happened to be sitting in. A package
    installed from a wheel has no repository, and returns None.
    """
    root = Path(__file__).resolve().parents[2]
    return root if (root / ".git").exists() else None


def _git(root: Path, *args: str) -> str | None:
    with contextlib.suppress(subprocess.SubprocessError, OSError):
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
    return None


def _code_version(root: Path | None) -> dict:
    try:
        version = metadata.version("ridescore")
    except metadata.PackageNotFoundError:  # running from a source tree
        version = "unknown"

    commit = None
    if root is not None:
        commit = _git(root, "rev-parse", "HEAD")
        # A build from a modified tree did not come from the commit it names, so
        # say so rather than record a commit that does not describe this output.
        # `git status --porcelain` reports untracked files too, which is
        # deliberate: an uncommitted source file changes the result as much as an
        # edited one does.
        if commit is not None and _git(root, "status", "--porcelain"):
            commit += "-dirty"

    return {"package": version, "commit": commit, "python": platform.python_version()}


def _lockfile_hash(root: Path | None) -> str | None:
    if root is None:
        return None
    lockfile = root / "uv.lock"
    if not lockfile.exists():
        return None
    return hashlib.sha256(lockfile.read_bytes()).hexdigest()


def record(built: Built, snapshot: Snapshot, run_date: dt.date) -> dict:
    return {
        "run_date": run_date.isoformat(),
        "built_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "code": _code_version(_source_root()),
        "lockfile_sha256": _lockfile_hash(_source_root()),
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
