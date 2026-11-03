import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import test_auth as helpers
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from test_auth import login_admin, login_customer, post
from test_orders import approve, mutate

from sinegor.db.types import DeletionReason, DeletionStatus, OrderStatus
from sinegor.integrations.yandex_disk.client import DiskError, Reply, Resource, YandexDisk
from sinegor.modules.audit.models import OrderEvent
from sinegor.modules.disk import service as disk_service
from sinegor.modules.disk.models import DiskFolder
from sinegor.modules.retention.models import DeletionRequest

pytestmark = pytest.mark.integration
auth = helpers.auth
actors = helpers.actors
ROOT = "disk:/orders"


class MemoryDisk(YandexDisk):
    def __init__(self):
        self.root = ROOT
        self._token = True
        self.resources = {}
        self.calls = []
        self.pending = False
        self.status = "in-progress"
        self.fail = False
        self.fail_verification = False

    def metadata(self, path, **kwargs):
        self.path(path)
        if self.fail or self.fail_verification:
            raise DiskError("Disk service unavailable")
        return self.resources.get(path)

    def create(self, path):
        self.path(path)
        self.calls.append(("create", path))
        if self.fail:
            raise DiskError("Disk service unavailable")
        resource = Resource(path, "id-" + str(uuid4()))
        self.resources[path] = resource
        return resource

    def delete(self, path, resource_id):
        self.path(path)
        self.calls.append(("delete", path))
        if self.fail:
            raise DiskError("Disk service unavailable")
        if self.resources.get(path) != Resource(path, resource_id):
            from sinegor.integrations.yandex_disk.client import DiskConflict

            raise DiskConflict("Folder identity changed")
        if self.pending:
            return "operation-1"
        del self.resources[path]
        return None

    def operation(self, identifier):
        self.calls.append(("operation", identifier))
        if self.status == "success":
            self.resources.clear()
        return self.status


@pytest.fixture
def admin(auth, actors):
    login_admin(auth, actors)
    auth.app.state.yandex_disk = MemoryDisk()
    auth.disk = auth.app.state.yandex_disk
    return auth


def folder_path(actors):
    return f"/api/admin/orders/{actors.order.id}/folder"


def create(admin, actors):
    result = post(admin, folder_path(actors))
    assert result.status_code == 200, result.text
    return result.json()


def eligible(admin, actors, *, early=False):
    now = datetime.now(UTC)
    # Keep all domain timestamps consistent even for a newly-created test order.
    actors.order.created_at = now - timedelta(days=20)
    actors.order.ready_at = now - timedelta(days=15 if not early else 1)
    actors.order.result_notified_at = actors.order.ready_at
    actors.order.status = OrderStatus.RESULT_READY
    request = DeletionRequest(
        order_id=actors.order.id,
        reason=DeletionReason.EARLY_PERMISSION if early else DeletionReason.RETENTION_EXPIRED,
        status=DeletionStatus.CONFIRMED,
        due_at=now - timedelta(days=1),
        confirmed_at=now,
        confirmed_by_id=actors.admin.id,
        early_authorized_at=now if early else None,
    )
    admin.db.add(request)
    admin.db.commit()
    return request


def delete(admin, actors, request, **kwargs):
    return post(
        admin,
        folder_path(actors) + "/delete",
        {
            "deletion_request_id": str(request.id),
            "confirm": True,
            **kwargs,
        },
    )


def test_create_retry_open_and_event(admin, actors):
    first = create(admin, actors)
    assert create(admin, actors)["id"] == first["id"]
    assert len(admin.disk.calls) == 1
    assert first["resource_id"] and first["folder_url"] is None
    assert admin.client.get(folder_path(actors)).json() == first
    opened = admin.client.get(folder_path(actors) + "/open")
    assert opened.status_code == 200
    assert opened.json()["folder_url"].startswith("https://disk.yandex.ru/client/")
    assert (
        admin.db.scalar(
            select(func.count())
            .select_from(OrderEvent)
            .where(OrderEvent.event_type == "disk_folder_bound")
        )
        == 1
    )


