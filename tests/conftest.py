"""Shared fixtures. Nothing here reaches the network."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from ridescore.sources.cache import Snapshot

FIXTURES = Path(__file__).parent / "fixtures"
EXTRACT_DATE = dt.date(2026, 8, 5)


@pytest.fixture
def extract() -> Snapshot:
    """A committed extract of a real snapshot: 34 roadway blocks and 49 crashes.

    Chosen to cover every bike facility type and road function the source uses,
    plus blocks with crashes nearby, blocks with no recorded speed limit and
    blocks with no pavement condition. The boundary is the extract's own bounding
    box rather than the city's, so the clip does not depend on a 490 kB file.

    Regenerating it needs a real `raw/<date>/`; the selection is described above
    and in `tests/fixtures/README.md`.
    """
    return Snapshot(FIXTURES / "snapshot" / EXTRACT_DATE.isoformat())


@pytest.fixture
def run_date() -> dt.date:
    return EXTRACT_DATE
