"""Read systemd scheduler state only; never import the app or access its queue."""

import argparse
import json
import subprocess
import sys
import time


def evaluate(timer: dict, service: dict, *, now: float, max_age: float) -> dict:
    result = {"status": "critical", "reason": "unit_missing"}
    if any(unit.get("LoadState", "loaded") != "loaded" for unit in (timer, service)):
        return result
    if timer.get("ActiveState") != "active":
        return result | {"reason": "timer_inactive"}
    try:
        started = int(service.get("ExecMainStartTimestampMonotonic", "0")) / 1_000_000
        finished = int(service.get("ExecMainExitTimestampMonotonic", "0")) / 1_000_000
    except ValueError:
        return result | {"reason": "invalid_timestamps"}
    if service.get("ActiveState") in {"active", "activating", "deactivating"}:
        age = now - started
        if started <= 0 or age < 0 or age > max_age:
            return result | {"reason": "run_stuck"}
        return {"status": "ok", "reason": "running", "age_seconds": round(age, 1)}
    if service.get("Result") != "success" or service.get("ExecMainStatus") != "0":
        return result | {"reason": "run_failed"}
    if finished <= 0:
        return result | {"reason": "never_completed"}
    age = now - finished
    result |= {"age_seconds": round(age, 1)}
    if age < 0 or age > max_age:
        return result | {"reason": "run_stale"}
    return result | {"status": "ok", "reason": "completed"}


def properties(unit: str) -> dict:
    response = subprocess.run(
        [
            "systemctl",
            "show",
            unit,
            "--no-pager",
            "--property="
            + ",".join(
                (
                    "LoadState",
                    "ActiveState",
                    "Result",
                    "ExecMainStatus",
                    "ExecMainStartTimestampMonotonic",
                    "ExecMainExitTimestampMonotonic",
                )
            ),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return dict(line.split("=", 1) for line in response.stdout.splitlines() if "=" in line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-age", type=int, default=900, help="Maximum run age in seconds")
    args = parser.parse_args()
    if args.max_age <= 0:
        parser.error("--max-age must be positive")
    try:
        result = evaluate(
            properties("sinegor-notifications.timer"),
            properties("sinegor-notifications.service"),
            now=time.monotonic(),
            max_age=args.max_age,
        )
    except (OSError, subprocess.SubprocessError):
        result = {"status": "critical", "reason": "systemd_unavailable"}
    print(
        json.dumps({"event": "notification_scheduler_check", **result}),
        file=sys.stdout if result["status"] == "ok" else sys.stderr,
    )
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
