# BNA — Bicycle Network Analysis

**Empty — open for someone to take on.**

BNA is [PeopleForBikes'](https://cityratings.peopleforbikes.org/) methodology,
and it asks a fundamentally different question from the one we currently ask.

## Why it is interesting here

Our published score rates **segments in isolation**: how stressful is this
block? BNA rates **the network**: from where people live, how many
destinations — schools, shops, jobs, parks — can be reached on low-stress
streets *without ever crossing a high-stress one*?

That difference matters. A protected lane that ends at a six-lane arterial
scores well segment-by-segment and is useless in practice. Connectivity is
what a rider actually experiences, and no model in this repository captures it
yet.

BNA also builds on low-stress classification, so it consumes something very
close to our [LTS](../LTS/) output — the stress work is already done.

## What taking this on would involve

- Destination data — schools, supermarkets, parks, employment. Open Data DC
  publishes several of these.
- Census blocks for population weighting.
- A routing graph over the segments, filtered to low-stress edges. Our segments
  are blocks, not a topologically connected graph, so building the connectivity
  is real work and probably the hard part.

## Start here

Read [`../BaseData/`](../BaseData/) and [`../LTS/`](../LTS/) first, copy
[`../model-template.ipynb`](../model-template.ipynb), and say hello in
`#ridescore-dc` before you begin — this is a large enough piece that it is
worth coordinating.
