"""Dataset descriptions: what a stage produces, in the stage's own terms.

A description is authored next to the code that writes the dataset and travels
with it. It is the only place an attribute's label, unit and meaning are
written down, which is what stops the popup field list existing three times and
disagreeing with itself.

`check` is the cheap half of what a real conformance step would do: the
description and the parquet must name the same attributes, with compatible
types. It says nothing about values.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

DESCRIPTIONS_DIR = Path("descriptions")

# The description's type vocabulary, and the pandas dtypes each accepts.
TYPE_FAMILIES = {
    "integer": ("i", "u"),
    "number": ("f", "i", "u"),
    "string": ("O", "U", "S"),
    "boolean": ("b",),
    "datetime": ("M",),
    "geometry": (),  # matched by dtype name, not kind
}


@dataclass(frozen=True)
class Description:
    dataset: str
    title: str
    description: str
    geography: str
    key: str | None
    # What identifies a feature inside a tile. A tile's feature id must be a
    # number, so a geography whose published key is a string carries a dense
    # integer alongside it.
    tile_key: str | None
    shape: str | None
    attributes: dict[str, dict]

    def attribute(self, name: str) -> dict:
        return self.attributes.get(name, {})

    def label(self, name: str) -> str:
        return self.attribute(name).get("label", name)


class DescriptionError(RuntimeError):
    """A description and the data it describes disagree."""


def load(dataset: str, root: Path = DESCRIPTIONS_DIR) -> Description:
    raw = yaml.safe_load((root / f"{dataset}.yaml").read_text())
    return Description(
        dataset=raw["dataset"],
        title=raw["title"],
        description=" ".join(raw["description"].split()),
        geography=raw["geography"],
        key=raw.get("key"),
        tile_key=raw.get("tile_key") or raw.get("key"),
        shape=raw.get("shape"),
        attributes=raw["attributes"],
    )


def load_all(root: Path = DESCRIPTIONS_DIR) -> dict[str, Description]:
    return {path.stem: load(path.stem, root) for path in sorted(root.glob("*.yaml"))}


def check(described: Description, frame: pd.DataFrame) -> list[str]:
    """Complaints, in the order a reader would want them. Empty means it agrees."""
    problems: list[str] = []

    described_names = set(described.attributes)
    actual_names = set(frame.columns)

    for missing in sorted(described_names - actual_names):
        problems.append(f"described but not written: {missing}")
    for extra in sorted(actual_names - described_names):
        problems.append(f"written but not described: {extra}")

    for name in sorted(described_names & actual_names):
        want = described.attributes[name].get("type")
        dtype = frame.dtypes[name]
        if want == "geometry":
            if dtype.name != "geometry":
                problems.append(f"{name}: described as geometry, written as {dtype}")
        elif want in TYPE_FAMILIES:
            if dtype.kind not in TYPE_FAMILIES[want]:
                problems.append(f"{name}: described as {want}, written as {dtype}")
        else:
            problems.append(f"{name}: unknown described type {want!r}")

    return problems
