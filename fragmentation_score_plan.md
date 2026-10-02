# Challenge 1 Implementation Plan — Low-Stress Network Fragmentation Score (`connectivity_lts`)

## How to use this document

Work through the steps below **one at a time**. For each step: implement it, run it, show the output of the "watch for" checks, and stop for review before moving to the next step. Do not implement multiple steps in one pass — each step has a specific thing to verify before it's safe to build on top of it.

## Project context

RideScore DC's existing models (LTS, BNA, and every index named in the challenge doc — BLOS, BCI, Bike ISI) score each street segment using only that segment's own attributes: speed, lanes, bike facility presence. None of them ask whether a "safe" segment is actually *reachable* without first crossing an unsafe one. A segment can be individually low-stress and still be a disconnected island, functionally useless for trip planning.

This project adds a connectivity-aware feature to a custom, transparent stress classification: for every Low-stress segment, is it part of a large connected network of other Low-stress segments, or is it isolated? The network graph is built directly from the snapshot's own `osm_u`/`osm_v`/`osm_key` columns — no external routing library needed.

**Scope for today:** snapshot-only (no crash data, no scoring pipeline dependency). Output is a standalone notebook + results file + README, submitted as a PR per the submission spec below.

## Output specification (per "Submitting Your Work")

- **ID columns (required):** `osm_u`, `osm_v`, `osm_key`, plus a `snapshot_date` column (literal value `"2026-09-29"` — segment IDs only hold within one snapshot, so this must travel with every row).
- **Primary model column:** `connectivity_lts` — categorical, one of `High`, `Medium`, `Low-Isolated`, `Low-Connected`.
- **Supporting columns:** `base_stress_class` (the pre-connectivity 3-tier classification), `component_size_segments`, `component_size_m`, `is_isolated` (boolean), `is_one_way_bridge` (boolean — see Step 7; `False` for every row that isn't a qualifying bridge, including all Medium/High rows, never `NaN`).
- **Format:** Parquet preferred.
- **Location:** `notebooks/low-stress-fragmentation/`, containing the notebook, the results file, and `README.md` together.
- **Row count:** one row per original snapshot segment — Medium/High rows get `NaN` for the component columns, not zero.

---

## Step 0 — Environment and data load

**a) Do:** Load both snapshot files (Parquet and GeoJSON) from wherever they live relative to this notebook's actual location, confirm `geopandas`/`networkx`/`matplotlib` import cleanly, print shape and column list.

**b) Watch for:** The notebook will live at `notebooks/low-stress-fragmentation/`, nested two levels into the repo — the relative path to the sibling `ridescore-data` folder from *there* is different from the path used earlier at the repo root (likely `../../ridescore-data/...` instead of `../ridescore-data/...`). Get this path right before anything else, or every later step silently works off stale/wrong data.

**c) Why:** Baseline sanity check — confirms the environment and data are actually usable before any real logic is written.

---

## Step 1 — Missingness audit

**a) Do:** For each attribute pair you'll need — speed (`dc_SPEEDLIMITS_OB` vs `osm_maxspeed`), lanes (`dc_TOTALTRAVELLANES` vs `osm_lanes`), bike facility (`dc_BIKELANE_*` columns vs `osm_cycleway*` columns) — print the null rate of each source individually. Also print the `match_status` value counts.

**b) Watch for:** A null in a bike-facility column doesn't necessarily mean "confirmed no facility" — it may just mean "not tagged." You'll have to treat null as "no facility" anyway (there's no better option), but that's a stated assumption, not a neutral fact — note it for the README now so you don't forget later. Also verify `osm_lanes`'s actual dtype in your data before doing arithmetic on it — it's sometimes stored as text.

**c) Why:** You need to know how much you're actually filling in via fallback before you trust the merged columns in Step 2.

---

## Step 2 — Fallback-merged attributes

**a) Do:** Build three clean columns — `speed_mph`, `lanes_total`, `has_bike_facility` — using this priority order: DDOT (`dc_*`) first for speed and lanes, OSM (`osm_*`) first for bike facility, falling back to the other source when the primary is null. `has_bike_facility` should be `True` if *any* relevant `osm_cycleway*` or `dc_BIKELANE_*` column indicates presence — not just one specific subtype.

