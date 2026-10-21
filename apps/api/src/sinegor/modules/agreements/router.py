from contextlib import contextmanager
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from sinegor.modules.agreements import service
from sinegor.modules.agreements.schemas import AgreementRead, RejectionInput, ReviewInput
from sinegor.modules.agreements.storage import AgreementStorageError
from sinegor.modules.auth.dependencies import Admin, Customer, Database, OwnedOrder, Principal
from sinegor.modules.notifications.service import deliver_order_from_app
from sinegor.modules.orders.models import Order
from sinegor.modules.orders.service import locked_order, record_event

router = APIRouter(tags=["agreements"])
Revision = Annotated[int, Header(alias="X-Agreement-Revision", ge=0)]
Kind = Literal["initial", "returned", "final"]
PDF_BODY = {
    "requestBody": {
        "required": True,
        "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
    }
}
PDF_RESPONSE = {
    200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}
}


@contextmanager
def storage_errors():
    try:
        yield
    except AgreementStorageError as exc:
        raise HTTPException(503, "Agreement storage is unavailable") from exc


def require_order(db: Database, order_id: UUID) -> Order:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    return order


async def pdf_body(request: Request) -> bytes:
    if request.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/pdf":
        raise HTTPException(415, "Use Content-Type: application/pdf")
    limit = request.app.state.settings.agreement_max_bytes
    declared = request.headers.get("Content-Length")
    if declared is not None:
        try:
            length = int(declared)
            if length < 0:
                raise ValueError
        except ValueError as exc:
            raise HTTPException(400, "Invalid Content-Length") from exc
        if length > limit:
            raise HTTPException(413, "Agreement PDF is too large")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > limit:
            raise HTTPException(413, "Agreement PDF is too large")
        data.extend(chunk)
    return bytes(data)


@router.get("/admin/orders/{order_id}/agreement", response_model=AgreementRead)
def admin_metadata(order_id: UUID, principal: Admin, db: Database):
    require_order(db, order_id)
    return AgreementRead.from_agreement(service.get_agreement(db, order_id))


@router.get("/customer/orders/{order_id}/agreement", response_model=AgreementRead)
def customer_metadata(order: OwnedOrder, db: Database):
    return AgreementRead.from_agreement(service.get_agreement(db, order.id))


@router.post(
    "/admin/orders/{order_id}/agreement/initial",
    response_model=AgreementRead,
    openapi_extra=PDF_BODY,
)
async def upload_initial(
    order_id: UUID,
    request: Request,
    principal: Admin,
    db: Database,
    revision: Revision,
    tasks: BackgroundTasks,
):
    await run_in_threadpool(require_order, db, order_id)
    # Authorization only read data; return its connection before receiving/parsing the PDF.
    await run_in_threadpool(db.rollback)
    data = await pdf_body(request)
    with storage_errors():
        agreement = await run_in_threadpool(
            service.upload,
            db,
            request.app.state.agreement_storage,
            order_id,
            data,
            revision,
            principal.id,
            initial=True,
        )
    result = AgreementRead.from_agreement(agreement)
    tasks.add_task(deliver_order_from_app, request.app, order_id)
    return result


@router.post(
    "/customer/orders/{order_id}/agreement/returned",
    response_model=AgreementRead,
    openapi_extra=PDF_BODY,
)
async def upload_returned(
    request: Request,
    principal: Customer,
    order: OwnedOrder,
    db: Database,
    revision: Revision,
    tasks: BackgroundTasks,
):
    order_id = order.id  # Rollback expires ORM instances; keep the scalar before releasing the DB.
    await run_in_threadpool(db.rollback)
    data = await pdf_body(request)
    with storage_errors():
        agreement = await run_in_threadpool(
            service.upload,
            db,
            request.app.state.agreement_storage,
            order_id,
            data,
            revision,
            principal.id,
            initial=False,
        )
    result = AgreementRead.from_agreement(agreement)
    tasks.add_task(deliver_order_from_app, request.app, order_id)
    return result


@router.post("/admin/orders/{order_id}/agreement/approve", response_model=AgreementRead)
def approve(
    order_id: UUID,
    payload: ReviewInput,
    request: Request,
    principal: Admin,
    db: Database,
    tasks: BackgroundTasks,
):
    with storage_errors():
        agreement = service.review(
            db, request.app.state.agreement_storage, order_id, payload.revision, principal.id
        )
    result = AgreementRead.from_agreement(agreement)
    tasks.add_task(deliver_order_from_app, request.app, order_id)
    return result


@router.post("/admin/orders/{order_id}/agreement/reject", response_model=AgreementRead)
def reject(
    order_id: UUID,
    payload: RejectionInput,
    request: Request,
    principal: Admin,
    db: Database,
    tasks: BackgroundTasks,
):
    with storage_errors():
        agreement = service.review(
            db,
            request.app.state.agreement_storage,
            order_id,
            payload.revision,
            principal.id,
            reason=payload.reason,
        )
    result = AgreementRead.from_agreement(agreement)
    tasks.add_task(deliver_order_from_app, request.app, order_id)
    return result


def download(order_id: UUID, kind: Kind, request: Request, principal: Principal, db: Database):
    order = locked_order(db, order_id)
    agreement = service.get_agreement(db, order_id)
    key = getattr(agreement, f"{kind}_pdf_key")
    if key is None:
        raise HTTPException(404, "Agreement PDF not found")
    with storage_errors():
        data, digest = request.app.state.agreement_storage.read(
            key, getattr(agreement, f"{kind}_sha256")
        )
    revision = agreement.revision
    record_event(
        db,
        order,
        f"agreement_{kind}_downloaded",
        admin_id=principal.id if principal.role == "admin" else None,
        customer_id=principal.id if principal.role == "customer" else None,
    )
    db.commit()
    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="agreement-{order.number}-{kind}.pdf"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "X-Agreement-Revision": str(revision),
            "ETag": f'"{digest}"',
        },
    )


@router.get(
    "/admin/orders/{order_id}/agreement/{kind}", response_class=Response, responses=PDF_RESPONSE
)
def admin_download(order_id: UUID, kind: Kind, request: Request, principal: Admin, db: Database):
    return download(order_id, kind, request, principal, db)


@router.get(
    "/customer/orders/{order_id}/agreement/{kind}", response_class=Response, responses=PDF_RESPONSE
)
def customer_download(
    kind: Kind, request: Request, principal: Customer, order: OwnedOrder, db: Database
):
    return download(order.id, kind, request, principal, db)
