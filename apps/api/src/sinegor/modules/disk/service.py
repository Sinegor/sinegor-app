"""Order folder ownership and deletion evidence stay in the business backend."""

from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sinegor.db.types import DeletionReason, DeletionStatus, OrderStatus
from sinegor.integrations.yandex_disk.client import (
    DiskConflict,
    DiskError,
    DiskFolderNotFound,
    Resource,
    YandexDisk,
)
from sinegor.integrations.yandex_disk.paths import folder_url, overlaps
from sinegor.modules.disk.models import DiskFolder
from sinegor.modules.orders.models import Order
from sinegor.modules.orders.service import locked_order, record_event
from sinegor.modules.retention.models import DeletionRequest


def folder_for(db: Session, order: Order) -> DiskFolder:
    folder = db.scalar(
        select(DiskFolder)
        .where(DiskFolder.order_id == order.id)
        .execution_options(populate_existing=True)
    )
    if folder is None:
        raise HTTPException(404, "Order folder not found")
    return folder


def binding_lock(db: Session) -> None:
    # Low-volume admin actions: serialize bindings to prevent cross-order nested paths.
    db.execute(select(func.pg_advisory_xact_lock(217006)))


def available_path(
    db: Session, path: str, resource_id: str | None = None, *, exclude_id: UUID | None = None
) -> None:
    folders = db.scalars(select(DiskFolder)).all()
    if any(
        overlaps(path, folder.disk_path)
        or resource_id is not None
        and resource_id == folder.resource_id
        for folder in folders
        if folder.id != exclude_id
    ):
        raise HTTPException(409, "Folder overlaps another order binding")


def bind(db: Session, order: Order, resource: Resource, admin_id: UUID) -> DiskFolder:
    available_path(db, resource.path, resource.resource_id)
    folder = DiskFolder(
        order_id=order.id, disk_path=resource.path, resource_id=resource.resource_id
    )
    db.add(folder)
    record_event(db, order, "disk_folder_bound", admin_id)
    db.commit()
    return folder


def provision(
    db: Session,
    disk: YandexDisk,
    order_id: UUID,
    admin_id: UUID,
    path: str | None = None,
    *,
    name_base: str = "Заказ",
) -> DiskFolder:
    order = locked_order(db, order_id)
    binding_lock(db)
    current = db.scalar(select(DiskFolder).where(DiskFolder.order_id == order.id))
    if current is not None:
        if current.deleted_at or path is not None and path != current.disk_path:
            raise HTTPException(409, "Order already has a folder binding")
        if path is not None:
            disk.path(path)
            resource = disk.metadata(path)
            if resource is None:
                raise DiskFolderNotFound("Disk folder not found")
            if current.resource_id is not None and current.resource_id != resource.resource_id:
                raise HTTPException(409, "Folder identity has changed")
            available_path(db, path, resource.resource_id, exclude_id=current.id)
            if current.resource_id is None:
                current.resource_id = resource.resource_id
                record_event(db, order, "disk_folder_identity_verified", admin_id)
                db.commit()
        return current
    if order.status in {OrderStatus.COMPLETED, OrderStatus.CANCELLED}:
        raise HTTPException(409, "Closed orders cannot receive a folder")
    today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    name = f"{name_base or 'Заказ'}_{order.number:03d}_{today:%Y-%m-%d}"
    target = disk.path(path if path is not None else f"{disk.root}/{name}")
    available_path(db, target)
    resource = disk.metadata(target) if path is not None else disk.create(target)
    if resource is None:
        raise DiskFolderNotFound("Disk folder not found")
    return bind(db, order, resource, admin_id)


def admin_url(folder: DiskFolder) -> str:
    if folder.deleted_at or folder.deletion_operation_id or folder.deletion_succeeded:
        raise HTTPException(409, "Folder is deleted or being deleted")
    return folder_url(folder.disk_path)


