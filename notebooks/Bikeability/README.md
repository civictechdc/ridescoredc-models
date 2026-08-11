# Bikeability

**Empty — a candidate score, not yet started.**

A newer take on the question [RideScore](../RideScore/) currently answers.
Where `ridescore_v1` is a fixed weighted blend of stress, crash history and
facility type, this folder is the place to try something different.

## Things it could do differently

**Rider type.** One score assumes one rider. "Interested but concerned" riders
— the large majority — avoid streets that confident commuters use daily. A
score that produced different answers for different riders would be more
honest than a single average.

**Absolute rather than relative crash normalisation.** The published score
normalises crashes against each run's own 95th percentile, so a street's score
moves when the rest of the city moves. See the note in
[../RideScore/README.md](../RideScore/README.md).

**Exposure.** Crash counts without ridership counts penalise popular routes for
being popular. A street nobody rides has no crashes.

**Uncertainty.** Every score is currently reported as a confident number, even
for segments where most attributes were imputed. Saying so would be useful.

## Relationship to RideScore

This is a **separate candidate**, not a rename of the published score.
`ridescore_v1` stays where it is — the map, the tile function and the website
all depend on that column name. If a model here is adopted, it lands as a new
column beside the old one, and the switch is its own deliberate decision.

## Start here

Copy [`../model-template.ipynb`](../model-template.ipynb), read
[`../RideScore/`](../RideScore/) to know what you are comparing against, and
post in `#ridescore-dc`.
