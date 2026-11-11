"""The scheduler has its own health, independent of HTTP and database readiness."""

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest


def checker():
    path = Path(__file__).resolve().parents[4] / "infra/scheduler/check_notifications.py"
    spec = importlib.util.spec_from_file_location("notification_scheduler_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def state(**changes):
    values = {
        "LoadState": "loaded",
        "ActiveState": "inactive",
        "Result": "success",
        "ExecMainStatus": "0",
        "ExecMainStartTimestampMonotonic": "900000000",
        "ExecMainExitTimestampMonotonic": "950000000",
    }
    return values | changes


def test_recent_success_is_healthy():
    result = checker().evaluate(
        {"LoadState": "loaded", "ActiveState": "active"},
        state(),
        now=1000,
        max_age=180,
    )
    assert result["status"] == "ok"
    assert result["age_seconds"] == 50


@pytest.mark.parametrize(
    "timer,service,reason",
    [
        ({"ActiveState": "inactive"}, state(), "timer_inactive"),
        ({"ActiveState": "active"}, state(Result="exit-code", ExecMainStatus="1"), "run_failed"),
        ({"ActiveState": "active"}, state(ExecMainExitTimestampMonotonic="0"), "never_completed"),
        ({"ActiveState": "active"}, state(ExecMainExitTimestampMonotonic="1000000"), "run_stale"),
        (
            {"ActiveState": "active"},
            state(ActiveState="activating", ExecMainStartTimestampMonotonic="1000000"),
            "run_stuck",
        ),
        ({"LoadState": "not-found", "ActiveState": "active"}, state(), "unit_missing"),
    ],
)
def test_scheduler_failure_is_detected(timer, service, reason):
    result = checker().evaluate(timer, service, now=1000, max_age=180)
    assert result["status"] == "critical"
    assert result["reason"] == reason


def test_in_progress_run_has_bounded_grace():
    result = checker().evaluate(
        {"ActiveState": "active"},
        state(ActiveState="activating", ExecMainExitTimestampMonotonic="0"),
        now=1000,
        max_age=180,
    )
    assert result["status"] == "ok"
    assert result["reason"] == "running"


@pytest.mark.parametrize("timer_active", [True, False])
def test_command_exit_and_json_using_systemctl_boundary(tmp_path, timer_active):
    systemctl = tmp_path / "systemctl"
    timer = {"LoadState": "loaded", "ActiveState": "active" if timer_active else "inactive"}
    service = state(ExecMainExitTimestampMonotonic=str(int(time.monotonic() * 1_000_000)))
    systemctl.write_text(
        f"#!{sys.executable}\nimport sys\n"
        f"values = {timer!r} if sys.argv[2].endswith('.timer') else {service!r}\n"
        "print('\\n'.join(key+'='+value for key,value in values.items()))\n"
    )
    systemctl.chmod(0o755)
    path = Path(__file__).resolve().parents[4] / "infra/scheduler/check_notifications.py"
    result = subprocess.run(
        [sys.executable, str(path)],
        env={"PATH": str(tmp_path)},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == (0 if timer_active else 1)
    payload = json.loads(result.stdout if timer_active else result.stderr)
    assert payload["status"] == ("ok" if timer_active else "critical")


def test_systemctl_unavailable_is_reported_without_traceback(tmp_path):
    path = Path(__file__).resolve().parents[4] / "infra/scheduler/check_notifications.py"
    result = subprocess.run(
        [sys.executable, str(path)],
        env={"PATH": str(tmp_path)},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    assert json.loads(result.stderr)["reason"] == "systemd_unavailable"
    assert "Traceback" not in result.stderr
