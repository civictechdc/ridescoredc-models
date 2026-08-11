# notebooks/ — this folder is for you

If you are new here, start with
[docs/getting-started-as-a-modeler.md](../docs/getting-started-as-a-modeler.md),
then come back.

Every model in the project lives here, **one folder per model**. That is the
whole convention.

```
notebooks/
├── model-template.ipynb    copy this to start a new model
├── BaseData/               the shared road network — read this first
├── LTS/                    level of traffic stress
├── RideScore/              the published score the live map serves
├── BNA/                    Bicycle Network Analysis
├── Bikeability/            a newer candidate score
└── archive/                the original monolith, kept as a reference
```

## Reading order

1. **`BaseData/`** — what a road segment actually is in this project, which
   attributes it carries, and where they are missing. Every model starts from
   the same segments, so this is shared ground.
2. **The model closest to your idea.** Copying a neighbour is a good way to
   start.
3. **`model-template.ipynb`** when you are ready to write your own.

## Adding your model

Make a new folder, named for the model — descriptive, because the folder name
becomes what people call it in conversation.

```
notebooks/YourModelName/
├── README.md         what it claims, what you validated, what you are unsure about
├── 01_....ipynb      numbered, so the reading order is obvious
└── scratch/          personal working files; gitignored
```

Work on a feature branch (`git checkout -b feature/your-model-name`), open a
pull request into `develop`, and post it in the `#ridescore-dc` channel of the
CivicTechDC Slack.

## Two conventions worth honouring

**Load from `BaseData/`; do not fetch your own copy.** If two models fetch
independently, nobody can tell whether a difference in scores came from the
idea or from the inputs.

**Keep your parameters in one cell and your rule in one pure function.** This
is what lets a model be *promoted* into
[`tools/ridescore-cli/`](../tools/ridescore-cli/) by copying rather than
rewriting, if the group adopts it. Reimplementation is where scores quietly
change.

`notebooks/archive/data_processing.ipynb` is what happens without those two
rules — it works, it built the live map, and porting it has required
reproducing six separate bugs on purpose just to prove the port was faithful.
