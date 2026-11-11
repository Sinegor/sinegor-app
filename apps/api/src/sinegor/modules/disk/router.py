from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response

from sinegor.db.types import AgreementStatus
from sinegor.integrations.yandex_disk.client import DiskError
from sinegor.modules.auth.dependencies import Admin, Customer, Database, OwnedOrder
from sinegor.modules.disk import service
from sinegor.modules.disk.schemas import (
    AttachFolder,
    CreateFolder,
    CustomerFolderRead,
    DeleteFolder,
    FolderLink,
    FolderRead,
)
from sinegor.modules.notifications.service import deliver_from_app
from sinegor.modules.orders.models import Order
from sinegor.modules.orders.service import locked_order, record_event

router = APIRouter(tags=["disk"])


@router.post("/admin/orders/{order_id}/folder", response_model=FolderRead)
def create_folder(
    order_id: UUID,
    request: Request,
    principal: Admin,
    db: Database,
    payload: CreateFolder | None = None,
):
    return service.provision(
        db,
        request.app.state.yandex_disk,
        order_id,
        principal.id,
        name_base=(payload.name_base if payload else "Заказ"),
    )


@router.put("/admin/orders/{order_id}/folder", response_model=FolderRead)
def attach_folder(
    order_id: UUID, payload: AttachFolder, request: Request, principal: Admin, db: Database
):
    return service.provision(
        db, request.app.state.yandex_disk, order_id, principal.id, payload.disk_path
    )


@router.get("/admin/orders/{order_id}/folder", response_model=FolderRead)
def read_folder(order_id: UUID, principal: Admin, db: Database):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    return service.folder_for(db, order)


@router.get("/admin/orders/{order_id}/folder/open")
def open_folder(order_id: UUID, principal: Admin, db: Database):
    return {"folder_url": service.admin_url(read_folder(order_id, principal, db))}


@router.put("/admin/orders/{order_id}/folder/link", response_model=FolderRead)
def set_folder_link(order_id: UUID, payload: FolderLink, principal: Admin, db: Database):
    order = locked_order(db, order_id)
    folder = service.folder_for(db, order)
    service.admin_url(folder)
    if folder.folder_url != payload.folder_url:
        folder.folder_url = payload.folder_url
        record_event(db, order, "disk_folder_link_updated", principal.id)
        db.commit()
    return folder


@router.get("/customer/orders/{order_id}/folder", response_model=CustomerFolderRead)
def customer_folder(request: Request, principal: Customer, owned: OwnedOrder, db: Database):
    if owned.agreement is None or owned.agreement.status != AgreementStatus.APPROVED:
        request.state.security_reason = "agreement_required"
        raise HTTPException(404, "Order folder not available")
    folder = service.folder_for(db, owned)
    if (
        not folder.folder_url
        or folder.deleted_at
        or folder.deletion_operation_id
        or folder.deletion_succeeded
    ):
        raise HTTPException(404, "Order folder not available")
    return CustomerFolderRead(folder_url=folder.folder_url)


@router.post("/admin/orders/{order_id}/folder/delete", response_model=FolderRead)
def delete_folder(
    order_id: UUID,
    payload: DeleteFolder,
    request: Request,
    response: Response,
    tasks: BackgroundTasks,
    principal: Admin,
    db: Database,
):
    notification_ids: list[UUID] = []
    folder = service.delete_folder(
        db,
        request.app.state.yandex_disk,
        order_id,
        payload.deletion_request_id,
        principal.id,
        permanent_deletion_verified=payload.permanent_deletion_verified,
        notification_ids=notification_ids,
    )
    for identifier in notification_ids:
        tasks.add_task(deliver_from_app, request.app, identifier)
    if folder.deleted_at is None:
        response.status_code = 202
    return folder


async def disk_error(request: Request, exc: DiskError):
    from sinegor.api.errors import error_response

    return error_response(request, exc.status_code, exc.code, str(exc))