def test_attach_verifies_identity_and_prevents_rebind_and_nesting(admin, actors):
    path = ROOT + "/existing"
    admin.disk.resources[path] = Resource(path, "unique-resource")
    attached = mutate(admin, "PUT", folder_path(actors), {"disk_path": path})
    assert attached.status_code == 200
    assert mutate(admin, "PUT", folder_path(actors), {"disk_path": path}).status_code == 200
    assert (
        mutate(admin, "PUT", folder_path(actors), {"disk_path": ROOT + "/another"}).status_code
        == 409
    )
    other = f"/api/admin/orders/{actors.other_order.id}/folder"
    for candidate in [path, path + "/child"]:
        result = mutate(admin, "PUT", other, {"disk_path": candidate})
        assert result.status_code == 409
    alias = ROOT + "/alias"
    admin.disk.resources[alias] = Resource(alias, "unique-resource")
    assert mutate(admin, "PUT", other, {"disk_path": alias}).status_code == 409
    assert mutate(admin, "PUT", other, {"disk_path": ROOT + "/missing"}).status_code == 404


def test_customer_link_requires_ownership_agreement_and_manual_access(admin, actors):
    create(admin, actors)
    customer_path = f"/api/customer/orders/{actors.order.id}/folder"
    shared = "https://disk.yandex.ru/client/disk/Shared?invite=manually-set"
    response = mutate(
        admin,
        "PUT",
        folder_path(actors) + "/link",
        {
            "folder_url": shared,
            "access_granted": True,
        },
    )
    assert response.status_code == 200
    login_customer(admin)
    assert admin.client.get(customer_path).status_code == 404
    approve(admin, actors)
    assert admin.client.get(customer_path).json() == {"folder_url": shared}
    assert (
        admin.client.get(f"/api/customer/orders/{actors.other_order.id}/folder").status_code == 404
    )
    assert admin.client.get(folder_path(actors)).status_code == 403
    assert post(admin, folder_path(actors)).status_code == 403
    assert mutate(admin, "PUT", folder_path(actors), {"disk_path": ROOT + "/x"}).status_code == 403
    assert (
        post(
            admin,
            folder_path(actors) + "/delete",
            {
                "deletion_request_id": str(uuid4()),
                "confirm": True,
            },
        ).status_code
        == 403
    )


def test_csrf_anonymous_and_invalid_paths(admin, actors):
    assert admin.client.post(folder_path(actors)).status_code == 403
    for path in ["disk:/orders/../secret", "disk:/orders/%2e%2e/a", "disk:/orders//a"]:
        assert mutate(admin, "PUT", folder_path(actors), {"disk_path": path}).status_code == 422
    admin.client.cookies.clear()
    assert admin.client.get(folder_path(actors)).status_code == 401
    assert not admin.disk.calls


def test_failed_create_leaves_no_binding_and_can_retry(admin, actors):
    admin.disk.fail = True
    assert post(admin, folder_path(actors)).status_code == 503
    assert admin.db.scalar(select(DiskFolder)) is None
    admin.disk.fail = False
    create(admin, actors)


@pytest.mark.parametrize("early", [False, True])
def test_confirmed_delete_is_idempotent_and_preserves_order_and_agreement(admin, actors, early):
    create(admin, actors)
    agreement = approve(admin, actors)
    request = eligible(admin, actors, early=early)
    result = delete(admin, actors, request)
    assert result.status_code == 200, result.text
    assert result.json()["deleted_at"]
    assert request.status == DeletionStatus.PERFORMED
    assert actors.order.status == OrderStatus.RESULT_READY
    assert admin.db.get(type(agreement), agreement.id).final_sha256 == "a" * 64
    count = len(admin.disk.calls)
    assert delete(admin, actors, request).json()["deleted_at"] == result.json()["deleted_at"]
    assert len(admin.disk.calls) == count
    assert admin.client.get(folder_path(actors) + "/open").status_code == 409
    assert post(admin, folder_path(actors)).status_code == 409


def test_async_deletion_persists_operation_and_checks_result(admin, actors):
    create(admin, actors)
    request = eligible(admin, actors)
    admin.disk.pending = True
    started = delete(admin, actors, request)
    assert started.status_code == 202
    assert started.json()["deletion_operation_id"] == "operation-1"
    assert request.performed_at is None
    assert delete(admin, actors, request).status_code == 202
    admin.disk.status = "success"
    completed = delete(admin, actors, request)
    assert completed.status_code == 200 and completed.json()["deleted_at"]
    assert len([call for call in admin.disk.calls if call[0] == "delete"]) == 1


