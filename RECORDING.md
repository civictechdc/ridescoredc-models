# The screen recording

A 3:20 walkthrough: the map first, then the manifest that produced it, then the
code that draws it. The order is deliberate — nobody cares what the manifest is
until they have seen what it does.

**Captions, not a voice-over.** `captions.srt` carries the on-screen text with
its timings; the bold lines below are the longer form the captions are cut down
from, kept because they say what each shot is *for*. Captions read with the
sound off, which is how most of the team will watch it in Slack, and they are
edited by changing a text file rather than re-recording.

Everything not in bold is what is on screen.

Two windows, arranged before recording starts: a browser on
`http://localhost:8081/demo.html?watch`, and an editor with `presentation.yaml`
and a terminal. Do not switch to a third.

---

## 1 · The map (0:00 – 0:25)

*Browser, freshly loaded. Do not touch anything for the first few seconds.*

> **This is RideScore DC, drawn on this laptop, from public data. Every street
> in the city is coloured by how comfortable it is to cycle on. Underneath,
> census blocks are coloured by a completely different model — PeopleForBikes'
> Bicycle Network Analysis, which scores what each block can reach without using
> high-stress streets.**

*Pan slowly once. Do not zoom yet.*

> **Two models, two geometries, two producers. One map.**

## 2 · What is under the cursor (0:25 – 0:50)

*Hover slowly along a road. The one-line box follows the cursor.*

> **Hovering says what a thing is. Clicking says everything about it.**

*Click a road. The sidebar opens with two sections.*

> **One click, one answer — the street on top, the block it sits on underneath.
> Street, RideScore, traffic stress, speed limit, facility, crashes. Every one of
> those labels, and its units, come from the pipeline. Nothing here was typed
> into the website.**

*Point at the two sections without narrating over it.*

## 3 · Two layers, one geometry (0:50 – 1:05)

*In the left panel, switch RideScore → Traffic stress.*

> **RideScore and traffic stress are two layers over the same road network. The
> map fetches the geometry once, and shows one at a time, because both of them
> colour the same lines.**

*Switch back to RideScore.*

## 4 · The manifest (1:05 – 1:35)

*Browser tab: `localhost:8081/manifest.json`. Scroll to `geographies`, then to
one layer.*

> **The website was told all of that by this file. It has three parts.
> Geographies — what is being scored, and how one of them is identified. Sources
> — where the geometry comes from. Layers — one value, drawn one way.**

*Scroll to the `ridescore_v1` layer, and rest on `value` and `popup`.*

> **A colour scale, a domain, a list of fields with labels and units. This file
> is generated. Half of it comes from a presentation, which says what this
> deployment publishes and how it looks. The other half comes from the dataset
> descriptions, written next to the code that produces each dataset — so what a
> field means is written down once, by the people who know.**

## 5 · The code (1:35 – 2:00)

*Editor: `demo.html`, scrolled to the capability table.*

> **This is everything the frontend knows about the data. Three ways to draw
> something, two ways to deliver it, one kind of colour scale. It does not
> contain the word RideScore, or BNA, or the name of any table or column.**

*Scroll to the boot loop.*

> **It reads the manifest, adds each source once however many layers use it, and
> draws each layer from its declaration. That is the whole frontend.**

## 6 · Adding a layer, live (2:00 – 2:25)

*Editor: `presentation.yaml`. Paste the prepared ten-line block. Save.*

> **BNA publishes more scores than this map draws. Here is one of them —
> recreation: how much park and trail a block can reach.**

*Terminal: `uv run ridescore manifest --to ../website/api/static/manifest.json`.
Cut to the browser, which reloads itself.*

> **Regenerate the manifest, and there it is. A legend, a title, a popup, and a
> scale that runs nought to one rather than nought to a hundred — because the
> description says that is the range of that attribute. No frontend change. No
> rebuild. No deploy.**

## 7 · Publishing ahead of the frontend (2:25 – 2:40)

*Editor: change that layer's `template:` to `hexbin`. Save, regenerate.*

> **And if the pipeline publishes something this website cannot draw, the layer
> is dropped and everything else still works. So the two can be released
> separately — which is the point.**

*Browser: the panel's red line, and the console warning.*

## 8 · The description earns its place (2:40 – 2:55)

*Terminal: `uv run ridescore describe`.*

> **The descriptions are checked against the data. The first time this ran it
> found three places where the pipeline was not producing what it claimed —
> including a field documented as a yes-or-no flag that is actually free text.**

## 9 · Close (2:55 – 3:05)

*Browser, back on the map.*

> **What is not here: the weight sliders, and the endpoint behind a
> selection-driven layer. Both are the next step, and neither needs the frontend
> to change. Everything you have seen runs on one laptop from a three-megabyte
> download.**

---

## Captions

`captions.srt` has 34 cues over 3:20, timed to the shots above. Each is at least
two seconds, at most two lines, and under twenty characters a second, which is
about the limit for reading while also watching a map.

**Record first, then fit the captions to what you actually did** — the timings
here are a plan, not a metronome. Any subtitle editor will nudge them; so will
editing the file by hand.

The map's own furniture is top-left and top-right, so captions sit along the
bottom and cover nothing:

    ffmpeg -i recording.mp4 -vf "subtitles=captions.srt:force_style=\
    'FontName=DejaVu Sans,FontSize=20,PrimaryColour=&H00FFFFFF&,\
    BackColour=&HB0000000&,BorderStyle=4,Alignment=2,MarginV=36'" \
    -c:a copy recording-captioned.mp4

Burning them in rather than shipping a subtitle track is deliberate: Slack,
GitHub and most players show an mp4 inline and ignore a sidecar `.srt`.

A voice-over can be added later without redoing any of this — the bold lines are
the script, and `captions.srt` doubles as the timing sheet.

## Before you record

- `uv run ridescore manifest --to ../website/api/static/manifest.json` once, so
  the starting state is clean.
- Have the recreation layer's ten lines on the clipboard — see PROTOTYPE.md.
- Browser at 100% zoom, console open on a second monitor if you want to show the
  dropped-layer warning, otherwise skip it.
- `git stash` any half-finished edits in the editor; the recording shows real
  files.

## After

Restore `presentation.yaml`:

    git checkout presentation.yaml && uv run ridescore manifest --to ../website/api/static/manifest.json
