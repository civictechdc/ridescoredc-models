#!/usr/bin/env python3
"""
Structural pre-flight checks for live/migrations — no database required.

Runs fast in CI on every PR, BEFORE the DB smoke-apply, to catch the cheap
mistakes that are confusing to debug on a server:

  1. every migration file is named NNNN_<slug>.py or .sql (post-apply.py exempt)
  2. every NNNN_ numeric prefix is unique (no two migrations claim the same slot)

Exit non-zero on any failure. Deeper checks (does it actually apply? does the
baseline load?) are the smoke-apply job's responsibility — those need a live
Postgres.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MIGRATIONS = os.path.join(os.path.dirname(HERE), "live", "migrations")

errors = []
NUM = re.compile(r"^(\d{4})_.+\.(py|sql)$")


def fail(msg):
    errors.append(msg)


def main():
    if not os.path.isdir(MIGRATIONS):
        fail(f"migrations dir not found: {MIGRATIONS}")
        return

    migration_ids = {}
    for name in sorted(os.listdir(MIGRATIONS)):
        path = os.path.join(MIGRATIONS, name)
        if name == "post-apply.py":
            continue  # repeatable hook, intentionally has no NNNN prefix
        if not (os.path.isfile(path) and name.endswith((".py", ".sql"))):
            continue
        m = NUM.match(name)
        if not m:
            fail(f"migration missing NNNN_ prefix: {name}")
            continue
        mid = m.group(1)
        if mid in migration_ids:
            fail(f"duplicate migration number {mid}: {name} and {migration_ids[mid]}")
        migration_ids[mid] = name


if __name__ == "__main__":
    main()
    if errors:
        print(f"FAIL: migration checks failed ({len(errors)}):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)
    print("OK: migration structure checks passed")
