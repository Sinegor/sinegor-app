"""Bounded read-only host monitoring; no private HTTP data enters output or email."""

import argparse
import copy
import html
import importlib.util
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SERVICES = ("api", "cms", "postgres", "web", "proxy")
STATE = Path("/var/lib/sinegor-monitor")
ORIGIN = "https://sinegor-lab.website"
CMS = "https://cms.sinegor-lab.website"
CRITICAL = {
    "backup_space",
    "disk_critical",
    "inode_critical",
    "tls_invalid",
    "tls_critical",
    "recovery_overdue",
    "restart_loop",
}
GIB = 1024**3


def http_result(kind, status, body, *, title=None):
    if status != (204 if kind == "cms_live" else 200):
        return "http_error"
    if kind == "cms_live":
        return None
    try:
        if kind == "proxy":
            text = body.decode("utf-8")
            valid = (
                "<html" in text
                and "<title>Вход администратора — SINEGOR LAB</title>" in text
                and "Проверка сессии" in text
                and "SINEGOR" in text
                and "</html>" in text
            )
        elif kind == "site":
            text = body.decode("utf-8")
            valid = (
                bool(title)
                and html.escape(title) in text
                and "<h1" in text
                and "public-hero" in text
                and "SINEGOR" in text
                and "</html>" in text
            )
        else:
            value = json.loads(body)
            if kind == "api_ready":
                valid = value == {"status": "ok", "database": "ok"}
            elif kind == "api_live":
                valid = value == {"status": "ok"}
            elif kind == "cms_content":
                content = value.get("data")
                valid = (
                    isinstance(content, dict)
                    and content.get("slug") == "home"
                    and isinstance(content.get("title"), str)
                    and bool(content["title"].strip())
                )
            else:
                valid = False
        return None if valid else "response_invalid"
    except (ValueError, TypeError, AttributeError, UnicodeError):
        return "response_invalid"


def tls_result(days, valid):
    if not valid:
        return "tls_invalid"
    if days <= 7:
        return "tls_critical"
    return "tls_expiring" if days <= 30 else None


def maintenance_allowed(pending, run, backup_active, now):
    return backup_module().controlled_window(pending, run, backup_active, now)


def container_results(items, previous, now, maintenance):
    checks, history = {}, {}
    permanent = [
        v
        for v in items
        if v["Config"]["Labels"].get("com.docker.compose.oneoff", "false").lower()
        != "true"
    ]
    checks["docker.composition"] = (
        None
        if len(permanent) == 5
        and all(
            v["Config"]["Labels"].get("com.docker.compose.service") in SERVICES
            for v in permanent
        )
        else "composition_changed"
    )
    for service in SERVICES:
        found = [
            v
            for v in permanent
            if v["Config"]["Labels"].get("com.docker.compose.service") == service
        ]
        key = "docker." + service
        if len(found) != 1:
            checks[key] = "missing_or_duplicate"
            continue
        item = found[0]
        old = previous.get(service, {})
        changes = [v for v in old.get("changes", []) if 0 <= now - v <= 600]
        if old and (old.get("id"), old.get("started_at")) != (
            item["Id"],
            item["State"]["StartedAt"],
        ):
            changes.append(now)
        count = item.get("RestartCount", 0)
        delta = (
            max(0, count - old.get("restarts", count))
            if old.get("id") == item["Id"]
            else 0
        )
        history[service] = {
            "id": item["Id"],
            "started_at": item["State"]["StartedAt"],
            "restarts": count,
            "changes": changes,
        }
        reason = None
        if item["State"]["Status"] != "running":
            reason = "stopped"
        elif item["State"].get("Health", {}).get("Status") != "healthy":
            reason = "unhealthy"
        if delta >= 3 or len(changes) >= 3:
            reason = "restart_loop"
        if (
            maintenance
            and service in ("api", "cms")
            and reason in ("stopped", "unhealthy")
        ):
            reason = None
        checks[key] = reason
    return checks, history


def normalize_results(results, maintenance):
    results = results | {"monitor.collect": None}
    if maintenance:
        for key in (
            "docker.api",
            "docker.cms",
            "http.site",
            "http.api_live",
            "http.api_ready",
            "http.cms_live",
            "http.cms_ready",
        ):
            if results.get(key) not in (
                "missing_or_duplicate",
                "restart_loop",
                "tls_invalid",
            ):
                results.pop(key, None)
    return results


def disk_capacity(free, inodes, available_inodes):
    if available_inodes < max(1024, inodes * 0.01):
        return "inode_critical"
    if free < 5 * GIB:
        return "disk_critical"
    return None