def test_failed_async_operation_and_network_failure_can_retry(admin, actors):
    create(admin, actors)
    request = eligible(admin, actors)
    admin.disk.pending = True
    assert delete(admin, actors, request).status_code == 202
    admin.disk.status = "failed"
    assert delete(admin, actors, request).status_code == 503
    assert request.status == DeletionStatus.ERROR
    assert admin.db.scalar(select(DiskFolder)).deletion_operation_id is None
    admin.disk.pending = False
    admin.disk.fail = True
    assert delete(admin, actors, request).status_code == 503
    admin.disk.fail = False
    assert delete(admin, actors, request).status_code == 200


def test_upstream_success_survives_verification_failure(admin, actors, monkeypatch):
    create(admin, actors)
    request = eligible(admin, actors)
    original_delete = admin.disk.delete

    def fail_verification_after_delete(path, resource_id):
        result = original_delete(path, resource_id)
        admin.disk.fail_verification = True
        return result

    monkeypatch.setattr(admin.disk, "delete", fail_verification_after_delete)
    assert delete(admin, actors, request).status_code == 503
    assert admin.db.scalar(select(DiskFolder)).deletion_succeeded
    assert request.performed_at is None
    admin.disk.fail_verification = False
    assert delete(admin, actors, request).status_code == 200
    assert len([c for c in admin.disk.calls if c[0] == "delete"]) == 1


@pytest.mark.parametrize(
    "change", ["waiting", "deferred", "future", "wrong_order", "too_early", "missing_confirmation"]
)
def test_ineligible_requests_never_delete(admin, actors, change):
    create(admin, actors)
    request = eligible(admin, actors)
    if change == "waiting":
        request.status = DeletionStatus.WAITING
    elif change == "deferred":
        request.deferred_until = datetime.now(UTC) + timedelta(days=1)
    elif change == "future":
        request.due_at = datetime.now(UTC) + timedelta(days=1)
    elif change == "wrong_order":
        request.order_id = actors.other_order.id
    elif change == "too_early":
        actors.order.ready_at = datetime.now(UTC) - timedelta(days=1)
        actors.order.result_notified_at = actors.order.ready_at
    else:
        request.status = DeletionStatus.WAITING
        request.confirmed_at = None
        request.confirmed_by_id = None
    admin.db.commit()
    assert delete(admin, actors, request).status_code == 409
    assert not [c for c in admin.disk.calls if c[0] == "delete"]


def test_replaced_or_outside_folder_never_deleted(admin, actors):
    first = create(admin, actors)
    request = eligible(admin, actors)
    admin.disk.resources[first["disk_path"]] = Resource(first["disk_path"], "replacement")
    assert delete(admin, actors, request).status_code == 409
    folder = admin.db.scalar(select(DiskFolder))
    folder.disk_path = "disk:/other/secret"
    admin.db.commit()
    calls = len(admin.disk.calls)
    assert delete(admin, actors, request).status_code == 422
    assert len(admin.disk.calls) == calls


def test_review_reattach_fills_legacy_resource_id_before_deletion(admin, actors):
    path = ROOT + "/legacy"
    folder = DiskFolder(order_id=actors.order.id, disk_path=path)
    admin.db.add(folder)
    admin.db.commit()
    admin.disk.resources[path] = Resource(path, "legacy-resource")
    attached = mutate(admin, "PUT", folder_path(actors), {"disk_path": path})
    assert attached.status_code == 200
    assert attached.json()["resource_id"] == "legacy-resource"
    request = eligible(admin, actors)
    assert delete(admin, actors, request).status_code == 200


def test_review_lost_delete_response_requires_explicit_result_verification(admin, actors):
    first = create(admin, actors)
    request = eligible(admin, actors)
    remote_exists = True
    calls = []

    def transport(method, target, token, timeout):
        nonlocal remote_exists
        calls.append(method)
        if method == "DELETE":
            remote_exists = False
            raise TimeoutError("Response lost after deletion")
        if not remote_exists:
            return Reply(404)
        return Reply(
            200,
            json.dumps(
                {
                    "path": first["disk_path"],
                    "type": "dir",
                    "resource_id": first["resource_id"],
                }
            ).encode(),
        )

    settings = admin.settings.model_copy(
        update={
            "yandex_disk_root": ROOT,
            "yandex_disk_token": SecretStr("test-only"),
        }
    )
    admin.app.state.yandex_disk = YandexDisk(settings, transport)
    assert delete(admin, actors, request).status_code == 503
    # Ordinary retries must not treat an absent folder as proof of permanent deletion.
    assert delete(admin, actors, request).status_code == 409
    assert request.performed_at is None
    resolved = delete(admin, actors, request, permanent_deletion_verified=True)
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["deleted_at"]
    assert resolved.json()["deletion_started_at"]
    assert not remote_exists
    assert request.status == DeletionStatus.PERFORMED
    assert calls.count("DELETE") == 1
    repeated = delete(admin, actors, request, permanent_deletion_verified=True)
    assert repeated.json()["deleted_at"] == resolved.json()["deleted_at"]
    event = admin.db.scalar(
        select(OrderEvent).where(
            OrderEvent.event_type == "disk_deletion_manually_verified",
        )
    )
    assert event.actor_admin_id == actors.admin.id