def delete_folder(
    db: Session,
    disk: YandexDisk,
    order_id: UUID,
    request_id: UUID,
    admin_id: UUID,
    *,
    permanent_deletion_verified: bool = False,
) -> DiskFolder:
    order = locked_order(db, order_id)
    binding_lock(db)
    folder = folder_for(db, order)
    deletion = db.scalar(
        select(DeletionRequest)
        .where(DeletionRequest.id == request_id, DeletionRequest.order_id == order.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if deletion is None:
        raise HTTPException(409, "A confirmed deletion request for this order is required")
    if folder.deleted_at and deletion.status == DeletionStatus.PERFORMED:
        return folder
    now = datetime.now(UTC)
    if (
        deletion.status not in {DeletionStatus.CONFIRMED, DeletionStatus.ERROR}
        or deletion.confirmed_at is None
        or deletion.confirmed_by_id is None
        or deletion.confirmed_at > now
        or order.result_notified_at is None
        or order.status not in {OrderStatus.RESULT_READY, OrderStatus.COMPLETED}
        or deletion.deferred_until is not None
        and deletion.deferred_until > now
        or deletion.reason == DeletionReason.RETENTION_EXPIRED
        and (now < deletion.due_at or now < order.result_notified_at + timedelta(days=14))
        or deletion.reason == DeletionReason.EARLY_PERMISSION
        and (
            deletion.early_authorized_at is None
            or deletion.early_authorized_at < order.result_notified_at
            or deletion.early_authorized_at > now
        )
    ):
        raise HTTPException(409, "Deletion request is not eligible for execution")
    disk.path(folder.disk_path)
    available_path(db, folder.disk_path, folder.resource_id, exclude_id=folder.id)
    if not folder.resource_id:
        raise HTTPException(409, "Folder identity must be verified before deletion")
    if permanent_deletion_verified and not folder.deletion_succeeded:
        if folder.deletion_started_at is None or folder.deletion_operation_id:
            raise HTTPException(409, "No uncertain deletion attempt to verify")
        if disk.metadata(folder.disk_path) is not None:
            raise HTTPException(409, "Disk folder still exists; deletion cannot be confirmed")
        folder.deletion_succeeded = True
        record_event(db, order, "disk_deletion_manually_verified", admin_id)
        db.commit()
        return delete_folder(db, disk, order_id, request_id, admin_id)
    if (
        folder.deletion_started_at is None
        and not folder.deletion_operation_id
        and not folder.deletion_succeeded
    ):
        resource = disk.metadata(folder.disk_path)
        if resource is None or resource.resource_id != folder.resource_id:
            raise DiskConflict("Folder is missing or its identity has changed")
        folder.deletion_started_at = datetime.now(UTC)
        record_event(db, order, "disk_deletion_started", admin_id)
        # Durable intent survives a lost DELETE response or a later commit failure.
        db.commit()
        return delete_folder(db, disk, order_id, request_id, admin_id)
    recheck = False
    try:
        if folder.deletion_succeeded:
            pass
        elif folder.deletion_operation_id:
            status = disk.operation(folder.deletion_operation_id)
            if status == "failed":
                folder.deletion_operation_id = None
                raise DiskError("Disk deletion failed; retry after checking the folder")
            if status == "in-progress":
                return folder
        else:
            folder.deletion_operation_id = disk.delete(folder.disk_path, folder.resource_id)
            if folder.deletion_operation_id:
                db.commit()
                return folder
        if not folder.deletion_succeeded:
            folder.deletion_succeeded = True
            db.commit()
            recheck = True
        elif disk.metadata(folder.disk_path) is not None:
            raise DiskError("Disk folder deletion is not yet verified")
    except DiskError:
        deletion.status = DeletionStatus.ERROR
        record_event(db, order, "disk_deletion_failed", admin_id)
        db.commit()
        raise
    if recheck:
        # Reacquire locks and revalidate eligibility after persisting upstream success.
        return delete_folder(db, disk, order_id, request_id, admin_id)
    folder.deleted_at = datetime.now(UTC)
    deletion.status = DeletionStatus.PERFORMED
    deletion.performed_at = folder.deleted_at
    record_event(db, order, "disk_folder_deleted", admin_id)
    db.commit()
    return folder