def disk_result(free, inodes, available_inodes, database_bytes, file_bytes):
    payload = max(256 * 1024**2, file_bytes + 2 * database_bytes + 64 * 1024**2)
    required = 5 * GIB + 4 * payload + 2 * database_bytes
    metrics = {
        "available": free,
        "required_free": required,
        "payload_budget": payload,
        "database_bytes": database_bytes,
        "file_bytes": file_bytes,
        "inodes": inodes,
        "available_inodes": available_inodes,
    }
    capacity = disk_capacity(free, inodes, available_inodes)
    if capacity:
        return capacity, metrics
    if free < required:
        return "backup_space", metrics
    if free < required + 2 * GIB or available_inodes < inodes * 0.05:
        return "capacity_warning", metrics
    return None, metrics


def transition(previous, results, now, notify, persist):
    state = copy.deepcopy(previous)
    state.update(checked_at=now, version=1)
    checks = state.setdefault("checks", {})
    for key, reason in results.items():
        if not re.fullmatch(r"[a-z][a-z0-9_.]{1,60}", key):
            raise ValueError("Invalid check identifier")
        entry = checks.setdefault(
            key,
            {
                "failures": 0,
                "successes": 0,
                "active": False,
                "notified": False,
                "pending": None,
                "last_attempt": 0,
                "last_sent": 0,
            },
        )
        entry["reason"] = reason
        if reason is not None:
            if entry["pending"] == "recovered":
                entry["pending"] = None
            entry["failures"] += 1
            entry["successes"] = 0
            if entry["failures"] >= (1 if reason in CRITICAL else 3):
                if not entry["active"]:
                    entry.update(active=True, pending="down", last_attempt=0)
                elif entry["notified"] and now - entry["last_sent"] >= 21600:
                    entry["pending"] = "down"
        else:
            entry["failures"] = 0
            entry["successes"] += 1
            if entry["successes"] >= 2:
                if entry["active"]:
                    entry.update(
                        active=False,
                        pending="recovered" if entry["notified"] else None,
                        last_attempt=0,
                    )
                elif entry["notified"]:
                    if entry["pending"] != "recovered":
                        entry.update(pending="recovered", last_attempt=0)
                else:
                    entry["pending"] = None
    persist(state)
    for key in results:
        entry = checks[key]
        if not entry["pending"] or now - entry["last_attempt"] < 300:
            continue
        entry["last_attempt"] = now
        persist(state)
        try:
            accepted = bool(notify("monitor." + key + "." + entry["pending"]))
        except Exception:  # noqa: BLE001 - boundary emits only a closed failure code
            accepted = False
        entry["smtp_accepted"] = accepted
        if accepted:
            entry.update(
                notified=entry["pending"] == "down", last_sent=now, pending=None
            )
        persist(state)
    return state


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def get(url):
    request = urllib.request.Request(
        url, headers={"User-Agent": "SINEGOR-host-monitor/1"}
    )
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(request, timeout=5) as response:
        body = response.read(2 * 1024 * 1024 + 1)
        if len(body) > 2 * 1024 * 1024:
            raise ValueError("Response too large")
        return response.status, body


def probe_http(kind, url):
    try:
        title = None
        if kind == "site":
            code, content = get(CMS + "/api/public-content/pages/home")
            if http_result("cms_content", code, content):
                return {"reason": "cms_not_ready"}
            title = json.loads(content)["data"]["title"]
        status, body = get(url)
        return {
            "reason": http_result(kind, status, body, title=title),
            "status": status,
        }
    except ssl.SSLCertVerificationError:
        return {"reason": "tls_invalid"}
    except urllib.error.HTTPError as error:
        error.close()
        return {"reason": "http_error", "status": error.code}
    except Exception:  # noqa: BLE001 - boundary emits only a closed failure code
        return {"reason": "http_unreachable"}


def probe_tls(host):
    try:
        with (
            socket.create_connection((host, 443), timeout=5) as raw,
            ssl.create_default_context().wrap_socket(
                raw, server_hostname=host
            ) as connection,
        ):
            cert = connection.getpeercert()
            days = (ssl.cert_time_to_seconds(cert["notAfter"]) - time.time()) / 86400
            return {
                "reason": tls_result(days, True),
                "remaining_days": round(days, 2),
            }
    except ssl.SSLCertVerificationError:
        return {"reason": "tls_invalid"}
    except Exception:  # noqa: BLE001 - boundary emits only a closed failure code
        return {"reason": "tls_unreachable"}


def child_probe(args):
    try:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), *args],
            capture_output=True,
            check=False,
            text=True,
            timeout=15,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/root"},
        )
        if result.returncode:
            return {"reason": "probe_failed"}
        return json.loads(result.stdout)
    except Exception:  # noqa: BLE001 - boundary emits only a closed failure code
        return {"reason": "probe_timeout"}