@pytest.mark.parametrize("remote", ["missing", "replacement", "duplicate"])
def test_review_reattach_checks_identity_without_overwriting_binding(admin, actors, remote):
    first = create(admin, actors)
    folder = admin.db.scalar(select(DiskFolder))
    if remote == "missing":
        del admin.disk.resources[first["disk_path"]]
        expected = 404
    elif remote == "replacement":
        admin.disk.resources[first["disk_path"]] = Resource(first["disk_path"], "other-id")
        expected = 409
    else:
        admin.db.add(
            DiskFolder(
                order_id=actors.other_order.id,
                disk_path=ROOT + "/other",
                resource_id="other-id",
            )
        )
        folder.resource_id = None
        admin.db.commit()
        admin.disk.resources[first["disk_path"]] = Resource(first["disk_path"], "other-id")
        expected = 409
    original_id = folder.resource_id
    result = mutate(admin, "PUT", folder_path(actors), {"disk_path": first["disk_path"]})
    assert result.status_code == expected
    admin.db.expire_all()
    assert admin.db.get(DiskFolder, folder.id).resource_id == original_id


def test_review_commit_failure_after_delete_preserves_intent(admin, actors, monkeypatch):
    create(admin, actors)
    request = eligible(admin, actors)
    original_commit = admin.db.commit

    def fail_receipt_commit():
        folder = admin.db.scalar(select(DiskFolder))
        if folder.deletion_succeeded:
            raise SQLAlchemyError("Simulated receipt commit failure")
        original_commit()

    with monkeypatch.context() as patch:
        patch.setattr(admin.db, "commit", fail_receipt_commit)
        with pytest.raises(SQLAlchemyError):
            disk_service.delete_folder(
                admin.db, admin.disk, actors.order.id, request.id, actors.admin.id
            )
    admin.db.rollback()
    admin.db.expire_all()
    folder = admin.db.scalar(select(DiskFolder))
    assert folder.deletion_started_at is not None
    assert not folder.deletion_succeeded and folder.deleted_at is None
    assert not admin.disk.resources
    assert delete(admin, actors, request, permanent_deletion_verified=True).status_code == 200
    assert len([c for c in admin.disk.calls if c[0] == "delete"]) == 1


