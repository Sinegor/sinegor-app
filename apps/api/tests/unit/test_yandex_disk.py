import json
from urllib.parse import parse_qs, urlsplit

import pytest

from sinegor.core.config import Settings
from sinegor.integrations.yandex_disk.client import (
    DiskConflict,
    DiskError,
    Reply,
    YandexDisk,
)
from sinegor.integrations.yandex_disk.paths import canonical_path, child_path, folder_url
from sinegor.modules.disk.schemas import DeleteFolder, FolderLink

ROOT = "disk:/orders"
PATH = ROOT + "/заказ 1"
TOKEN = "private-disk-token"


def settings(**kwargs):
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://u:p@localhost/test",
        yandex_disk_token=TOKEN,
        yandex_disk_root=ROOT,
        **kwargs,
    )


def reply(status_code=200, **data):
    return Reply(status_code, json.dumps(data).encode())


def meta(path=PATH, resource_id="id-1"):
    return reply(path=path, resource_id=resource_id, type="dir")


class Transport:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, method, target, token, timeout):
        self.calls.append((method, target, token, timeout))
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def disk(*replies):
    transport = Transport(*replies)
    return YandexDisk(settings(), transport), transport


@pytest.mark.parametrize(
    "path",
    [
        "disk:/",
        "/orders/a",
        "disk:/orders/../x",
        "disk:/orders//x",
        "disk:/orders/.",
        "disk:/orders/%2e%2e/x",
        "disk:/orders/a%2Fb",
        "disk:/orders/\\x",
        "disk:/orders/a\n",
        "disk:/orders/x?y",
        "disk:/orders/x#y",
        "disk:/orders/a/",
        "disk:/orders/ x",
        "disk:/orders/e\u0301",
        "disk:/orders/\u200fx",
    ],
)
def test_ambiguous_paths_are_rejected(path):
    with pytest.raises(ValueError):
        canonical_path(path)


@pytest.mark.parametrize("path", [ROOT, "disk:/orders-other/a", "disk:/other"])
def test_root_and_siblings_cannot_be_modified(path):
    with pytest.raises(ValueError):
        child_path(path, ROOT)


def test_create_checks_root_and_identity_and_encodes_path():
    client, transport = disk(meta(ROOT), reply(201), meta())
    resource = client.create(PATH)
    assert resource.path == PATH and resource.resource_id == "id-1"
    assert [c[0] for c in transport.calls] == ["GET", "PUT", "GET"]
    assert parse_qs(urlsplit(transport.calls[1][1]).query)["path"] == [PATH]
    assert all(c[2] == TOKEN and c[3] == 10 for c in transport.calls)
    assert "заказ" not in transport.calls[1][1]
    assert TOKEN not in repr(settings())
    assert folder_url(PATH).startswith("https://disk.yandex.ru/client/disk/")


def test_existing_folder_is_not_silently_adopted():
    client, transport = disk(meta(ROOT), reply(409))
    with pytest.raises(DiskConflict):
        client.create(PATH)
    assert len(transport.calls) == 2


@pytest.mark.parametrize("code", [401, 403, 429, 500, 503, 302])
def test_upstream_errors_do_not_expose_response_or_token(code):
    client, _ = disk(Reply(code, TOKEN.encode()))
    with pytest.raises(DiskError) as error:
        client.metadata(PATH)
    assert TOKEN not in str(error.value)


@pytest.mark.parametrize(
    "data",
    [
        {"path": PATH, "type": "file", "resource_id": "id"},
        {"path": ROOT, "type": "dir", "resource_id": "id"},
        {"path": PATH, "type": "dir"},
    ],
)
def test_incorrect_metadata_is_rejected(data):
    client, _ = disk(reply(**data))
    with pytest.raises(DiskConflict):
        client.metadata(PATH)


def test_transport_errors_are_sanitized():
    client, _ = disk(OSError(TOKEN))
    with pytest.raises(DiskError) as error:
        client.metadata(PATH)
    assert TOKEN not in str(error.value)


@pytest.mark.parametrize("body", [b"not json", b"[]", b"\xff"])
def test_malformed_json_is_rejected(body):
    client, _ = disk(Reply(200, body))
    with pytest.raises(DiskError):
        client.metadata(PATH)


def test_delete_permanent_and_identity_checked():
    client, transport = disk(meta(), reply(204))
    assert client.delete(PATH, "id-1") is None
    params = parse_qs(urlsplit(transport.calls[1][1]).query)
    assert params == {"path": [PATH], "permanently": ["true"]}
    client, transport = disk(meta(resource_id="replacement"))
    with pytest.raises(DiskConflict):
        client.delete(PATH, "id-1")
    assert len(transport.calls) == 1


def test_missing_folder_is_not_proof_of_permanent_deletion():
    client, transport = disk(reply(404))
    with pytest.raises(DiskConflict):
        client.delete(PATH, "id-1")
    assert len(transport.calls) == 1


def test_async_delete_and_status():
    client, _ = disk(
        meta(),
        reply(202, href="https://cloud-api.yandex.net/v1/disk/operations/op-1", method="GET"),
        reply(status="success"),
    )
    assert client.delete(PATH, "id-1") == "op-1"
    assert client.operation("op-1") == "success"


@pytest.mark.parametrize(
    "href",
    [
        "https://evil.example/op",
        "http://cloud-api.yandex.net/v1/disk/operations/x",
        "https://cloud-api.yandex.net/v1/disk/operations/x?token=private",
        "https://cloud-api.yandex.net/v1/disk/operations/../resources",
        "https://cloud-api.yandex.net@evil.example/v1/disk/operations/x",
    ],
)
def test_operation_links_never_allow_token_exfiltration(href):
    client, transport = disk(meta(), reply(202, href=href, method="GET"))
    with pytest.raises(DiskError):
        client.delete(PATH, "id-1")
    assert len(transport.calls) == 2


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_deletion_confirmation_must_be_explicit_boolean(value):
    with pytest.raises(ValueError):
        DeleteFolder(deletion_request_id="00000000-0000-0000-0000-000000000001", confirm=value)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/client/disk",
        "https://disk.yandex.ru.evil/client/a",
        "http://disk.yandex.ru/client/a",
        "https://disk.yandex.ru/d/public",
    ],
)
def test_shared_link_restricted_to_disk_interface(url):
    with pytest.raises(ValueError):
        FolderLink(folder_url=url, access_granted=True)


def test_manual_invitation_link_is_supported():
    link = "https://disk.yandex.ru/invite/?hash=manual-invitation"
    assert FolderLink(folder_url=link, access_granted=True).folder_url == link


@pytest.mark.parametrize("value", [1, "true", None])
def test_result_verification_requires_boolean(value):
    with pytest.raises(ValueError):
        DeleteFolder(
            deletion_request_id="00000000-0000-0000-0000-000000000001",
            confirm=True,
            permanent_deletion_verified=value,
        )
