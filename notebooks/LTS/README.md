# LTS — Level of Traffic Stress

How unpleasant a street is to ride on, 1 (calm) to 4 (hostile), from its
physical characteristics alone. No crash history: LTS asks "would you let a
twelve-year-old ride here?", not "has anyone been hurt here?"

This is both a model in its own right and the largest single input to
[RideScore](../RideScore/) — 60% of the published blend.

## The rules

Ours is a modified LTS, simpler than the Mineta/BLTS original:

| Bike lane | Lanes | Speed | Function | LTS |
|---|---|---|---|---|
| Protected track | — | — | — | **1** |
| Buffered or painted | ≤ 2 | ≤ 25 | — | **2** |
| Buffered or painted | ≤ 3 | ≤ 30 | — | **3** |
| None | ≤ 2 | ≤ 20 | Local | **2** |
| None | ≤ 2 | ≤ 30 | Local | **3** |
| Anything else | | | | **4** |

Implemented in
[`lts.py`](../../tools/ridescore-cli/src/ridescore/models/lts/rules.py),
importable directly:

```python
from ridescore.models.lts import lts_level
lts_level(facility="none", speed=20, lanes=2, function="Local")   # -> 2
```

## Known issues, kept on purpose

**The repository README says ≤ 25 mph for the no-facility local-street rule.
The code says ≤ 20.** The code is what the live map reflects. The discrepancy
is recorded rather than silently resolved, because deciding which is correct is
a modelling decision — it moves thousands of quiet streets between LTS 2 and 3
— and it deserves to be made deliberately, by the group, as its own change.

**A missing speed limit becomes 25 and a missing lane count becomes 1**, which
lands a segment with no recorded data at all on LTS 3. Whether "we know
nothing" should score the same as "we measured a moderately stressful street"
is an open question, and a good one for a new model to take on.

**`shared` and `separated_lane` fall through to 4.** They appear in the facility
bonus table but the classifier never produces them, so the branch is dead. If
your model can distinguish them, that is new signal.

## Ideas worth exploring

- Intersections. Ours is entirely segment-based, but crossings are where most
  of the real stress is.
- Traffic volume (AADT), not just lane count and posted speed.
- Parking presence — a door zone makes a painted lane substantially worse.
- Continuity: an LTS 1 block between two LTS 4 blocks is not usable.
