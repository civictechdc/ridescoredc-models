"""
post-apply -- repeatable lane for stateless DB objects (tile functions).

yoyo runs a migration named ``post-apply`` after every successful apply batch.
Functions are re-created with CREATE OR REPLACE, so re-running is safe and the
DB always matches functions/*.sql in git -- no version-suffixed clones drifting
around in the database.
"""

import glob
import os

from yoyo import step

FUNCTIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "functions"
)


def apply_step(conn):
    cur = conn.cursor()
    for path in sorted(glob.glob(os.path.join(FUNCTIONS_DIR, "*.sql"))):
        with open(path, encoding="utf-8") as fh:
            cur.execute(fh.read())
    cur.close()


steps = [step(apply_step)]
