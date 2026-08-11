# RideScore — the published score

**This is what the live map serves today.** `ridescore_v1` is the default score
at [ridescoredc.com](https://ridescoredc.com), and the column of that name in
the `ridescoredc` table.

If you are proposing a new model, this is the thing to beat — and the thing to
compare against.

## The blend

Three components, each 0–100, weighted:

```
ridescore_v1 = 0.6 × LTS + 0.3 × Crash + 0.1 × Facility
```

| Component | From |
|---|---|
| **LTS** | `{1: 100, 2: 75, 3: 40, 4: 10}`, missing → 10. See [../LTS/](../LTS/) |
| **Crash** | `100 × (1 − crashes / p95(crashes))`, clamped to 0–100 |
| **Facility** | `{protected_track: 10, buffered_lane: 5, painted_lane: 3, none: 0}` |

The weights live in this model's own
[`config.py`](../../tools/ridescore-cli/src/ridescore/models/ridescore_v1/config.py)
as `W_LTS`, `W_CRASH`, `W_FACILITY` — import them rather than copying the
numbers:

```python
from ridescore.models.ridescore_v1 import config as v1
```

Note that the LTS *rules* are not in here. They are their own model at
[`models/lts/`](../../tools/ridescore-cli/src/ridescore/models/lts/), and
`ridescore_v1` consumes them — see [../LTS/](../LTS/).

## Two properties worth arguing about

**The facility component is capped at 10, not 100.** So it contributes at most
1 point of the final 100 — a protected track and a painted lane differ by 0.7
points here. Facility type already drives LTS, so this is closer to a
tie-breaker than a third opinion. Whether that is the right weighting is a fair
question.

**The crash score is normalised against each run's own 95th percentile.** It is
therefore *relative*: a street's score can change because the rest of the city
changed, not because the street did. That makes cross-run comparison harder than
it looks, and the derived p95 is recorded with each run so an old score can
still be interpreted.

Absolute normalisation would be more stable and less responsive. Both are
defensible; the current choice is deliberate.

## Comparing your model against it

The point of this folder is the diff. Score the same segments both ways, and
look at where you disagree:

```python
from ridescore import config
from ridescore.models.lts import lts_level
```

The streets where your model and `ridescore_v1` disagree — and your explanation
of why you are right — are the most persuasive output a proposal can have. A
model that agrees everywhere is not adding anything; a model that disagrees
everywhere probably has a bug.

## Naming

The score is `ridescore_v1` in the database, in the tile function, and in the
frontend. It is not renamed here even where a different name might read better,
because that column name is a contract with
[ridescoredc-website](https://github.com/civictechdc/ridescoredc-website).
