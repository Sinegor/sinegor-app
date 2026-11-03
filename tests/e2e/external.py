"""Local SMTP/TLS and HTTPS fixtures for external providers, with a private control channel."""

import asyncio
import base64
import email
import email.policy
import json
import re
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from configuration import load_config


async def main():
    config = load_config()
    settings = config["api_env"]
    state = {
        "smtp_error": False,
        "disk_error": False,
        "telegram_error": False,
        "mail": [],
        "telegram": [],
        "folders": {"disk:/E2E": "e2e-root"},
        "operations": {},
    }
    lock = threading.RLock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, data):
            raw = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self.dispatch()

        def do_POST(self):
            self.dispatch()

        def do_PUT(self):
            self.dispatch()

        def do_DELETE(self):
            self.dispatch()

        def dispatch(self):
            with lock:
                self.handle_locked()

        def handle_locked(self):
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            if self.server.server_port == config["ports"]["control"]:
                if url.path == "/health":
                    return self.reply(200, {"status": "ok"})
                if self.headers.get("X-E2E-Key") != config["control_key"]:
                    return self.reply(403, {})
                if url.path == "/mode" and self.command == "POST":
                    data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                    for key in ("smtp_error", "telegram_error", "disk_error"):
                        if key in data and type(data[key]) is bool:
                            state[key] = data[key]
                    return self.reply(200, {"ok": True})
                if url.path == "/mail" and self.command == "GET":
                    messages = [
                        item for item in state["mail"] if item["to"] == query.get("to", [""])[0]
                    ]
                    return self.reply(
                        200,
                        {
                            "count": len(messages),
                            "link": next(
                                (m["link"] for m in reversed(messages) if m["link"]),
                                None,
                            ),
                            "subjects": [m["subject"] for m in messages],
                        },
                    )
                if url.path == "/telegram" and self.command == "GET":
                    return self.reply(200, {"messages": state["telegram"]})
                return self.reply(404, {})
            host = self.headers.get("Host", "")
            if host == "api.telegram.org":
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                if (
                    url.path != "/botsynthetic-e2e/sendMessage"
                    or data.get("chat_id") != "synthetic-e2e"
                ):
                    return self.reply(401, {"ok": False})
                if not state["telegram_error"]:
                    state["telegram"].append(data.get("text"))
                return self.reply(
                    503 if state["telegram_error"] else 200,
                    {"ok": not state["telegram_error"]},
                )
            if (
                host != "cloud-api.yandex.net"
                or self.headers.get("Authorization") != "OAuth synthetic-e2e"
            ):
                return self.reply(401, {})
            if state["disk_error"]:
                return self.reply(503, {"error": "SyntheticUnavailable"})
            if url.path.startswith("/v1/disk/operations/"):
                return self.reply(
                    200,
                    {"status": state["operations"].get(url.path.split("/")[-1], "failed")},
                )
            if url.path != "/v1/disk/resources":
                return self.reply(404, {})
            path = query.get("path", [""])[0]
            if not (path == "disk:/E2E" or path.startswith("disk:/E2E/")):
                return self.reply(400, {})
            if self.command == "GET":
                if path not in state["folders"]:
                    return self.reply(404, {})
                return self.reply(
                    200,
                    {
                        "path": path,
                        "type": "dir",
                        "resource_id": state["folders"][path],
                    },
                )
            if self.command == "PUT":
                if path in state["folders"]:
                    return self.reply(409, {})
                state["folders"][path] = uuid4().hex
                return self.reply(201, {})
            if self.command == "DELETE" and query.get("permanently") == ["true"]:
                state["folders"].pop(path, None)
                operation = uuid4().hex
                state["operations"][operation] = "success"
                return self.reply(
                    202,
                    {
                        "href": "https://cloud-api.yandex.net/v1/disk/operations/" + operation,
                        "method": "GET",
                    },
                )
            return self.reply(400, {})

    async def smtp(reader, writer):
        async def reply(value):
            writer.write((value + "\r\n").encode())
            await writer.drain()

        authenticated = False
        recipient = ""
        await reply("220 E2E SMTP TLS")
        try:
            while raw := await reader.readline():
                line = raw.decode().strip()
                command = line.split(" ", 1)[0].upper()
                if command in {"EHLO", "HELO"}:
                    await reply("250-E2E\r\n250-AUTH PLAIN\r\n250 SIZE 30000000")
                elif command == "AUTH":
                    parts = line.split()
                    if len(parts) < 3:
                        await reply("334 ")
                        parts.append((await reader.readline()).decode().strip())
                    credentials = base64.b64decode(parts[-1]).split(b"\x00")
                    authenticated = credentials[-2:] == [
                        settings["SMTP_USERNAME"].encode(),
                        settings["SMTP_PASSWORD"].encode(),
                    ]
                    await reply("235 Authenticated" if authenticated else "535 Invalid credentials")
                elif not authenticated:
                    await reply("530 Authenticate first")
                elif command == "RCPT":
                    recipient = line.split(":", 1)[1].strip("<>")
                    await reply("250 OK" if recipient.endswith("@example.org") else "550 Test only")
                elif command == "DATA":
                    if state["smtp_error"]:
                        await reply("451 Synthetic SMTP unavailable")
                        continue
                    await reply("354 End with dot")
                    body = bytearray()
                    while (part := await reader.readline()) != b".\r\n":
                        if not part:
                            break
                        body.extend(part)
                    message = email.message_from_bytes(bytes(body), policy=email.policy.default)
                    match = re.search(
                        re.escape(config["origin"]) + r"/auth/magic-link#token=[\w-]+",
                        message.get_content(),
                    )
                    with lock:
                        state["mail"].append(
                            {
                                "to": recipient,
                                "subject": str(message["Subject"]),
                                "link": match[0] if match else None,
                            }
                        )
                    await reply("250 Accepted")
                elif command == "QUIT":
                    await reply("221 Bye")
                    break
                else:
                    await reply("250 OK")
        except (ConnectionError, ValueError, UnicodeError):
            pass
        finally:
            writer.close()

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    private = Path(config["private"])
    context.load_cert_chain(private / "tls.crt", private / "tls.key")
    external = ThreadingHTTPServer(("127.0.0.1", config["ports"]["external"]), Handler)
    external.socket = context.wrap_socket(external.socket, server_side=True)
    control = ThreadingHTTPServer(("127.0.0.1", config["ports"]["control"]), Handler)
    for server in (external, control):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    server = await asyncio.start_server(smtp, "127.0.0.1", config["ports"]["smtp"], ssl=context)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
