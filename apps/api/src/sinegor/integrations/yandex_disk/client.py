"""Small server-only REST adapter. No uploads, publishing, permissions or trash purge."""

import json
import re
from dataclasses import dataclass
from http.client import HTTPException, HTTPSConnection
from typing import Protocol
from urllib.parse import urlencode, urlsplit

from sinegor.core.config import Settings
from sinegor.integrations.yandex_disk.paths import canonical_path, child_path

HOST = "cloud-api.yandex.net"
BASE = "/v1/disk"
OPERATION = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


class DiskError(Exception):
    """Safe service message; never includes the upstream response or credentials."""


class DiskConflict(DiskError):
    pass


@dataclass(frozen=True)
class Resource:
    path: str
    resource_id: str


@dataclass(frozen=True)
class Reply:
    status: int
    body: bytes = b""


class Transport(Protocol):
    def __call__(self, method: str, target: str, token: str, timeout: int) -> Reply: ...


def https_request(method: str, target: str, token: str, timeout: int) -> Reply:
    connection = HTTPSConnection(HOST, timeout=timeout)
    try:
        connection.request(method, target, headers={"Authorization": "OAuth " + token})
        response = connection.getresponse()
        body = response.read(65537)
        if len(body) > 65536:
            raise DiskError("Invalid Disk response")
        return Reply(response.status, body)
    except (OSError, HTTPException, ValueError):
        raise DiskError("Disk service unavailable") from None
    finally:
        connection.close()


class YandexDisk:
    def __init__(self, settings: Settings, transport: Transport = https_request):
        self.root = settings.yandex_disk_root
        self._token = settings.yandex_disk_token
        self._timeout = settings.yandex_disk_timeout
        self._transport = transport

    def path(self, path: str) -> str:
        if not self.root or not self._token:
            raise DiskError("Disk integration is not configured")
        try:
            return child_path(path, self.root)
        except ValueError:
            raise DiskConflict("Invalid order folder path") from None

    def _request(self, method: str, endpoint: str, **params) -> Reply:
        if not self.root or not self._token:
            raise DiskError("Disk integration is not configured")
        target = BASE + endpoint
        if params:
            target += "?" + urlencode(params)
        try:
            result = self._transport(method, target, self._token.get_secret_value(), self._timeout)
        except DiskError:
            raise
        except Exception:
            raise DiskError("Disk service unavailable") from None
        if result.status not in {200, 201, 202, 204, 404, 409}:
            raise DiskError("Disk request failed")
        return result

    @staticmethod
    def _json(reply: Reply) -> dict:
        try:
            result = json.loads(reply.body)
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (ValueError, UnicodeError):
            raise DiskError("Invalid Disk response") from None

    def metadata(self, path: str, *, root: bool = False) -> Resource | None:
        if root:
            if path != self.root:
                raise DiskConflict("Invalid orders root")
            canonical_path(path)
        else:
            self.path(path)
        reply = self._request("GET", "/resources", path=path, fields="path,type,resource_id")
        if reply.status == 404:
            return None
        if reply.status != 200:
            raise DiskError("Cannot verify Disk folder")
        data = self._json(reply)
        resource_id = data.get("resource_id")
        if (
            data.get("path") != path
            or data.get("type") != "dir"
            or not isinstance(resource_id, str)
            or not resource_id
            or len(resource_id) > 512
        ):
            raise DiskConflict("Disk resource is not the expected folder")
        return Resource(path, resource_id)

    def create(self, path: str) -> Resource:
        self.path(path)
        if self.metadata(self.root, root=True) is None:
            raise DiskConflict("Create the configured orders root in Disk first")
        reply = self._request("PUT", "/resources", path=path)
        if reply.status == 409:
            # Never silently adopt an unrelated folder after a failed/uncertain create.
            raise DiskConflict("Folder already exists; verify and attach it explicitly")
        if reply.status != 201:
            raise DiskError("Cannot create Disk folder")
        resource = self.metadata(path)
        if resource is None:
            raise DiskError("Created folder could not be verified")
        return resource

    def delete(self, path: str, resource_id: str) -> str | None:
        """Permanent delete; None is synchronous success, otherwise an operation ID."""
        self.path(path)
        resource = self.metadata(path)
        if resource is None or resource.resource_id != resource_id:
            raise DiskConflict("Folder is missing or its identity has changed")
        reply = self._request("DELETE", "/resources", path=path, permanently="true")
        if reply.status == 204:
            return None
        if reply.status != 202:
            raise DiskError("Disk deletion was not accepted")
        data = self._json(reply)
        href = data.get("href")
        if not isinstance(href, str):
            raise DiskError("Invalid Disk operation")
        parsed = urlsplit(href)
        prefix = BASE + "/operations/"
        identifier = parsed.path.removeprefix(prefix)
        if (
            parsed.scheme != "https"
            or parsed.netloc != HOST
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith(prefix)
            or not OPERATION.fullmatch(identifier)
            or data.get("method") != "GET"
        ):
            raise DiskError("Invalid Disk operation")
        return identifier

    def operation(self, identifier: str) -> str:
        if not OPERATION.fullmatch(identifier):
            raise DiskConflict("Invalid Disk operation")
        reply = self._request("GET", "/operations/" + identifier)
        if reply.status != 200:
            raise DiskError("Cannot verify Disk operation")
        status = self._json(reply).get("status")
        if status not in {"in-progress", "success", "failed"}:
            raise DiskError("Invalid Disk operation status")
        return status