**b) Watch for:** Normalize formats *before* merging, not after. `osm_maxspeed` may be text like `"25 mph"` while `dc_SPEEDLIMITS_OB` may already be numeric — parse/strip units and cast both to the same numeric type first, or a naive `combine_first` will leave you with a mixed-type mess. Explicitly document that null-after-merge is being treated as "no bike facility" (per Step 1).

**c) Why:** This is the fallback logic we discussed — DDOT is more complete for speed/lanes, OSM is more complete for bike facilities, so each attribute tries its stronger source first.

---

## Step 3 — Stress classification (`base_stress_class`)

**a) Do:** Implement a 3-tier rule:
- **Low:** `speed_mph <= 25` AND `has_bike_facility`
- **High:** `speed_mph >= 35` OR (`lanes_total >= 3` AND NOT `has_bike_facility`)
- **Medium:** everything else

Print the resulting tier distribution. **Treat this as a first draft to test, not the final rule.** Requiring a bike facility for Low is stricter than standard LTS (which treats quiet ≤25mph, ≤2-lane residential streets as low-stress even with no facility) — if the resulting Low network looks implausibly sparse or dominated by bike-lane segments specifically, switch to `speed_mph <= 25 AND (has_bike_facility OR lanes_total <= 2)` and note in the README which version was used and why.

**b) Watch for:** Segments where `speed_mph` or `lanes_total` are still null even after the Step 2 fallback need an explicit decision — don't let a NaN comparison silently fall through into "Medium" by accident. Classify these explicitly as `Unknown` in `base_stress_class` (this column isn't constrained by the output spec, so `Unknown` is fine here) — but since the final `connectivity_lts` column is spec-limited to 4 values, map `Unknown` segments to `Medium` there as the conservative default, and report the exact count of affected segments in the README.

**c) Why:** This is your own transparent, justified metric — exactly what the challenge doc invites in 4.2 ("choose the attributes, decide how to combine them, justify each choice"). Simple and defensible beats clever and opaque here.

---

## Step 4 — Directed graph construction

**a) Do:** Build an `nx.DiGraph`. For each segment, add the edge `u → v`. If the segment is NOT one-way (or one-way status is null — see below), also add `v → u`. If it IS one-way but has a bicycle contraflow exemption (`osm_oneway_bicycle` or `dc_BIKELANE_CONTRAFLOW`), also add `v → u`. Use `dc_SUMMARYDIRECTION` as a fallback/cross-check when `osm_oneway` is null.

**b) Watch for:**
- **Verify the direction convention before trusting it broadly.** Don't assume `osm_oneway=True` means `u → v` is the allowed direction — spot-check one real, known one-way DC street against the data to confirm which way the convention actually runs. Concretely: pull that street's row, note its geometry's first and last coordinates (these correspond to `u` and `v` in order), and check whether that implied direction matches the street's real, known one-way restriction. If it matches, `u → v` is the allowed direction for `oneway=True` rows; if it's reversed, flip the logic to `v → u` instead.
- **A second, independent check that needs no specific street knowledge:** after Step 5, look at whether the strongly-connected-components result looks plausible — e.g., does the dense downtown grid mostly form one connected mass, or does it look implausibly shattered? A convention backwards from reality tends to produce suspiciously over-fragmented results, which is a useful red flag even before hand-verifying a single street.
- **Decide what a null `osm_oneway` should default to.** Treating it as bidirectional (two-way) is the conservative choice — it won't wrongly cut off a street that actually allows both directions — but it's a modeling assumption, so name it in the README.
- A plain `DiGraph` (not `MultiDiGraph`) is sufficient here — for pure connectivity, you only need to know *whether* a path exists between two nodes, not how many parallel ways there are to make it. **This is only safe if classification (Step 3) happens per physical segment, keyed by its own `(u, v, osm_key)`, before any collapsing.** `osm_key` exists to distinguish genuinely separate physical segments sharing the same two nodes — the clearest case being a street and its adjacent cycle track (the exact scenario the challenge doc warns about). If one is High-stress and the other Low-stress, collapsing them into one graph edge *before* classification would force picking one and losing the other. Classify first, filter to Low-stress rows, *then* build the subgraph — at that point, collapsing two parallel edges that both happen to be Low-stress is harmless.

**c) Why:** This is the fix for the one-way mistake from earlier — cyclists have to obey one-way restrictions like anyone else, except where a contraflow lane specifically exempts them. An undirected graph would have silently ignored this.

---

## Step 5 — Low-stress subgraph and strongly connected components

