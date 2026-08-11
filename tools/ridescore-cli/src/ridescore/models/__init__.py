"""Scoring models. One package per model, each owning its own parameters.

Adding a model is two steps: create the package with a `MODEL` declaration, and
add it to `REGISTRY` below. Nothing else in the codebase needs to change --
the CLI takes a `--model` name and looks it up here, so it has no idea which
models exist.

What is NOT a model:

* `ridescore.config` -- pipeline and network settings, true for every model
* `ridescore.factors` -- the per-factor columns the `update_score` stored
  procedure re-weights per request. A contract with `schema/`, not a scoring
  decision made here.

Dependencies point one way only. `ridescore_v1` consumes `lts`; `lts` knows
nothing about what consumes it. A model that reaches into another model's
package to borrow a rule means that rule belongs in its own model.
"""

from __future__ import annotations

from collections.abc import Iterable

from ridescore.models import lts, ridescore_v1
from ridescore.models.base import Model

#: Every model that can be built. Order here is not significant -- `resolve`
#: works out what has to run first from each model's `requires`.
REGISTRY: tuple[Model, ...] = (
    lts.MODEL,
    ridescore_v1.MODEL,
)

__all__ = ["REGISTRY", "Model", "get", "names", "resolve"]


def names() -> tuple[str, ...]:
    return tuple(m.name for m in REGISTRY)


def get(name: str) -> Model:
    for model in REGISTRY:
        if model.name == name:
            return model
    raise KeyError(f"unknown model {name!r}. Registered: {', '.join(names())}")


def resolve(name: str, available: Iterable[str]) -> tuple[Model, ...]:
    """Which models must run, in order, for `name` to be scoreable.

    A model declares the columns it needs. Anything the network already
    provides is satisfied; anything else has to come from another model, and
    that model's own requirements are resolved the same way.

    This is what lets `ridescore build --model ridescore_v1` run the stress
    rules first without the caller -- or the flow, or the notebook -- having to
    know that `ridescore_v1` is built on `lts`.
    """
    have = set(available)
    ordered: list[Model] = []
    visiting: set[str] = set()

    def visit(model: Model) -> None:
        if model.name in {m.name for m in ordered}:
            return
        if model.name in visiting:
            chain = " -> ".join([*visiting, model.name])
            raise ValueError(f"circular model dependency: {chain}")
        visiting.add(model.name)

        for column in model.requires:
            if column in have:
                continue
            producer = _producer_of(column, exclude=model.name)
            if producer is None:
                raise ValueError(
                    f"model {model.name!r} needs column {column!r}, which the network "
                    "does not provide and no registered model produces."
                )
            visit(producer)

        visiting.discard(model.name)
        ordered.append(model)
        have.update(model.produces)

    visit(get(name))
    return tuple(ordered)


def _producer_of(column: str, *, exclude: str) -> Model | None:
    for model in REGISTRY:
        if model.name != exclude and column in model.produces:
            return model
    return None
