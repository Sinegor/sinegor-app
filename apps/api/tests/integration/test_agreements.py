import hashlib
import os
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
import test_auth as auth_helpers
from pypdf import PdfWriter
from sqlalchemy import event, func, select
from test_orders import ResultMailer

from sinegor.db.types import OrderStatus
from sinegor.modules.agreements import service
from sinegor.modules.agreements.models import Agreement, AgreementFileDeletion
from sinegor.modules.agreements.storage import AgreementStorage, AgreementStorageError
from sinegor.modules.audit.models import OrderEvent
from sinegor.modules.orders.service import process_lifecycle

pytestmark = pytest.mark.integration
auth = auth_helpers.auth
actors = auth_helpers.actors


def pdf(title="agreement", *, encrypted=False, empty=False):
    writer = PdfWriter()
    if not empty:
        writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Title": title})
    if encrypted:
        writer.encrypt("test-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.fixture
def api(auth, actors, tmp_path):
    storage = AgreementStorage(tmp_path / "agreements")
    auth.app.state.agreement_storage = storage
    auth_helpers.login_admin(auth, actors)
    admin_cookies = dict(auth.client.cookies)
    auth.client.cookies.clear()
    auth_helpers.login_customer(auth)
    customer_cookies = dict(auth.client.cookies)

    def switch(role):
        auth.client.cookies.clear()
        auth.client.cookies.update(admin_cookies if role == "admin" else customer_cookies)

    def upload(role, data, revision, order_id=None, **headers):
        switch(role)
        csrf = auth.client.get("/api/auth/csrf").json()["csrf_token"]
        kind = "initial" if role == "admin" else "returned"
        return auth.client.post(
            f"/api/{role}/orders/{order_id or actors.order.id}/agreement/{kind}",
            content=data,
            headers={
                "Origin": "http://testserver",
                "X-CSRF-Token": csrf,
                "Content-Type": "application/pdf",
                "X-Agreement-Revision": str(revision),
                **headers,
            },
        )

    def review(action, revision, **extra):
        switch("admin")
        return auth_helpers.post(
            auth,
            f"/api/admin/orders/{actors.order.id}/agreement/{action}",
            {"revision": revision, **extra},
        )

    def get(role, kind=None, order_id=None):
        switch(role)
        suffix = f"/{kind}" if kind else ""
        return auth.client.get(
            f"/api/{role}/orders/{order_id or actors.order.id}/agreement{suffix}"
        )

    return SimpleNamespace(
        auth=auth,
        actors=actors,
        storage=storage,
        upload=upload,
        review=review,
        get=get,
        switch=switch,
    )


def test_pdf_exchange_approval_and_private_download(api):
    initial, signed = pdf("executor signed"), pdf("both signatures")
    assert api.get("admin").status_code == 404
    created = api.upload("admin", initial, 0)
    assert created.status_code == 200, created.text
    assert created.json()["status"] == "awaiting_customer" and created.json()["revision"] == 1
    assert "pdf_key" not in created.text and str(api.storage.root) not in created.text
    agreement = api.auth.db.scalar(
        select(Agreement).where(Agreement.order_id == api.actors.order.id)
    )
    initial_key = agreement.initial_pdf_key
    downloaded = api.get("customer", "initial")
    assert downloaded.status_code == 200 and downloaded.content == initial
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert downloaded.headers["cache-control"] == "no-store"
    assert downloaded.headers["x-agreement-revision"] == "1"
    returned = api.upload("customer", signed, 1)
    assert returned.status_code == 200 and returned.json()["status"] == "under_review"
    assert api.get("admin", "returned").content == signed
    approved = api.review("approve", 2)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved" and approved.json()["revision"] == 3
    assert approved.json()["final_sha256"] == hashlib.sha256(signed).hexdigest()
    assert approved.json()["verified_by_id"] == str(api.actors.admin.id)
    assert api.actors.order.status == OrderStatus.AWAITING_MATERIALS
    assert not (api.storage.root / initial_key).exists()
    assert api.get("customer", "initial").status_code == 404
    assert api.get("admin", "returned").status_code == 404
    assert api.get("customer", "final").content == signed
    assert api.get("admin", "final").content == signed
    assert len(list(api.storage.root.glob("*.pdf"))) == 1
    assert api.review("approve", 3).status_code == 409
    assert api.upload("customer", signed, 3).status_code == 409
    assert api.upload("admin", initial, 3).status_code == 409
    assert api.auth.db.scalar(select(func.count()).select_from(AgreementFileDeletion)) == 0
    events = api.auth.db.scalars(
        select(OrderEvent).where(OrderEvent.order_id == api.actors.order.id)
    ).all()
    types = [event.event_type for event in events]
    for expected in (
        "agreement_initial_uploaded",
        "agreement_returned_uploaded",
        "agreement_approved",
        "agreement_file_deleted",
        "status_awaiting_materials",
        "agreement_final_downloaded",
    ):
        assert expected in types
    assert (
        next(
            event for event in events if event.event_type == "agreement_returned_uploaded"
        ).actor_customer_id
        == api.actors.customer.id
    )
    api.auth.app.state.order_mailer = ResultMailer()
    api.switch("admin")
    for body in (
        {"status": "in_progress"},
        {"status": "result_ready", "result_uploaded": True},
    ):
        response = auth_helpers.post(
            api.auth, f"/api/admin/orders/{api.actors.order.id}/status", body
        )
        assert response.status_code == 200, response.text
    due = api.actors.order.result_notified_at + timedelta(days=14)
    assert process_lifecycle(api.auth.db, now=due) == 1
    assert api.get("customer", "final").content == signed


def test_rejection_keeps_initial_and_allows_resigning(api):
    initial = pdf("initial")
    assert api.upload("admin", initial, 0).status_code == 200
    assert api.upload("customer", pdf("missing signature"), 1).status_code == 200
    assert api.review("reject", 2, reason=" ").status_code == 422
    rejected = api.review("reject", 2, reason="Please sign page two")
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected" and rejected.json()["revision"] == 3
    assert api.get("customer").json()["rejection_reason"] == "Please sign page two"
    assert api.get("customer", "initial").content == initial
    assert api.get("admin", "returned").status_code == 404
    assert api.actors.order.status == OrderStatus.AWAITING_AGREEMENT
    assert len(list(api.storage.root.glob("*.pdf"))) == 1
    assert api.upload("customer", pdf("corrected"), 3).status_code == 200
    assert api.get("admin").json()["rejection_reason"] is None
    assert api.review("approve", 4).status_code == 200


def test_stale_review_cannot_approve_a_replacement(api):
    assert api.upload("admin", pdf(), 0).status_code == 200
    assert api.upload("customer", pdf("first"), 1).status_code == 200
    first = api.get("admin", "returned")
    assert api.upload("customer", pdf("replacement"), 2).status_code == 200
    assert api.review("approve", int(first.headers["x-agreement-revision"])).status_code == 409
    assert api.review("reject", 2, reason="old review").status_code == 409
    assert api.upload("customer", pdf(), 2).status_code == 409
    assert api.upload("admin", pdf(), 3).status_code == 409
    assert api.review("approve", 3).status_code == 200
    assert api.get("customer", "final").content == pdf("replacement")


def test_initial_replacement_checks_version_and_cleans_old_file(api):
    assert api.upload("admin", pdf("old"), 0).status_code == 200
    assert api.upload("admin", pdf("new"), 0).status_code == 409
    assert api.upload("admin", pdf("new"), 1).status_code == 200
    assert api.get("customer", "initial").content == pdf("new")
    assert len(list(api.storage.root.glob("*.pdf"))) == 1


@pytest.mark.parametrize(
    "data",
    [b"", b"not a PDF", b"%PDF-1.7\nprivate-fragment\n%%EOF", pdf(encrypted=True), pdf(empty=True)],
)
def test_invalid_pdfs_are_rejected_without_creating_files(api, data):
    response = api.upload("admin", data, 0)
    assert response.status_code == 422, response.text
    assert "private-fragment" not in response.text
    assert not api.storage.root.exists()
    assert api.auth.db.scalar(select(func.count()).select_from(Agreement)) == 0


def test_type_size_and_missing_revision_checks(api, monkeypatch):
    assert api.upload("admin", pdf(), 0, **{"Content-Type": "text/plain"}).status_code == 415
    monkeypatch.setattr(api.auth.settings, "agreement_max_bytes", 100)
    assert api.upload("admin", b"x" * 101, 0).status_code == 413
    # A chunked request cannot bypass the bound by omitting Content-Length.
    chunks = iter([b"%PDF-" + b"x" * 50, b"x" * 51])
    assert api.upload("admin", chunks, 0).status_code == 413
    assert not api.storage.root.exists()


def test_roles_ownership_and_csrf(api):
    assert api.upload("admin", pdf(), 0, order_id=uuid4()).status_code == 404
    assert api.upload("customer", pdf(), 0).status_code == 409
    assert api.upload("customer", pdf(), 0, order_id=api.actors.other_order.id).status_code == 404
    assert api.get("customer", order_id=api.actors.other_order.id).status_code == 404
    assert api.get("customer", "initial", order_id=api.actors.other_order.id).status_code == 404
    api.switch("customer")
    assert (
        auth_helpers.post(
            api.auth, f"/api/admin/orders/{api.actors.order.id}/agreement/approve", {"revision": 1}
        ).status_code
        == 403
    )
    api.switch("admin")
    path = f"/api/admin/orders/{api.actors.order.id}/agreement/initial"
    assert (
        api.auth.client.post(
            path,
            content=pdf(),
            headers={"Content-Type": "application/pdf", "X-Agreement-Revision": "0"},
        ).status_code
        == 403
    )
    csrf = api.auth.client.get("/api/auth/csrf").json()["csrf_token"]
    assert (
        api.auth.client.post(
            path,
            content=pdf(),
            headers={
                "Origin": "http://testserver",
                "X-CSRF-Token": csrf,
                "Content-Type": "application/pdf",
            },
        ).status_code
        == 422
    )
    api.auth.client.cookies.clear()
    assert (
        api.auth.client.get(f"/api/admin/orders/{api.actors.order.id}/agreement").status_code == 401
    )
    assert (
        api.auth.client.get(
            f"/api/customer/orders/{api.actors.order.id}/agreement/final"
        ).status_code
        == 401
    )


def test_cancelled_order_does_not_accept_agreement(api):
    api.switch("admin")
    assert (
        auth_helpers.post(
            api.auth,
            f"/api/admin/orders/{api.actors.order.id}/status",
            {
                "status": "cancelled",
                "cancellation_internal_reason": "Internal decision",
                "cancellation_customer_reason": "Explanation for customer",
            },
        ).status_code
        == 200
    )
    assert api.upload("admin", pdf(), 0).status_code == 409


def test_cleanup_failure_is_durable_and_never_removes_final(api, monkeypatch):
    assert api.upload("admin", pdf("initial"), 0).status_code == 200
    assert api.upload("customer", pdf("final"), 1).status_code == 200
    original_delete = api.storage.delete

    def fail(key):
        raise AgreementStorageError("private-path")

    monkeypatch.setattr(api.storage, "delete", fail)
    assert api.review("approve", 2).status_code == 200
    assert api.get("customer", "final").content == pdf("final")
    assert len(list(api.storage.root.glob("*.pdf"))) == 2
    assert api.auth.db.scalar(select(func.count()).select_from(AgreementFileDeletion)) == 1
    monkeypatch.setattr(api.storage, "delete", original_delete)
    assert service.cleanup_files(api.auth.db, api.storage) == 1
    assert service.cleanup_files(api.auth.db, api.storage) == 0
    agreement = api.auth.db.scalar(select(Agreement))
    api.auth.db.add(
        AgreementFileDeletion(order_id=api.actors.order.id, file_key=agreement.final_pdf_key)
    )
    api.auth.db.commit()
    assert service.cleanup_files(api.auth.db, api.storage) == 0
    assert (
        service.cleanup_orphans(api.auth.db, api.storage, now=datetime.now(UTC) + timedelta(days=2))
        == 0
    )
    assert api.get("customer", "final").content == pdf("final")


def test_approval_database_failure_preserves_both_documents(api):
    assert api.upload("admin", pdf("initial"), 0).status_code == 200
    assert api.upload("customer", pdf("returned"), 1).status_code == 200

    def fail(db):
        raise RuntimeError("simulated commit failure")

    event.listen(api.auth.db, "before_commit", fail)
    try:
        with pytest.raises(RuntimeError, match="simulated commit failure"):
            service.review(api.auth.db, api.storage, api.actors.order.id, 2, api.actors.admin.id)
    finally:
        event.remove(api.auth.db, "before_commit", fail)
        api.auth.db.rollback()
    assert api.get("customer", "initial").content == pdf("initial")
    assert api.get("admin", "returned").content == pdf("returned")
    assert api.get("admin").json()["status"] == "under_review"
    assert api.actors.order.status == OrderStatus.AWAITING_AGREEMENT
    assert api.auth.db.scalar(select(func.count()).select_from(AgreementFileDeletion)) == 0


def test_tampering_or_missing_pdf_blocks_approval(api):
    assert api.upload("admin", pdf(), 0).status_code == 200
    assert api.upload("customer", pdf("signed"), 1).status_code == 200
    agreement = api.auth.db.scalar(select(Agreement))
    path = api.storage.root / agreement.returned_pdf_key
    path.write_bytes(pdf("tampered"))
    assert api.review("approve", 2).status_code == 503
    assert api.get("admin", "returned").status_code == 503
    path.unlink()
    assert api.review("approve", 2).status_code == 503
    assert api.get("admin").json()["status"] == "under_review"


def test_storage_failure_does_not_publish_an_agreement(api, monkeypatch):
    def fail(data):
        raise AgreementStorageError("private-path")

    monkeypatch.setattr(api.storage, "put", fail)
    response = api.upload("admin", pdf(), 0)
    assert response.status_code == 503 and "private-path" not in response.text
    assert api.auth.db.scalar(select(func.count()).select_from(Agreement)) == 0


def test_orphan_cleanup_preserves_references_and_recent_uploads(api):
    assert api.upload("admin", pdf("active"), 0).status_code == 200
    old_key, _ = api.storage.put(pdf("abandoned after crash"))
    recent_key, _ = api.storage.put(pdf("recent"))
    old_time = (datetime.now(UTC) - timedelta(days=2)).timestamp()
    os.utime(api.storage.root / old_key, (old_time, old_time))
    assert service.cleanup_orphans(api.auth.db, api.storage) == 1
    assert not (api.storage.root / old_key).exists()
    assert (api.storage.root / recent_key).exists()
    assert api.get("customer", "initial").content == pdf("active")


@pytest.mark.parametrize("reason", ["", " ", "\t\n"])
def test_review_validates_rejection_reason_and_approval_payload(api, reason):
    assert api.upload("admin", pdf(), 0).status_code == 200
    assert api.upload("customer", pdf("signed"), 1).status_code == 200
    assert api.review("reject", 2, reason=reason).status_code == 422
    assert api.get("admin").json()["status"] == "under_review"
    assert api.review("approve", 2, reason="must not be supplied").status_code == 422
    assert api.review("approve", 2).status_code == 200


@pytest.mark.parametrize("role", ["admin", "customer"])
def test_final_pdf_download_preserves_bytes_digest_and_attachment(api, role):
    signed = pdf("synthetic approved agreement")
    assert api.upload("admin", pdf("synthetic initial agreement"), 0).status_code == 200
    assert api.upload("customer", signed, 1).status_code == 200
    approved = api.review("approve", 2).json()
    digest = hashlib.sha256(signed).hexdigest()
    assert approved["final_sha256"] == digest
    agreement = api.auth.db.scalar(select(Agreement))
    stored = api.storage.root / agreement.final_pdf_key
    for _ in range(2):
        response = api.get(role, "final")
        assert response.status_code == 200
        assert response.content == signed == stored.read_bytes()
        assert hashlib.sha256(response.content).hexdigest() == digest
        assert response.headers["etag"] == f'"{digest}"'
        assert response.headers["content-disposition"] == (
            f'attachment; filename="agreement-{api.actors.order.number}-final.pdf"'
        )
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-agreement-revision"] == "3"
    assert api.get("admin").json()["final_sha256"] == digest


@pytest.mark.parametrize("role", ["admin", "customer"])
@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_unavailable_final_pdf_is_never_delivered_as_download(api, role, damage):
    assert api.upload("admin", pdf(), 0).status_code == 200
    assert api.upload("customer", pdf("synthetic signed agreement"), 1).status_code == 200
    assert api.review("approve", 2).status_code == 200
    agreement = api.auth.db.scalar(select(Agreement))
    stored = api.storage.root / agreement.final_pdf_key
    if damage == "missing":
        stored.unlink()
    else:
        stored.write_bytes(pdf("synthetic modified agreement"))
    response = api.get(role, "final")
    assert response.status_code == 503
    assert "content-disposition" not in response.headers
    assert response.headers["content-type"] != "application/pdf"
    assert str(stored) not in response.text
    assert api.get("admin").json()["status"] == "approved"


def test_final_pdf_download_requires_session_role_and_ownership(api):
    signed = pdf("synthetic private agreement")
    assert api.upload("admin", pdf(), 0).status_code == 200
    assert api.upload("customer", signed, 1).status_code == 200
    assert api.review("approve", 2).status_code == 200
    api.auth.client.cookies.clear()
    for role in ("admin", "customer"):
        response = api.auth.client.get(f"/api/{role}/orders/{api.actors.order.id}/agreement/final")
        assert response.status_code == 401
        assert "content-disposition" not in response.headers
        assert signed not in response.content
    api.switch("customer")
    response = api.auth.client.get(f"/api/admin/orders/{api.actors.order.id}/agreement/final")
    assert response.status_code == 403
    api.auth.client.cookies.clear()
    auth_helpers.login_customer(api.auth, email="other@example.ru")
    response = api.auth.client.get(f"/api/customer/orders/{api.actors.order.id}/agreement/final")
    assert response.status_code == 404
    assert "content-disposition" not in response.headers
    assert signed not in response.content