**a) Do:** Build the subgraph containing only edges where `base_stress_class == "Low"`. Run `nx.strongly_connected_components` on it. Assign each node a component ID, then assign each edge the component ID shared by its endpoints.

**b) Watch for:** `strongly_connected_components` operates on *nodes*, not edges — you'll need to map node-level components back to edges (an edge's component is whichever component both its endpoints share, since within one SCC they're always the same). Ignore components made up of nodes with no Low-stress edges at all — they're not meaningful here. Decide now whether "component size" counts edges or physical street segments (see Step 6 — this matters more than it looks).

**A one-way edge can have endpoints in two *different* SCCs** (no path back from `v` to `u` through the Low-stress subgraph at all) — in that case there's no single shared component to assign. Treat that edge as not-strongly-connected rather than forcing it into either endpoint's component: the whole reason for using strong connectivity instead of weak was to make "connected" mean genuine round-trip reachability, and assigning these edges to a component anyway would quietly undo that. Concretely (see Step 6): give it a component of size 1 — its own physical segment — rather than `NaN`; this is the same treatment `strongly_connected_components` already gives any truly isolated node by default, just applied consistently to this case too.

**c) Why:** Strongly connected components answer "can you get from any point in this component to any other point and back, respecting one-way restrictions" — the correct formal tool for "is this low-stress street actually part of a usable network," not an approximation of it.

---

## Step 6 — Connectivity feature and island flag

**a) Do:** For every Low-stress edge, attach `component_size_segments` and `component_size_m` (reproject geometry to EPSG:26985 first for accurate length in meters). Define `is_isolated` primarily by **length** (e.g., `component_size_m < 500`), not segment count — 2-3 very short segments are practically just as isolated as a single long one, so a pure count-based cutoff would under-flag that case. Use segment count as a secondary/supporting number to report, not the primary definition.

**The 500m cutoff is provisional.** What counts as a "large" SCC is to be redefined once we've actually looked at the Low subgraph and the distribution of its SCC sizes (in the coding session, after Step 5) — the value is a placeholder, and it applies both here and to the Step 7 bridge test. Whatever final value is chosen goes in the README with the reasoning.

**Cross-edges are always `is_isolated = True`, regardless of length.** A one-way edge whose endpoints sit in different SCCs (Step 5) is flagged isolated even if its own physical length exceeds the cutoff — otherwise a single long cross-edge would pass the length test and come out `Low-Connected`, contradicting the strong-connectivity definition. The length cutoff only decides the *non*-cross-edge cases.

**b) Watch for — this is the single easiest thing to get subtly wrong in the whole plan:** because Step 4 built a *directed* graph, a two-way street is represented as **two edges** (`u→v` and `v→u`) for what is physically **one segment**. If you sum edge count or edge length directly, every two-way street gets double-counted — e.g., a real 120m two-way street becomes two 120m edges in the same component, summing to a phantom 240m. Dedupe to physical segments before summing — group by `(u, v, osm_key)` with direction ignored (i.e., `(u,v,key)` and `(v,u,key)` refer to the same physical segment), **not** by the unordered node pair alone — `osm_key` matters here because a street and its parallel cycle track can share the same `{u,v}` while being genuinely different physical segments that must stay separate, not merged.

**Check this assumption before writing the dedup logic, not after:** the above assumes each physical street is a single row in the raw snapshot, with Step 4 synthesizing both directed edges from it. Confirm that's actually true — filter the snapshot to a street you know is two-way and see whether it appears as one row or two. If it's already two rows (one per direction, each with its own `osm_id`), the dedup key needs to be something else (e.g., matching geometry, or `{u,v}` is still fine but `osm_id` is not).

**One rule covers every Low-stress segment, including both isolation cases from Step 5** (a segment with no Low-stress neighbors at all, and a one-way edge whose endpoints land in different SCCs): give it `component_size_segments = 1` and `component_size_m` equal to its own physical length — never `NaN`. `NaN` is reserved strictly for Medium/High segments, which were never part of this subgraph at all. A quick way to catch a dedup mistake: construct one tiny synthetic two-node example by hand (one 120m two-way segment) and confirm your component-size calculation returns 120, not 240, before running it on the real data.

**c) Why:** This produces the actual evidence behind your headline demo number — "X% of segments individually classified Low-stress are functionally isolated."

---

## Step 7 — Final combined classification (`connectivity_lts`)

