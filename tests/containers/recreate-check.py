"""Recreate only SINEGOR upstreams, forcing IP changes; keep the proxy unchanged."""

import json
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT = "sinegor-vi0-20261111"
ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / "storage/vi0-20261112"
COMPOSE = [
    "docker",
    "compose",
    "-p",
    PROJECT,
    "--env-file",
    str(ROOT / "storage/vi0-20261111/compose.env"),
    "-f",
    str(ROOT / "infra/compose/production.yaml"),
    "-f",
    str(ROOT / "infra/compose/production.local.yaml"),
]
NETWORK = PROJECT + "_application"


def inspect(service):
    obj = json.loads(
        subprocess.check_output(["docker", "inspect", PROJECT + "-" + service + "-1"])
    )[0]
    assert obj["Config"]["Labels"]["com.docker.compose.project"] == PROJECT
    return obj


def ready(path):
    client = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl._create_unverified_context()),
    )
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            with client.open("https://localhost:18443" + path, timeout=5) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.5)
    raise AssertionError("Proxy did not recover after upstream IP change")


proxy_id = inspect("proxy")["Id"]
results = []
for service in ("api", "cms", "web"):
    old = inspect(service)
    old_ip = old["NetworkSettings"]["Networks"][NETWORK]["IPAddress"]
    reserve = PROJECT + "-reserve-" + service
    reserved = False
    try:
        with (PRIVATE / f"recreate-{service}.log").open("wb") as log:
            subprocess.run(
                [*COMPOSE, "rm", "--stop", "--force", service], check=True, stdout=log, stderr=log
            )
            subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    reserve,
                    "--label",
                    "sinegor.container-check=" + PROJECT,
                    "--network",
                    NETWORK,
                    "--ip",
                    old_ip,
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges:true",
                    "--read-only",
                    "python:3.12.12-slim-bookworm",
                    "python",
                    "-c",
                    "import time; time.sleep(240)",
                ],
                check=True,
                stdout=log,
                stderr=log,
            )
            reserved = True
            subprocess.run(
                [
                    *COMPOSE,
                    "up",
                    "-d",
                    "--no-deps",
                    "--no-build",
                    "--pull",
                    "never",
                    "--wait",
                    "--wait-timeout",
                    "180",
                    service,
                ],
                check=True,
                stdout=log,
                stderr=log,
            )
        new = inspect(service)
        new_ip = new["NetworkSettings"]["Networks"][NETWORK]["IPAddress"]
        assert new_ip != old_ip
        assert new["Id"] != old["Id"]
        ready("/api/health/ready" if service == "api" else "/")
        assert inspect("proxy")["Id"] == proxy_id
        results.append(
            {
                "service": service,
                "ip_changed": True,
                "proxy_unchanged": True,
                "request_recovered": True,
            }
        )
        print(f"PASS: {service} recreated at a different IP; unchanged proxy recovered", flush=True)
    finally:
        if reserved:
            helper = json.loads(subprocess.check_output(["docker", "inspect", reserve]))[0]
            assert helper["Config"]["Labels"]["sinegor.container-check"] == PROJECT
            subprocess.run(["docker", "rm", "-f", reserve], check=True, stdout=subprocess.DEVNULL)
(PRIVATE / "recreate-result.json").write_text(json.dumps(results, indent=2) + "\n")
