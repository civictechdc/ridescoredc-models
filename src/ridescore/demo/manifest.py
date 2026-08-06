"""The presentation, resolved.

Three inputs, one output. The presentation says what this deployment publishes
and how it is drawn; the descriptions say what each attribute is; the loader's
tables say what can actually be served. The manifest is the join of the three,
and is generated -- never hand-edited, because half of what is in it is a fact
about a pipeline run.

The frontend reads it and knows nothing else about RideScore, BNA or crashes.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import yaml

from ridescore.demo import descriptions as desc

MANIFEST_VERSION = "0.1-demo"
TILE_BASE = "/tiles"


def _split(reference: str) -> tuple[str, str]:
    """`dataset.attribute` -- the presentation's way of naming a field."""
    dataset, _, attribute = reference.partition(".")
    if not attribute:
        raise ValueError(f"Expected <dataset>.<attribute>, got {reference!r}")
    return dataset, attribute


def _field(reference: str, known: dict[str, desc.Description]) -> dict[str, Any]:
    """One field, described. Label, unit and range come from the description."""
    dataset, attribute = _split(reference)
    if dataset not in known:
        raise KeyError(f"{reference}: no description for dataset {dataset!r}")

    described = known[dataset].attributes.get(attribute)
    if described is None:
        raise KeyError(f"{reference}: {dataset} does not describe {attribute!r}")

    field: dict[str, Any] = {
        "field": attribute,
        "label": described.get("label", attribute),
        "type": described.get("type", "string"),
    }
    for optional in ("unit", "range", "description"):
        if optional in described:
            value = described[optional]
            field[optional] = " ".join(value.split()) if optional == "description" else value
    return field


def build(presentation: dict, known: dict[str, desc.Description]) -> dict[str, Any]:
    geographies: dict[str, Any] = {}
    sources: dict[str, Any] = {}

    for source_id, source in presentation["sources"].items():
        owner = known[source["geometry_from"]]

        geographies[owner.geography] = {
            "key": owner.key,
            "shape": owner.shape,
            "title": owner.title,
        }

        sources[source_id] = {
            "type": "vector",
            "geography": owner.geography,
            "tiles": [f"{TILE_BASE}/{source['relation']}/{{z}}/{{x}}/{{y}}"],
            "source_layer": source["relation"],
            "minzoom": source.get("minzoom", 1),
            "maxzoom": source.get("maxzoom", 14),
        }
        if owner.key:
            sources[source_id]["promote_id"] = owner.key

    layers = []
    for layer in presentation["layers"]:
        value = _field(layer["value"], known)
        dataset, _ = _split(layer["value"])

        resolved: dict[str, Any] = {
            "id": layer["id"],
            "title": layer.get("title") or value["label"],
            "description": layer.get("description") or value.get("description", ""),
            "attribution": known[dataset].title,
            "source": layer["source"],
            "delivery": {"mode": "tiles"},
            "value": value,
            "render": layer["render"],
            "popup": [_field(reference, known) for reference in layer.get("popup", [])],
            "displayable": True,
            "default_visible": layer.get("default_visible", False),
        }

        # A scale with no domain of its own takes the attribute's declared range.
        scale = resolved["render"].get("scale", {})
        if "domain" not in scale and "range" in value:
            scale["domain"] = value["range"]

        layers.append(resolved)

    return {
        "manifest_version": MANIFEST_VERSION,
        "generated": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "map": presentation["map"],
        "geographies": geographies,
        "sources": sources,
        "layers": layers,
    }


def generate(presentation_path: Path, descriptions_dir: Path) -> dict[str, Any]:
    presentation = yaml.safe_load(presentation_path.read_text())
    return build(presentation, desc.load_all(descriptions_dir))