**a) Do:** Combine `base_stress_class` and `is_isolated` into the final column: `High` and `Medium` pass through unchanged; `Low` splits into `Low-Isolated` or `Low-Connected` based on `is_isolated`.

**b) Watch for:** Make sure Medium/High rows are copied through untouched, not accidentally recomputed. Keep `base_stress_class` as its own column in the final output — don't discard it, since the comparison between it and `connectivity_lts` *is* the finding.

**c) Why:** This is the "before vs. after" number for your demo slide — how many segments the naive classification calls Low-stress, versus how many of those are actually well-connected once you account for the network.

**Optional enhancement — build only after the baseline above works:** keep `connectivity_lts` strict (a bridge edge stays `Low-Isolated`, full stop — no exceptions baked into the primary label), and instead add a diagnostic column `is_one_way_bridge`: for a cross-edge `(u,v)` whose endpoints sit in different SCCs, set this `True` if **both** `SCC(u)`'s and `SCC(v)`'s total length individually clear the "large" cutoff (500m as a placeholder — see Step 6; use AND, not OR — requiring both sides to be substantial is the more defensible version than crediting a singleton-to-huge-network edge). Compute each SCC's length with the same physical-segment dedup as Step 6, so two-way streets aren't double-counted. A node with no other Low edges is its own singleton SCC (length 0), so a cross-edge into a dead end correctly fails the test. Every row that isn't a qualifying bridge — including all Medium/High rows and all non-cross-edges — gets `False`, not `NaN`. This only looks at the two direct endpoints' own SCCs, not multi-hop chains of bridges (that's Goal 2's territory). This keeps the primary metric's definition completely clean while still letting the demo report the richer story: "`Low-Isolated` splits into genuine dead ends and one-way bridges into large networks — here's how many of each." State the exact rule in the README.

---

## Step 8 — Visualization

**a) Do:** Plot the street network colored by `connectivity_lts` (4 categories) using `geopandas.plot()`. If time allows, a second plot showing just the Low-stress subgraph colored by component size is worth having — the "mainland vs. scattered islands" pattern is the single most persuasive visual for the demo.

**b) Watch for:** Use a qualitative/categorical colormap, not a sequential one — this is categorical data. Make sure the legend clearly labels all 4 categories, since `Low-Isolated` vs `Low-Connected` is the whole point and needs to read clearly at a glance from across a room.

**c) Why:** The map carries the finding without anyone needing to read a table — this is likely your strongest single piece of evidence for the 4:15 demo.

---

## Step 9 — Export results, write README, assemble submission folder

**a) Do:** Create `notebooks/low-stress-fragmentation/` containing the notebook, `results.parquet` (columns: `osm_u`, `osm_v`, `osm_key`, `snapshot_date`, `connectivity_lts`, `base_stress_class`, `component_size_segments`, `component_size_m`, `is_isolated`, `is_one_way_bridge`), and `README.md`.

**b) Watch for:** Confirm the output has exactly one row per original snapshot segment — compare `len(results)` to the snapshot's segment count as a final check, nothing silently dropped or duplicated anywhere upstream.

The README must cover, per the submission spec:
- **What it produces, its scale, and which direction is safer.** State the ordering explicitly, and call out the nuance: `Low-Isolated` is individually low-stress by its own attributes but may require crossing higher-stress streets to reach — don't let it read as straightforwardly better than `Medium`.
- **Which inputs it uses** — the snapshot columns listed above, snapshot date, nothing else (no crash data, no existing pipeline scores).
- **Known gaps and assumptions**, gathered from every step above: null bike-facility treated as absent (Step 1), null one-way treated as bidirectional (Step 4), classification thresholds are a first draft tuned by eye rather than validated (Step 3), any segments left `Unknown` for missing attributes (Step 3), that this is a snapshot-only analysis with no crash or official LTS/BNA comparison attempted, and that **`Low-Isolated` measures round-trip reachability specifically** — a one-way segment that's the sole connector between two large, well-connected Low-stress networks gets the same `Low-Isolated` label as a true dead-end, since it fails the round-trip test either way. This is a deliberate consequence of using strong (not weak) connectivity, not an oversight. Point to the `is_one_way_bridge` diagnostic here (if built) and report how many `Low-Isolated` segments are genuine dead ends versus bridges, along with the final "large" cutoff chosen and why.

**c) Why:** This is the "What to hand in" checklist from the submission page, turned into concrete deliverables — and the README is what a reviewer reads to decide whether to trust the result at all.