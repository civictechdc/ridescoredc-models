# archive/

## `data_processing.ipynb`

**The original.** This one notebook built the map that is live today: it
fetches the roads and crashes, normalises the attributes, applies the LTS
rules, joins crashes to segments, computes `ridescore_v1`, and writes the
GeoJSON that was loaded into PostGIS.

It is kept for two reasons, and neither is nostalgia.

**It is the reference output for the port.** Everything in
[`tools/ridescore-cli/`](../../tools/ridescore-cli/) is judged by whether it
reproduces what these 32 cells produce. Until that diff is clean, this notebook
is the specification.

**It is the argument for the conventions in
[`../model-template.ipynb`](../model-template.ipynb).** Read it and you can see
exactly what those conventions are protecting against:

- A single global `gdf` is mutated across 32 cells, so re-running cell 24
  requires cells 1–22 to have already run in this kernel, in order.
- Parameters are scattered — thresholds in cell 6, LTS rules in cell 8, the
  crash buffer in cell 22, the weights in cell 24, more lookups in cell 27,
  render settings in cell 28.
- `date.today()` is read mid-run, so the same notebook produces different data
  every day with no record of which day it was.
- Outputs are written to the current working directory, wherever that happens
  to be.

The port has meant reproducing **six separate bugs on purpose** — each marked
`DEFECT:` in `config.py` — because a port that also fixes things cannot be
verified against the thing it came from.

None of this is a criticism of the notebook. It did its job: it proved the idea
and shipped a working map, which is the whole point of level 1. It just shows
why a model that is going to be maintained eventually needs to leave the
notebook.

## Do not build on this

Start from [`../model-template.ipynb`](../model-template.ipynb) or from an
existing model folder. If you want the logic this notebook contains, import it:

```python
from ridescore import config
from ridescore.models.lts import lts_level
```
