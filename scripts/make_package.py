# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Assemble a data package from what `ridescore build` produced.

Provisional. Proposal 0001 A.4 gives this to the CLI as `ridescore bundle` --
though `bundle` there means "a data package", while Proposal 0006 uses "bundle"
for the serving artifact. `ridescore package` would avoid the collision.
Delete this script when that command exists; do not maintain both.

    uv run scripts/make_package.py --out out --version 0.1
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
from pathlib import Path

NAME = "ridescoredc-data-preview"

# Named `-preview` and versioned 0.x on purpose. This data is built on the Open
# Data DC roadway network, which is being replaced by OpenStreetMap. That switch
# changes segment identity, so nothing built now is comparable with what comes
# after it. Keeping the name and 1.0 free means the first OSM package can claim
# them, and it means `geometry_source` on a feedback row reads
# "ridescoredc-data-preview@0.1" -- unmistakably disposable.

DATASETS = ("road_segment", "crashes", "ridescore_v1_scores")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=Path("out"), help="what build wrote")
    p.add_argument("--version", default="0.1")
    p.add_argument("--into", type=Path, default=Path("dist"))
    p.add_argument("--licence", default="CC-BY-4.0")
    args = p.parse_args()

    missing = [d for d in DATASETS if not (args.out / f"{d}.parquet").exists()]
    if missing:
        raise SystemExit(
            f"{args.out} is missing: {', '.join(missing)}. Run `ridescore build` first."
        )
    if not (args.out / "run.json").exists():
        raise SystemExit(f"{args.out}/run.json is missing. Run `ridescore build` first.")

    run = json.loads((args.out / "run.json").read_text())
    commit = (run.get("code") or {}).get("commit") or ""
    if commit.endswith("-dirty"):
        print(f"WARNING: built from a modified tree ({commit}).")
        print("         A published package should come from a clean checkout.")

    target = args.into / f"{NAME}-{args.version}"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    for dataset in DATASETS:
        shutil.copy2(args.out / f"{dataset}.parquet", target / f"{dataset}.parquet")
    shutil.copy2(args.out / "run.json", target / "run.json")

    # Resembles the Data Package standard rather than conforming to it; whether
    # to conform is Proposal 0001 §8's open question. Per-column descriptions
    # are Proposal 0002's and are deliberately absent.
    (target / "datapackage.json").write_text(
        json.dumps(
            {
                "name": NAME,
                "version": args.version,
                "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                "licenses": [{"name": args.licence}],
                "run_date": run.get("run_date"),
                "code": run.get("code"),
                "resources": [
                    {"name": d, "path": f"{d}.parquet", "format": "geoparquet"}
                    for d in DATASETS
                ],
                "notes": (
                    "Preview package built on the Open Data DC roadway network. "
                    "Segment identity does not survive the move to OpenStreetMap, "
                    "so anything keyed to it here is disposable."
                ),
            },
            indent=2,
        )
        + "\n"
    )

    print(f"{target}")
    for f in sorted(target.iterdir()):
        print(f"  {f.name:<32} {f.stat().st_size:>10,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
