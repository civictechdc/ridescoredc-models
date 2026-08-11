# ridescore-cli

The one implementation of the RideScore DC pipeline. Everything else in this
repository is a *runner* over this package:

| Rung | Runner | What it calls |
|------|--------|---------------|
| 1 | a notebook in `notebooks/` | `from ridescore... import ...` |
| 2 | your laptop, against a local database | `ridescore run`, then `ridescore load` |
| 3 | a Kestra flow in `kestra/` | the same `ridescore` commands |

There is no second copy of the scoring logic anywhere. A model that lives only
in a notebook is a model that will silently diverge from what production
serves, which is the failure this layout exists to prevent.

## Three names, and why they disagree

| | Name | Who sees it |
|---|------|-------------|
| Folder | `tools/ridescore-cli/` | anyone browsing the repository |
| Distribution | `ridescore` | `uv add ridescore` |
| **Import** | **`ridescore`** | **every notebook** |

The folder carries `-cli` because "ridescore" already names the project, the
score column (`ridescore_v1`), and a model — the suffix says *which* ridescore
this folder is.

The **import name stays `ridescore`** on purpose. This is a library with a CLI
on top, not a CLI. If notebooks had to write `import ridescore_cli`, modelers
would reasonably read that as "a command-line tool, not for me" and re-implement
the rules by hand. (Python does this constantly: `scikit-learn` imports as
`sklearn`, `pillow` as `PIL`.)

## Layout

```
tools/ridescore-cli/
├── pyproject.toml          distribution metadata + pytest config
├── src/ridescore/
│   ├── cli.py                fetch / build / run / load / inspect
│   ├── config.py             pipeline + network settings — NOT model parameters
│   ├── factors.py            the per-factor columns update_score() re-weights
│   ├── sources/              fetching the raw data
│   ├── network/              the segments every model scores
│   └── models/
│       ├── base.py             what a model must declare
│       ├── __init.py__         the registry `build` iterates over
│       ├── lts/                stress rules — a model, and an input to others
│       └── ridescore_v1/       the published blend; consumes models.lts
└── tests/                  mirrors src/, so a module's tests are findable
    ├── conftest.py           shared fixtures + the no-network guard
    └── data/                 committed extract the `slow` marker runs over
```

### Three kinds of settings, deliberately separated

| Where | Holds | Changes when |
|---|---|---|
| `config.py` | pipeline + network | the data source or the normalisation changes |
| `models/<name>/config.py` | that model's parameters | someone tunes that model |
| `factors.py` | the tile-function contract | `update_score()` in `schema/` changes |

A contributor promoting a model creates a package and adds one registry line.
They never edit a shared settings file, so two models can never collide on a
name like `W_CRASH`.

`factors.py` is the one people misread: those `*_score` columns look like a
model but are not. They are per-attribute normalisations the pipeline writes so
the `update_score` stored procedure can blend them **per request** with whatever
weights the person looking at the map has set on the sliders. The scoring
decision lives in SQL, not here.

### Dependencies point one way

`ridescore_v1` imports `lts`. `lts` knows nothing about what consumes it — which
is what lets BNA build a low-stress network from the same rules without
reaching through `ridescore_v1` to get them.

## Status

**This is a partial port and not yet runnable end to end.**

| Piece | State |
|-------|-------|
| `config.py` | Complete — every value transcribed from the notebook |
| `models/ridescore_v1/lts.py` | Complete — the stress rules, with tests |
| `cli.py` | Shape only. Every command raises "not implemented yet" |
| `sources/`, `network/` | Empty |

The reference output is `notebooks/archive/data_processing.ipynb`, the original
32-cell monolith. The port is judged against it.

## The bugs are on purpose

`config.py` reproduces the notebook's defects rather than fixing them, each
marked `DEFECT:` with the fix deferred to its own change. Among them: only the
*outbound* speed limit is read; the 10 m crash buffer is applied in Web
Mercator, so it is nearer 7.8 m on the ground at DC's latitude; a missing lane
count scores 10/100 in one component while the stress rules read the same blank
as a quiet one-lane street.

This is deliberate. **You cannot tell whether a port is faithful if it also
changes behaviour.** Every value stays as the notebook had it until the port
can be diffed against the notebook's own output; then the defects get fixed one
at a time, each as a visible change to the score.

If you are tempted to fix one while passing through: don't. Open it as its own
change so the effect on the map is reviewable.

## Working on it

From anywhere in the repository:

```bash
uv sync                        # one venv, at the repository root
uv run ridescore --help
```

Tests run from this directory, so pytest picks up the config above:

```bash
cd tools/ridescore-cli && uv run pytest
uv run ruff check .            # (from the repository root — lints everything)
```

Tests never touch the network. `conftest.py` blocks the socket, so a test that
reaches for Open Data DC fails with an explanation instead of passing on your
machine and hanging in CI.
