from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import Text, cast, or_, select

from sinegor.modules.auth.dependencies import Admin, Database
from sinegor.modules.destruction import service
from sinegor.modules.destruction.models import DestructionOperation
from sinegor.modules.retention.archive import RetentionArchive

router = APIRouter(prefix="/admin/destructions", tags=["destruction"])


class DestructionRead(BaseModel):
    id: UUID
    kind: str
    state: str
    subject: str
    created_at: datetime
    destroyed_at: datetime | None
    expires_at: datetime | None
    error_code: str | None
    act_url: str | None
    extract_url: str | None
    metadata_json: dict


def present(operation: DestructionOperation) -> DestructionRead:
    base = f"/api/admin/destructions/{operation.id}/documents"
    ready = operation.state == "ready" and operation.expires_at > datetime.now(UTC)
    subject = "; ".join(s.get("identity", "") for s in operation.metadata_json.get("subjects", []))
    return DestructionRead(
        id=operation.id,
        kind=operation.kind,
        state=operation.state,
        subject=subject,
        created_at=operation.created_at,
        destroyed_at=operation.destroyed_at,
        expires_at=operation.expires_at,
        error_code=operation.error_code,
        act_url=base + "/act" if ready else None,
        extract_url=base + "/extract" if ready else None,
        metadata_json=operation.metadata_json,
    )


def get_operation(db, identifier):
    op = db.get(DestructionOperation, identifier)
    if op is None:
        raise HTTPException(404, "Destruction operation not found")
    return op


@router.get("", response_model=list[DestructionRead])
def list_operations(
    principal: Admin,
    db: Database,
    q: Annotated[str | None, Query(max_length=320)] = None,
    kind: Annotated[str | None, Query(max_length=40)] = None,
    state: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    stmt = select(DestructionOperation)
    if q and q.strip():
        stmt = stmt.where(
            or_(
                cast(DestructionOperation.id, Text).icontains(q.strip(), autoescape=True),
                cast(DestructionOperation.metadata_json, Text).icontains(
                    q.strip(), autoescape=True
                ),
            )
        )
    if kind:
        stmt = stmt.where(DestructionOperation.kind == kind)
    if state:
        stmt = stmt.where(DestructionOperation.state == state)
    return [
        present(op)
        for op in db.scalars(
            stmt.order_by(DestructionOperation.created_at.desc(), DestructionOperation.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ]


@router.get("/{identifier}", response_model=DestructionRead)
def read_operation(identifier: UUID, principal: Admin, db: Database):
    return present(get_operation(db, identifier))


@router.post("/{identifier}/documents", response_model=DestructionRead)
def form_documents(identifier: UUID, principal: Admin, db: Database, request: Request):
    get_operation(db, identifier)
    try:
        op = service.generate(
            db, identifier, RetentionArchive(request.app.state.settings.destruction_archive_dir)
        )
    except ValueError as exc:
        raise HTTPException(
            409, "Destruction is unconfirmed or document retention expired"
        ) from exc
    db.commit()
    return present(op)


@router.get("/{identifier}/documents/{document}")
def read_document(
    identifier: UUID,
    document: Literal["act", "extract"],
    principal: Admin,
    db: Database,
    request: Request,
    download: bool = False,
):
    op = get_operation(db, identifier)
    if op.state != "ready" or op.expires_at <= datetime.now(UTC):
        raise HTTPException(409, "Documents are not available")
    try:
        data = RetentionArchive(request.app.state.settings.destruction_archive_dir).read(
            op.bundle_key,
            "journal_export.pdf"
            if document == "extract" and "/" in op.bundle_key
            else document + ".pdf",
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(409, "Document integrity verification failed") from exc
    disposition = "attachment" if download else "inline"
    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disposition}; filename="{document}-{op.id}.pdf"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
