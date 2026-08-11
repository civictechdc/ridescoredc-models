# Ongoing data pipeline

**Level 3 of [three](../README.md#three-ways-to-work-here), and the only one
with a prerequisite that is not technical: the group has to have approved the
model first.**

Levels 1 and 2 are proposals. This level is a commitment — you are saying the
model should keep running, on a schedule, into the database the public map
serves, without anyone watching each run. Do not start here.

---

## Most of level 3 is not Kestra

The surprising part: **orchestration is the small half of this job.**

```
notebooks/YourModel/        the model as you proved it
        │
        │  ← this is the work
        ▼
tools/ridescore-cli/        the model as a tested, installable package
        │
        │  ← this is a few lines of YAML
        ▼
kestra/flows/               a schedule, a clone, and the same CLI command
```

Kestra clones this repository and runs `ridescore build`. That is essentially
all it does. So if your model is not in the CLI, there is nothing for a flow to
call — and a flow that inlines your model's logic has just created a second
copy that will drift from your notebook within a month.

Get the promotion right and the flow is trivial. Skip it and the flow is a
liability.

---

## Step 1 — promote the model into the CLI

If you followed
[the template](getting-started-as-a-modeler.md#start-from-the-template), this
is mechanical rather than a rewrite:

Your model gets its own package. You do not edit any shared file except to add
one line to the registry:

| From your notebook | Goes to |
|---|---|
| the parameters cell | `models/<your_model>/config.py` |
| the pure scoring function | `models/<your_model>/rules.py` |
| a `MODEL = Model(...)` declaration | `models/<your_model>/__init__.py` |
| your hand-checked examples | `tools/ridescore-cli/tests/models/<your_model>/` |
| one import + one entry | `models/__init__.py` — the registry |

The `Model` declaration is small on purpose — a name, the columns it writes,
the columns it needs first, and one callable. See
[`base.py`](../tools/ridescore-cli/src/ridescore/models/base.py). Declaring
`requires` is what lets `build` score every registered model in **one pass**
over the network, which makes the comparison against the published score free
rather than a second run.

Three rules for the move:

**Copy, do not retype.** Retyping a lookup table is how a `75` becomes a `70`
and nobody notices for six months.

**Test the boundaries.** Every threshold gets a test at the value that passes
and the value that does not.
[`test_lts.py`](../tools/ridescore-cli/tests/models/lts/test_rules.py)
is the pattern — one test per edge, named for the behaviour.

**Change nothing on the way through.** If you spot a bug during promotion,
promote it faithfully first and fix it as its own separate change. A promotion
that also alters behaviour cannot be verified against the notebook it came
from — this is exactly why `config.py` still carries six `DEFECT:` markers
reproducing the original notebook's bugs.

Your notebook then switches to importing what it used to define. It stops being
a second implementation and becomes the model's documentation and validation
harness — which is a promotion for the notebook too.

---

## Step 2 — understand the three phases

The pipeline is three flows, not one, and the split is deliberate:

| Flow | Does | Re-run when |
|------|------|-------------|
| `fetch_sources` | Open Data DC → a dated snapshot on disk | the data should be refreshed |
| `build_scores` | snapshot → scored artifacts | **constantly** — every scoring change |
| `load_database` | artifacts → rows in `ridescoredc` | the build looks right |

**Build is the one you iterate on.** A weight change has to be judged against
yesterday's snapshot, not against a fresh download that moved underneath you —
otherwise you cannot tell your change from the city's.

That is also why snapshots are dated and never deleted: comparing a street to
its own past self means re-running old inputs through today's model, and a
cache that overwrote itself would destroy every comparison point you have.

---

## Step 3 — add your model to the flows

Usually a new input on `build_scores` and nothing else, because the flow just
passes arguments to a CLI that already knows how to run your model.

Read [`kestra/README.md`](../kestra/README.md) before editing any YAML. It is
the reference for this project's Kestra setup: namespaces, secrets, the
deployment loops, and the plugin properties that changed names between versions.

Two things from it that catch everyone out:

**Git is the truth, the UI is a draft.** Flows sync from `main` into Kestra.
Whichever lands last wins — so a flow you edit in the UI and do not push is
*reverted* by the next sync. Iterate in the UI freely, then mirror the YAML
back into `kestra/flows/` and open a pull request.

**Anything you want to keep must be written to a Tier 2 host mount.** A Kestra
`WorkingDirectory` is per-execution scratch and is deleted the moment the run
ends. Write a snapshot there and it is gone before the next flow can read it.

---

## Step 4 — first run

In this order. Each step exists because skipping it makes the next failure much
harder to read:

1. **`prod.example.hello_world`** — proves flows are syncing from git at all.
   If this does not update after a push, your problem is the webhook, not your
   pipeline.
2. **`prod.ridescore.volume_mount_test`**, `mode=write`, then again with
   `mode=read` as a **separate execution**. Two runs is the whole point: the
   second proves data survived the first. Debugging a mount through an
   hour-long download is miserable.
3. **`fetch_sources`** — populates the snapshot cache.
4. **`build_scores`** with `area` set to a single neighbourhood. Seconds, not
   minutes, and enough to see whether the numbers are sane.
5. **`build_scores`** across all of DC.
6. **`load_database`** with `dry_run=true` — reports what would change, writes
   nothing.
7. **`load_database`** for real, once the dry run's numbers look right.

The schedule on `refresh_all` ships **disabled**. Turn it on only after the
whole sequence above has run by hand and the segment counts hold up. A schedule
firing into production before anything has been validated writes bad data on a
timer, at night, while nobody is watching.

---

## Who owns what

A boundary worth keeping straight, because crossing it is how user data gets
destroyed:

| | Owns | Meaning |
|---|---|---|
| [`schema/`](../schema/) | **DDL** | tables, columns, indexes, the `update_score` tile function |
| [`kestra/`](../kestra/) | **DML** | the rows of `ridescoredc` and `crashes_dc` |

The load flow replaces rows. It does not create, alter or drop tables.

And it must never go near the **survey tables** — those hold live submissions
written by visitors through `ridescoredc-website`. Nothing in this pipeline
produces them, so nothing in this pipeline may truncate them.

---

## Reference

- [`kestra/README.md`](../kestra/README.md) — the full setup: server, namespaces, secrets, mounts, debugging
- [`kestra/flows/`](../kestra/flows/) — the flows themselves, commented
- [`schema/README.md`](../schema/README.md) — migrations and the tile function
