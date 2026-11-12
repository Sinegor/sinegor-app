"""Read-only Docker metadata checks for the isolated SINEGOR Compose project."""

import ipaddress
import json
import subprocess

PROJECT = "sinegor-vi0-20261111"


def inspect(kind, name):
    item = json.loads(subprocess.check_output(["docker", kind, "inspect", name]))[0]
    labels = item.get("Labels") if kind == "network" else item["Config"]["Labels"]
    assert labels["com.docker.compose.project"] == PROJECT, "Unexpected project"
    return item


application = inspect("network", PROJECT + "_application")
config = application["IPAM"]["Config"][0]
proxy = inspect("container", PROJECT + "-proxy-1")
fixed = proxy["NetworkSettings"]["Networks"][PROJECT + "_application"]["IPAMConfig"]["IPv4Address"]
assert config.get("IPRange"), "Dynamic IP pool must exclude the static proxy address"
assert ipaddress.ip_address(fixed) in ipaddress.ip_network(config["Subnet"])
assert ipaddress.ip_address(fixed) not in ipaddress.ip_network(config["IPRange"])
print("PASS: proxy static IP is inside subnet and outside dynamic allocation pool")

for service in ("postgres", "api", "cms", "web"):
    container = inspect("container", PROJECT + "-" + service + "-1")
    assert not container["HostConfig"]["PortBindings"], "Internal service publishes ports"
for binding in proxy["HostConfig"]["PortBindings"].values():
    assert all(item["HostIp"] == "127.0.0.1" for item in binding)
for name in ("database", "application", "outbound"):
    assert inspect("network", PROJECT + "_" + name)["Internal"] is True
print("PASS: internal networks stay internal; only proxy ports published on loopback")

for service in ("api", "cms", "web", "proxy"):
    container = inspect("container", PROJECT + "-" + service + "-1")
    assert container["Config"]["User"] not in ("", "root", "0", "0:0")
    assert "ALL" in container["HostConfig"]["CapDrop"]
    assert "no-new-privileges:true" in container["HostConfig"]["SecurityOpt"]
    assert container["HostConfig"]["LogConfig"]["Config"]["max-size"] == "10m"
    assert container["State"]["Health"]["Status"] == "healthy"
assert proxy["HostConfig"]["ReadonlyRootfs"]
print("PASS: apps non-root, capabilities dropped, logs bounded, all services healthy")

postgres = inspect("container", PROJECT + "-postgres-1")
assert postgres["State"]["Health"]["Status"] == "healthy"
database_ip = postgres["NetworkSettings"]["Networks"][PROJECT + "_database"]["IPAddress"]
web = inspect("container", PROJECT + "-web-1")
assert set(web["NetworkSettings"]["Networks"]) == {PROJECT + "_application"}
assert not web["Mounts"]
subprocess.run(
    [
        "docker",
        "exec",
        PROJECT + "-web-1",
        "node",
        "-e",
        "const net=require('net');"
        "const s=net.connect({host:process.argv[1],port:5432});"
        "s.on('connect',()=>{s.destroy();process.exit(3)});"
        "s.on('error',()=>process.exit(0));"
        "s.setTimeout(2000,()=>{s.destroy();process.exit(0)});",
        database_ip,
    ],
    check=True,
)
print("PASS: SSR has no private mounts and cannot connect to PostgreSQL")
