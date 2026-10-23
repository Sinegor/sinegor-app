"""Private run configuration shared only by disposable test processes."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit


def load_config() -> dict:
    path = Path(os.environ["SINEGOR_E2E_CONFIG"])
    config = json.loads(path.read_text())
    run_id = config["run_id"]
    if not re.fullmatch(r"[a-f0-9]{12}", run_id):
        raise RuntimeError("Invalid E2E run identity")
    private = Path(config["private"]).resolve()
    if path.resolve().parent != private or not private.name.startswith("sinegor-e2e-private-"):
        raise RuntimeError("E2E configuration must belong to a private run directory")
    database = urlsplit(config["api_env"]["DATABASE_URL"])
    if (
        database.hostname != "127.0.0.1"
        or database.path != f"/sinegor_e2e_{run_id}_test"
        or config["api_env"]["APP_ENV"] != "test"
    ):
        raise RuntimeError("Refused to use a non-E2E database")
    return config
