# Parity with the deployed database

The port is judged against the notebook. This is what happens when you judge it
against `live/schema/0001_baseline.sql` instead — the dump of the database the
map is actually serving.

Method: build from a 2026-08-05 snapshot, join to the dump's `ridescoredc` table
on geometry (both endpoints and vertex count, rounded to five decimals), compare
every column. **13,821 of 13,829 segments matched**; the rest are blocks the
source has added or re-cut since the dump.

---

## What agrees

Exactly, on all 13,821 segments:

`num_lanes` · `num_lanes_raw` · `s_facility` · `num_lanes_score` ·
`facility_score`

Near-exactly, differing only on segments whose source attributes changed:

`speed_limit` (3) · `len` (3) · `road_width_score` (6) ·
`pavement_condition_score` (2) · `function_score` (362)

The dump's column list also reassembles exactly from the three files this
pipeline writes: `road_segment` plus `ridescore_v1_scores` is the deployed
table's column set, less `ogc_fid` and `wkb_geometry`.

---

## What disagrees, and why

### The crash columns — expected

`crash_count_5yr` differs on 786 segments and `s_crash` on 487. The window is
five years counted back from the run date, so a run today is over a different
window than the run that produced the dump, and the crash score is normalised
against each run's own data. Both are recorded in `run.json`. Nothing to fix.

### `lts_level` — the finding

**2,420 segments disagree, and the deployed database is the one that does not
match the notebook.**

A rule differing from the committed notebook in exactly two places reproduces
the deployed `lts_level` on **13,820 of 13,821** segments:

| | The notebook, as committed | What the deployed data behaves like |
|---|---|---|
| no facility, LTS 3 | `speed <= 30 and lanes <= 2 and local` | `speed <= 30 and lanes <= 2` — **no road-type test** |
| marked lane, LTS 3 | `speed <= 30 and lanes <= 3` | `speed <= 30 and lanes <= 2` |

The current rule reproduces the deployed values on 11,401.

So the deployed database was produced by an **earlier version of the stress
rules than the notebook now contains**, and the map has been serving those
scores ever since. The two changes account for the disagreement almost exactly:

- **2,194 segments**, no facility, ≤30 mph, ≤2 lanes, but a collector or
  arterial rather than a local street. Deployed 3; the committed rule says 4.
- **135 segments**, a painted or buffered lane on exactly 3 lanes. Deployed 4;
  the committed rule says 3.

The remaining ~90 are genuine source reclassifications: 45 blocks that were
`Local` and are now a class the lookup does not name, and 46 that were
`Collector` and are now `Local`.

`ridescore_v1` disagrees on 2,789 segments, which follows: it is the blend of
`lts_level`, the crash score and the facility bonus, and the first two are the
two that moved.

---

## What this means

**The port is faithful.** It reproduces the notebook, which is what issue #4
asked for and what its tests assert.

**Three artifacts describe the stress rules and no two agree.** The repository
README says a local street with no facility is LTS 2 at ≤ 25 mph; the notebook
implements ≤ 20; the deployed data behaves like neither on the LTS-3 branch. The
version that produced the deployed scores exists nowhere in version control.

This is the same class of problem as the scoring formula existing twice in the
database in two functions that had drifted — and it is the argument for the
pipeline in one paragraph. Whichever rule is chosen, from now on there is one
copy of it, a diff when it changes, and a test that fails when a score moves.

**It needs a decision, not a fix.** Three questions, in order of how many
segments they move:

1. Should a quiet collector with no bike lane be LTS 3, as the map shows today,
   or LTS 4, as the notebook says? **2,194 segments.**
2. Should a painted lane on three lanes be LTS 3, as the notebook says, or 4, as
   the map shows? **135 segments.**
3. Should the no-facility local-street rule be ≤ 20 mph, as the notebook says, or
   ≤ 25, as the README says? Not visible in this comparison, because the deployed
   data agrees with the notebook here — but it reclassifies every 21–25 mph local
   street whenever it is answered.

Until they are answered, the pipeline reproduces the notebook, and a deployment
of this output would visibly change the map.
