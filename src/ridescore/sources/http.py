"""Getting bytes out of the DC open data endpoints.

One function, because there is one thing worth being careful about: the ArcGIS
download endpoints answer **202 with a short JSON placeholder** while they
generate the file, and only then 200 with the data. `requests`' own `ok` is true
for 202, so the obvious code parses the placeholder as if it were the dataset
and reports an empty download as a successful one.
"""

from __future__ import annotations

import time

import requests

from ridescore import config


class FetchError(RuntimeError):
    """A source could not be downloaded. Never a partial or placeholder file."""


def get(url: str, params: dict | None = None) -> bytes:
    """Download one URL, waiting out an ArcGIS 202 and failing loudly otherwise."""
    last = ""
    for attempt in range(config.FETCH_ATTEMPTS):
        try:
            response = requests.get(url, params=params, timeout=config.FETCH_TIMEOUT_S)
        except requests.RequestException as error:  # network, DNS, timeout
            last = f"{type(error).__name__}: {error}"
        else:
            if response.status_code == 200:
                return response.content
            # 202 means "still generating, ask again". Anything else is an error
            # we should not paper over by retrying forever.
            if response.status_code != 202:
                raise FetchError(f"{url} answered {response.status_code}: {response.text[:200]}")
            last = "202 (still generating)"

        if attempt < config.FETCH_ATTEMPTS - 1:
            time.sleep(config.FETCH_RETRY_WAIT_S)

    raise FetchError(f"{url} gave up after {config.FETCH_ATTEMPTS} attempts. Last: {last}")


def get_json(url: str, params: dict | None = None) -> dict:
    import json

    return json.loads(get(url, params))
