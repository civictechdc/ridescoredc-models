# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Assemble a deployment bundle: the SQL that serves a data package.

Kept separate from the data package on purpose. Proposal 0006 §4.1: "The data
package carries no presentation-derived material ... correcting a legend must
never require republishing it." A routine refresh publishes a package and reuses
the deployed bundle; a change to what a tile carries publishes a bundle over the
deployed package.

Provisional: the SQL here is hand-written, and Proposal 0006 has
`ridescore generate` produce it from a package plus a presentation.

    uv run scripts/make_bundle.py --version 0.1 --applies-to 0.1
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
from pathlib import Path

NAME = "ridescoredc-bundle-preview"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--serving", type=Path, default=Path("serving"))
    p.add_argument("--version", default="0.1")
    p.add_argument("--applies-to", default="0.1", help="data package version this serves")
    p.add_argument("--into", type=Path, default=Path("dist"))
    args = p.parse_args()

    sql = sorted(args.serving.glob("*.sql"))
    if not sql:
        raise SystemExit(f"no .sql files in {args.serving}")

    target = args.into / f"{NAME}-{args.version}"
    if target.exists():
        shutil.rmtree(target)
    (target / "serving").mkdir(parents=True)

    for f in sql:
        shutil.copy2(f, target / "serving" / f.name)

    (target / "bundle.json").write_text(
        json.dumps(
            {
                "name": NAME,
                "version": args.version,
                "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                # Proposal 0006 §4.1: a bundle declares which packages it applies
                # to, so a mismatched pair fails loudly instead of half-working.
                "applies_to": {"package": "ridescoredc-data-preview", "version": args.applies_to},
                "serving": [f.name for f in sql],
            },
            indent=2,
        )
        + "\n"
    )

    print(f"{target}")
    for f in sorted(target.rglob("*")):
        if f.is_file():
            print(f"  {f.relative_to(target)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
