"""Launch unchanged FastAPI; route only external providers to local TLS fixtures."""

import ipaddress
import os
import socket
import sys
from pathlib import Path

from configuration import load_config


def isolated_lookup(real_lookup, external_port):
    def lookup(host, port, *args, **kwargs):
        if host in {"cloud-api.yandex.net", "api.telegram.org"}:
            return real_lookup("127.0.0.1", external_port, *args, **kwargs)
        local = host in {None, "localhost"}
        if not local:
            try:
                local = ipaddress.ip_address(host).is_loopback
            except ValueError:
                local = False
        if not local:
            raise socket.gaierror(socket.EAI_NONAME, "External E2E networking is disabled")
        return real_lookup(host, port, *args, **kwargs)

    return lookup


def main():
    config = load_config()
    os.environ.update(config["api_env"])
    sys.path.insert(0, str(Path(config["workspace"]) / "apps/api/src"))
    socket.getaddrinfo = isolated_lookup(socket.getaddrinfo, config["ports"]["external"])
    if len(sys.argv) == 3 and sys.argv[1] == "--job":
        if sys.argv[2] not in {"process_orders", "process_notifications"}:
            raise RuntimeError("Unsupported E2E job")
        import runpy

        runpy.run_module("sinegor.jobs." + sys.argv[2], run_name="__main__")
        return
    import uvicorn

    uvicorn.run(
        "sinegor.main:create_app",
        factory=True,
        host="127.0.0.1",
        port=config["ports"]["api"],
        access_log=False,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
