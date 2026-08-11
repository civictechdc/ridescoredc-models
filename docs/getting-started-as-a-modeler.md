# Getting started as a modeler

**Level 1 of [three](../README.md#three-ways-to-work-here).** This is the entry
point to the project, and for most contributors it is the whole job.

You will be working with tables and dataframes. No maps, no database, no
containers — those come later and only if your model earns them. What matters
here is the computation: given what we know about a street, how safe is it to
ride on, and can you defend the answer?

---

## Before you write any code

**Post in the `#ridescore-dc` channel of the CivicTechDC Slack.** Say what you
are thinking of building.

Do this *first*, not when you are finished. Someone may have tried it, someone
may be halfway through it, and someone almost certainly has an opinion about
the data source you are about to trust. Fifteen minutes of conversation
regularly saves a weekend.

---

## Set up

**There is no conda environment and no system GDAL to install.** That is worth
saying first, because it is the thing that has historically stopped people.
geopandas 1.x installs pyogrio, which ships GDAL inside the wheel — so a stock
Windows, macOS or Linux machine can `pip install` its way to a working
geospatial stack in one step.

Pick either path below. They produce the same thing.

### Option A — uv (recommended)

[uv](https://docs.astral.sh/uv/) installs the right Python for you, so this
works even if you have no Python at all:

```bash
# install uv itself (see https://docs.astral.sh/uv/getting-started/installation/)
git clone https://github.com/civictechdc/ridescoredc-models
cd ridescoredc-models

uv sync                 # creates .venv at the repo root, installs everything
uv run ridescore models # check it worked
uv run jupyter lab
```

Every command is prefixed with `uv run` — there is no environment to activate
and no way to be in the wrong one.

### Option B — venv + pip (no new tools)

If you already have Python 3.12+, or you are on a machine where you cannot
install uv:

```bash
git clone https://github.com/civictechdc/ridescoredc-models
cd ridescoredc-models

python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate

pip install -e tools/ridescore-cli  # the pipeline, editable
pip install jupyterlab              # only if you want notebooks

ridescore models                    # check it worked
jupyter lab
```

`-e` means editable: your edits to the package take effect immediately, with no
reinstall. Remember to activate `.venv` in every new terminal.

> On Python 3.11 add `--ignore-requires-python` to the `pip install`. The code
> runs fine there; the 3.12 floor exists so nothing accidentally comes to
> depend on older behaviour.

### Check it really works

```bash
ridescore models
```

should list the registered models and — usefully — what each one would
download:

```
lts
  Level of traffic stress, 1 (calm) to 4 (hostile).
  produces  lts_level
  chain     lts
  sources   roads

ridescore_v1
  The published 0-100 safety score served by the live map.
  produces  ridescore_v1
  chain     lts -> ridescore_v1
  sources   roads, crashes, boundary
```

Note that `lts` downloads **roads only**. It scores physical characteristics
and declares no crash column, so it never fetches five years of crash records.
`ridescore_v1` does blend crash history, so asking for it pulls in two more
sources — and runs `lts` first, because it is built on it.

### Score some streets right now

Three commands, a few seconds, no database:

```bash
ridescore fetch --model lts --run-date 2026-08-10
ridescore build --model lts --run-date 2026-08-10 --area "-77.03,38.93,-77.01,38.95"
ridescore inspect --model lts --run-date 2026-08-10
```

That gives you 499 scored segments around Petworth in
`runs/lts/outputs/2026-08-10/lts.geojson` — open it in QGIS, or read it
straight into a notebook with `geopandas.read_file`. Drop `--area` for all of
DC; it takes minutes rather than seconds.

Everything lands under one predictable layout:

```
runs/<model>/data/<run-date>/       what was fetched
runs/<model>/outputs/<run-date>/    what was produced
```

Per-model, so you cannot corrupt someone else's run, and "start again" is
`rm -rf runs/<your-model>`. Dated, because comparing a street to its own past
self needs the old inputs kept.

---

## Look around `notebooks/` first

Every model in the project lives in [`notebooks/`](../notebooks/), one folder
each:

| Folder | What it is |
|--------|-----------|
| `BaseData/` | The shared road network every model starts from. **Read this one first.** |
| `LTS/` | Level of traffic stress — the stress rules, on their own |
| `RideScore/` | The published score, the blend the live map serves today |
| `BNA/` | Bicycle Network Analysis — a different methodology |
| `Bikeability/` | A newer candidate score |

Read `BaseData/` before anything else. Every model consumes the same road
segments with the same attributes, and knowing what those attributes actually
contain — including where they are missing — is most of the work.

Then read whichever existing model is closest to your idea. Copying a
neighbour is a perfectly good way to start.

---

## Start from the template

[`notebooks/model-template.ipynb`](../notebooks/model-template.ipynb) is the
recommended starting point. Copy it into your new folder and rename it.

The template has five sections and they are in that order for a reason:

**1. Load from `BaseData/`.** Never fetch your own copy of the road network. A
model that fetches independently will drift from every other model, and then
nobody can tell whether a score difference is your idea or your inputs.

**2. One parameters cell.** Every threshold, weight and lookup table you use,
named and defaulted in a single cell. Nothing inline, nothing buried in the
middle of a function.

**3. The rule as a pure function.** `f(attributes) -> score`. No globals, no
mutating a dataframe in place, no reaching outside its arguments.

**4. Validation.** Show the distribution. Hand-check a handful of streets you
personally know. Diff against the currently published score and *explain the
differences* — the streets where you disagree with RideScore v1 are the most
interesting output your notebook has.

**5. The promotion checklist.** What has to be true before this becomes real.

Sections 2 and 3 are strict because they are what makes your model
*promotable*. When a model is adopted it gets its own package under
[`models/`](../tools/ridescore-cli/src/ridescore/models/): your parameters cell
becomes its `config.py` and your pure function becomes its rules module —
**copied, not rewritten**. You never edit a shared settings file, so you can
never collide with another model's `W_CRASH`.

If your logic is tangled through twenty cells mutating a shared `gdf`, somebody
has to reimplement it instead, and reimplementation is where scores quietly
change.

You can see exactly what that costs by looking at
[`notebooks/archive/data_processing.ipynb`](../notebooks/archive/data_processing.ipynb),
the original 32-cell version of this project. It works, it produced the live
map, and porting it has meant carefully reproducing six separate bugs to prove
the port was faithful before any of them could be fixed.

---

## Reuse what already exists

The published logic is importable. Use it rather than retyping it:

```python
from ridescore import config                                 # pipeline + network settings
from ridescore.models.lts import lts_level                   # the stress rules
from ridescore.models.ridescore_v1 import config as v1       # the published blend's weights

lts_level(facility="painted_lane", speed=25, lanes=2, function="Local")   # -> 2
v1.W_LTS, v1.W_CRASH, v1.W_FACILITY                                       # -> 0.6, 0.3, 0.1
config.DEFAULT_SPEED_LIMIT                                                # -> 25
```

Note the split: `ridescore.config` holds what is true for *every* model (where
the data comes from, how a missing lane count is filled). Each model's own
parameters live in its own package.

If you want to compare your model against the published one, this is how you
get the published one — not by copying its numbers into your notebook, where
they will go stale the moment somebody tunes them.

---

## Propose it

Work on a feature branch, never directly on `develop`:

```bash
git checkout -b feature/new-model-name-here
```

Add **a new folder under `notebooks/`** containing your model. Give it a good
name — a clear, descriptive one, because it becomes what people call your model
in conversation from then on.

Include a short `README.md` in your folder covering:

- what the model claims, in a sentence
- what data it needs
- what you validated, and what you did not
- what you are unsure about

That last point is worth more than polish. "I could not work out how to handle
one-way pairs" is useful to a reviewer. A confident model with a quiet gap in
it is not.

Then open a pull request into `develop`, and post it in `#ridescore-dc`.

---

## What happens next

The group reviews model proposals together. If yours has traction, the next
step is showing it on an actual map —
[level 2](demonstrating-your-model.md).

Only after a model is approved by the group does anyone build a pipeline for
it ([level 3](ongoing-data-pipeline.md)). Do not skip ahead: an unapproved
model in the production pipeline is worse than no pipeline at all.
