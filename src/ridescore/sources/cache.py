"""The dated cache: one directory per fetch, never overwritten.

Comparing a street against its own past self means re-running the older inputs
through today's model, so a cache that overwrote itself has already destroyed
every comparison point. A snapshot directory is therefore written once. Fetching
again on a day that already has one reuses it unless asked not to.

Each snapshot carries a `fetch.json` recording, per file, where it came from,
when, how large it was and its SHA-256 -- which is what lets a later run say
whether the inputs actually moved.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

RECORD_NAME = "fetch.json"


@dataclass(frozen=True)
class Snapshot:
    """One dated directory of raw source files."""

    path: Path

    @property
    def date(self) -> dt.date:
        return dt.date.fromisoformat(self.path.name)

    def file(self, name: str) -> Path:
        return self.path / name

    def has(self, name: str) -> bool:
        return self.file(name).exists()

    @property
    def record_path(self) -> Path:
        return self.path / RECORD_NAME

    def record(self) -> dict:
        if not self.record_path.exists():
            return {}
        return json.loads(self.record_path.read_text())

    def note(self, name: str, *, url: str, content: bytes) -> dict:
        """Record what one file is, and return that record."""
        entry = {
            "url": url,
            "fetched_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        record = self.record()
        record[name] = entry
        self.record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        return entry

    def write(self, name: str, *, url: str, content: bytes) -> Path:
        path = self.file(name)
        path.write_bytes(content)
        self.note(name, url=url, content=content)
        return path


def open_snapshot(cache: Path, run_date: dt.date) -> Snapshot:
    """The snapshot for a date, created if it is not there yet."""
    path = cache / run_date.isoformat()
    path.mkdir(parents=True, exist_ok=True)
    return Snapshot(path)


def latest_snapshot(cache: Path, on_or_before: dt.date | None = None) -> Snapshot:
    """The most recent snapshot, so `build` need not be told which to read.

    Bounded by `on_or_before` when given, so that building for a past date reads
    the inputs as they were then rather than the newest ones on disk.
    """
    if not cache.exists():
        raise FileNotFoundError(f"No cache at {cache}. Run `ridescore fetch` first.")

    dated = []
    for child in cache.iterdir():
        if not child.is_dir():
            continue
        try:
            when = dt.date.fromisoformat(child.name)
        except ValueError:
            continue
        if on_or_before is None or when <= on_or_before:
            dated.append((when, child))

    if not dated:
        bound = f" on or before {on_or_before.isoformat()}" if on_or_before else ""
        raise FileNotFoundError(f"No snapshot in {cache}{bound}. Run `ridescore fetch` first.")

    return Snapshot(max(dated)[1])