def backup_module():
    directory = Path(__file__).resolve().parents[1] / "backup"
    sys.path.insert(0, str(directory))
    spec = importlib.util.spec_from_file_location(
        "monitor_backup", directory / "production.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def unit(module, name):
    raw = module.command(
        [
            "systemctl",
            "show",
            name,
            "--property=LoadState,ActiveState,UnitFileState,Result,ExecMainStatus,ExecMainStartTimestampMonotonic",
        ],
        timeout=5,
    )
    return dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)


def unit_result(timer, service, max_age):
    if (
        timer.get("LoadState") != "loaded"
        or timer.get("ActiveState") != "active"
        or timer.get("UnitFileState") != "enabled"
    ):
        return "timer_inactive"
    if service.get("LoadState") != "loaded":
        return "service_missing"
    started = int(service.get("ExecMainStartTimestampMonotonic", "0")) / 1e6
    if time.monotonic() - started > max_age:
        return "watchdog_stale"
    return None


def watchdog_result(timer, service, heartbeat, now, max_age):
    reason = unit_result(timer, service, max_age)
    if reason:
        return reason
    try:
        checked = heartbeat["checked_at"]
        if not 0 <= now - checked <= max_age:
            return "watchdog_state_stale"
        started = int(service.get("ExecMainStartTimestampMonotonic", "0")) / 1e6
        start_wall = now - (time.monotonic() - started)
        if service.get("ActiveState") != "activating" and checked < start_wall - 2:
            return "watchdog_failed"
        if service.get("ExecMainStatus", "0") not in ("0", "1"):
            return "watchdog_failed"
        return None
    except (KeyError, TypeError, ValueError):
        return "watchdog_state_missing"