def test_review_failed_intent_commit_does_not_send_delete(admin, actors, monkeypatch):
    create(admin, actors)
    request = eligible(admin, actors)

    def fail_commit():
        raise SQLAlchemyError("Simulated intent commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(admin.db, "commit", fail_commit)
        with pytest.raises(SQLAlchemyError):
            disk_service.delete_folder(
                admin.db, admin.disk, actors.order.id, request.id, actors.admin.id
            )
    admin.db.rollback()
    admin.db.expire_all()
    assert admin.db.scalar(select(DiskFolder)).deletion_started_at is None
    assert not [c for c in admin.disk.calls if c[0] == "delete"]


@pytest.mark.parametrize("state", ["no_attempt", "existing", "replacement", "pending"])
def test_review_manual_verification_requires_uncertain_attempt_and_absence(admin, actors, state):
    first = create(admin, actors)
    request = eligible(admin, actors)
    folder = admin.db.scalar(select(DiskFolder))
    if state == "no_attempt":
        del admin.disk.resources[first["disk_path"]]
    elif state in {"existing", "replacement"}:
        folder.deletion_started_at = datetime.now(UTC)
        if state == "replacement":
            admin.disk.resources[first["disk_path"]] = Resource(first["disk_path"], "replacement")
        admin.db.commit()
    else:
        admin.disk.pending = True
        assert delete(admin, actors, request).status_code == 202
    count = len(admin.disk.calls)
    assert delete(admin, actors, request, permanent_deletion_verified=True).status_code == 409
    assert request.performed_at is None
    assert len(admin.disk.calls) == count


def test_review_customer_cannot_confirm_uncertain_result(admin, actors):
    create(admin, actors)
    request = eligible(admin, actors)
    folder = admin.db.scalar(select(DiskFolder))
    folder.deletion_started_at = datetime.now(UTC)
    admin.db.commit()
    admin.disk.resources.clear()
    login_customer(admin)
    assert delete(admin, actors, request, permanent_deletion_verified=True).status_code == 403
    assert request.performed_at is None


@pytest.mark.parametrize(
    "base, expected",
    [(None, "Заказ"), ("", "Заказ"), ("  Финансовые документы  ", "Финансовые_документы")],
)
def test_named_creation_and_repeat_keep_original_binding(
    admin, actors, monkeypatch, base, expected
):
    class FixedDateTime:
        @classmethod
        def now(cls, zone):
            # UTC is still November 1; Moscow is already November 2.
            return datetime(2026, 11, 1, 22, 30, tzinfo=UTC).astimezone(zone)

    monkeypatch.setattr(disk_service, "datetime", FixedDateTime)
    body = {} if base is None else {"name_base": base}
    response = post(admin, folder_path(actors), body)
    assert response.status_code == 200
    expected_path = f"{ROOT}/{expected}_{actors.order.number:03d}_2026-11-02"
    assert response.json()["disk_path"] == expected_path
    repeated = post(admin, folder_path(actors), {"name_base": "Different"})
    assert repeated.status_code == 200
    assert repeated.json()["disk_path"] == expected_path
    assert len(admin.disk.calls) == 1


@pytest.mark.parametrize(
    "base",
    [
        "../secret",
        "a/b",
        "a\\b",
        "a?b",
        "a%b",
        "a#b",
        "a:b",
        "a*",
        "a<",
        "a|",
        "a\x00",
        "a\u200fb",
        "x" * 101,
    ],
)
def test_invalid_folder_name_does_not_contact_disk(admin, actors, base):
    response = post(admin, folder_path(actors), {"name_base": base})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "disk_invalid_name"
    assert not admin.disk.calls
    assert admin.db.scalar(select(DiskFolder)) is None


@pytest.mark.parametrize(
    "upstream, status, code",
    [
        (404, 404, "disk_folder_not_found"),
        (401, 503, "disk_access_denied"),
        (403, 503, "disk_access_denied"),
        (503, 503, "disk_unavailable"),
    ],
)
def test_attach_failure_is_distinct_and_never_binds(admin, actors, upstream, status, code):
    settings = admin.settings.model_copy(
        update={"yandex_disk_root": ROOT, "yandex_disk_token": SecretStr("test-only")}
    )
    calls = []

    def transport(method, target, token, timeout):
        calls.append(method)
        return Reply(upstream, b"private upstream details")

    admin.app.state.yandex_disk = YandexDisk(settings, transport)
    response = mutate(admin, "PUT", folder_path(actors), {"disk_path": ROOT + "/missing"})
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "private upstream details" not in response.text
    assert calls == ["GET"]
    assert admin.db.scalar(select(DiskFolder)) is None


@pytest.mark.parametrize("path", ["disk:/elsewhere/a", ROOT, ROOT + "/../secret"])
def test_invalid_binding_path_is_reported_without_upstream_request(admin, actors, path):
    response = mutate(admin, "PUT", folder_path(actors), {"disk_path": path})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "disk_invalid_path"
    assert not admin.disk.calls
    assert admin.db.scalar(select(DiskFolder)) is None


def test_file_cannot_be_attached_as_order_folder(admin, actors):
    path = ROOT + "/not-a-folder"
    settings = admin.settings.model_copy(
        update={"yandex_disk_root": ROOT, "yandex_disk_token": SecretStr("test-only")}
    )

    def transport(method, target, token, timeout):
        return Reply(
            200, json.dumps({"path": path, "type": "file", "resource_id": "file-id"}).encode()
        )

    admin.app.state.yandex_disk = YandexDisk(settings, transport)
    response = mutate(admin, "PUT", folder_path(actors), {"disk_path": path})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "disk_invalid_path"
    assert admin.db.scalar(select(DiskFolder)) is None
