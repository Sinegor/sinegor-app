"""Periodic CLI for disposable E2E only; configuration validation precedes every run."""

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from configuration import load_config


def main():
    config = load_config()
    status_path = Path(config["private"]) / "scheduler-status.json"
    environment = config["api_env"] | {"SINEGOR_E2E_CONFIG": os.environ["SINEGOR_E2E_CONFIG"]}
    while True:
        started = datetime.now(UTC).isoformat()
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("api.py")),
                    "--job",
                    "process_notifications",
                ],
                env=environment,
                check=False,
                timeout=60,
            )
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
        status = {
            "started_at": started,
            "finished_at": datetime.now(UTC).isoformat(),
            "exit_code": code,
        }
        temporary = status_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(status))
        temporary.replace(status_path)
        print(json.dumps({"event": "e2e_scheduler_run", **status}), flush=True)
        time.sleep(2)


if __name__ == "__main__":
    main()