def collect(module, cfg, previous, now):
    results, metrics = {}, {}
    state_root = Path(cfg["state_dir"])

    def read(path):
        return module.read_private(path) if path.exists() else {}

    pending, run = read(state_root / "pending.json"), read(state_root / "last-run.json")
    backup_service = unit(module, "sinegor-backup.service")
    maintenance = maintenance_allowed(
        pending, run, backup_service.get("ActiveState") in ("active", "activating"), now
    )
    raw = module.command(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            "label=com.docker.compose.project=sinegor-lab-prod",
        ],
        timeout=5,
    ).split()
    items = (
        json.loads(module.command(["docker", "inspect", *raw], timeout=5))
        if raw
        else []
    )
    if maintenance:
        for entry in pending["entries"]:
            if not any(
                v["Id"] == entry["id"]
                and v["Image"] == entry["image"]
                and v["Config"]["Labels"].get("com.docker.compose.service")
                == entry["service"]
                for v in items
            ):
                maintenance = False
    results, history = container_results(
        items, previous.get("containers", {}), now, maintenance
    )
    metrics["maintenance"] = maintenance
    results["backup.window"] = (
        "recovery_overdue" if pending and not maintenance else None
    )
    queries = {
        "http.proxy": ["probe-http", "proxy", ORIGIN + "/auth/admin"],
        "http.site": ["probe-http", "site", ORIGIN + "/"],
        "http.api_live": ["probe-http", "api_live", ORIGIN + "/api/health/live"],
        "http.api_ready": ["probe-http", "api_ready", ORIGIN + "/api/health/ready"],
        "http.cms_live": ["probe-http", "cms_live", CMS + "/_health"],
        "http.cms_ready": [
            "probe-http",
            "cms_content",
            CMS + "/api/public-content/pages/home",
        ],
        "tls.site": ["probe-tls", "sinegor-lab.website"],
        "tls.cms": ["probe-tls", "cms.sinegor-lab.website"],
    }
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {key: pool.submit(child_probe, args) for key, args in queries.items()}
        for key, future in futures.items():
            value = future.result()
            results[key] = value["reason"]
            metrics[key] = {k: v for k, v in value.items() if k != "reason"}
    fs = os.statvfs(state_root)
    free = fs.f_bavail * fs.f_frsize
    results["disk.root"] = disk_capacity(free, fs.f_files, fs.f_favail)
    metrics["disk"] = {
        "available": free,
        "inodes": fs.f_files,
        "available_inodes": fs.f_favail,
    }
    results["disk.budget"] = None
    try:
        db_bytes = module.Docker(cfg).sql(
            "postgres",
            "SELECT pg_database_size('sinegor') + pg_database_size('sinegor_cms')",
        )
        started, file_bytes = time.monotonic(), 0
        for source in cfg["sources"].values():
            path = Path(source)
            if path.resolve() != path or not path.is_dir():
                raise ValueError("Source unavailable")
            for item in path.rglob("*"):
                if time.monotonic() - started > 8:
                    raise TimeoutError("Measurement timeout")
                if item.is_file():
                    file_bytes += item.lstat().st_size
        results["disk.root"], metrics["disk"] = disk_result(
            free, fs.f_files, fs.f_favail, db_bytes, file_bytes
        )
    except Exception:  # noqa: BLE001 - boundary emits only a closed failure code
        results["disk.budget"] = "measurement_failed"
    results["telemetry.storage"] = None
    try:
        volumes = {}
        for item in items:
            for mount in item.get("Mounts", []):
                if mount["Type"] == "volume":
                    amount = module.command(
                        ["du", "-sx", "-B1", mount["Source"]], timeout=5
                    )
                    volumes[mount["Name"]] = int(amount.split()[0])
        metrics["volume_bytes"] = volumes
        old_volumes = previous.get("metrics", {}).get("volume_bytes", {})
        metrics["volume_growth_bytes"] = {
            key: value - old_volumes.get(key, value) for key, value in volumes.items()
        }
        metrics["container_log_bytes"] = sum(
            Path(v["LogPath"]).stat().st_size for v in items if v.get("LogPath")
        )
        metrics["journal_allocated_bytes"] = int(
            module.command(["du", "-sx", "-B1", "/var/log/journal"], timeout=5).split()[0]
        )
    except Exception:  # noqa: BLE001 - boundary emits only a closed failure code
        results["telemetry.storage"] = "measurement_failed"
    for key, prefix, age in (
        ("backup.watchdog", "sinegor-backup-watchdog", 600),
        ("jobs.watchdog", "sinegor-jobs-watchdog", 180),
    ):
        timer, service = (
            unit(module, prefix + ".timer"),
            unit(module, prefix + ".service"),
        )
        if key == "backup.watchdog":
            results[key] = watchdog_result(
                timer, service, read(state_root / "watchdog-state.json"), now, age
            )
        else:
            results[key] = unit_result(timer, service, age)
        if (
            key == "jobs.watchdog"
            and not maintenance
            and service.get("Result") not in ("success", None)
        ):
            results[key] = "jobs_failed"
    timer = unit(module, "sinegor-backup.timer")
    results["backup.timer"] = (
        None
        if timer.get("ActiveState") == "active"
        and timer.get("UnitFileState") == "enabled"
        else "timer_inactive"
    )
    metrics["containers"] = history
    return normalize_results(results, maintenance), metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("check", "show", "test-alert", "probe-http", "probe-tls")
    )
    parser.add_argument("arguments", nargs="*")
    args = parser.parse_args()
    if args.action == "probe-http":
        print(json.dumps(probe_http(*args.arguments)))
        return 0
    if args.action == "probe-tls":
        print(json.dumps(probe_tls(*args.arguments)))
        return 0
    if os.geteuid() != 0:
        return 2
    os.umask(0o077)
    module = backup_module()
    cfg = module.load_config(Path("/etc/sinegor/backup/config.json"))
    path = STATE / "state.json"
    if args.action == "show":
        print(json.dumps(module.read_private(path)))
        return 0
    if args.action == "test-alert":
        sent = module.notify(
            cfg,
            {
                "event": "monitor.channel_test",
                "stage": "monitor",
                "error_type": "None",
                "run_id": "iii10",
            },
        )
        print(json.dumps({"smtp_accepted": sent}))
        return 0 if sent else 1
    module.private(STATE.stat(), directory=True)
    import fcntl

    fd = os.open(STATE / "run.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        module.private(os.fstat(fd))
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous = module.read_private(path) if path.exists() else {}
        now = time.time()
        try:
            results, metrics = collect(module, cfg, previous, now)
        except Exception:  # noqa: BLE001 - boundary emits only a closed failure code
            results, metrics = {"monitor.collect": "probe_failed"}, {}
        base = previous | {
            "metrics": metrics,
            "containers": metrics.get("containers", previous.get("containers", {})),
        }
        notify = lambda event: module.notify(
            cfg,
            {
                "event": event,
                "stage": "monitor",
                "error_type": "MonitorState",
                "run_id": "monitor",
            },
        )
        state = transition(
            base, results, now, notify, lambda value: module.atomic_json(path, value)
        )
        active = sorted(
            key for key, value in state["checks"].items() if value["active"]
        )
        print(
            json.dumps(
                {
                    "event": "monitor_completed",
                    "active": active,
                    "maintenance": metrics.get("maintenance", False),
                }
            )
        )
        return 0
    finally:
        os.close(fd)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001 - top-level output excludes exception text
        print(
            json.dumps({"event": "monitor_failed", "error_type": type(error).__name__})
        )
        raise SystemExit(2)
