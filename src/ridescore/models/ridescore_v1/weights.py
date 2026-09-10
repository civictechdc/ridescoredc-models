"""Reading `weights.toml`.

Kept apart from the scoring so that the file is loaded once, checked once, and
the scoring functions take plain numbers.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

WEIGHTS_FILE = Path(__file__).with_name("weights.toml")
TOLERANCE = 1e-9


class WeightsError(ValueError):
    """The weights file says something the model cannot act on."""


@dataclass(frozen=True)
class Weights:
    lts: float
    crash: float
    facility: float

    def as_dict(self) -> dict[str, float]:
        return {"lts": self.lts, "crash": self.crash, "facility": self.facility}


def parse(text: str) -> Weights:
    table = tomllib.loads(text).get("weights")
    if table is None:
        raise WeightsError("weights.toml has no [weights] table.")

    expected = {"lts", "crash", "facility"}
    missing = expected - table.keys()
    unknown = table.keys() - expected
    if missing:
        raise WeightsError(f"weights.toml is missing: {', '.join(sorted(missing))}.")
    if unknown:
        raise WeightsError(
            f"weights.toml has weights for nothing that is scored: {', '.join(sorted(unknown))}."
        )

    total = sum(table.values())
    if abs(total - 1.0) > TOLERANCE:
        raise WeightsError(
            f"The weights sum to {total}, not 1. A blend of weights that do not sum to 1 "
            "is on a different scale from every score already published."
        )

    return Weights(lts=table["lts"], crash=table["crash"], facility=table["facility"])


def load(path: Path = WEIGHTS_FILE) -> Weights:
    return parse(path.read_text())
