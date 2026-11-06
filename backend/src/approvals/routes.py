from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from supabase import Client

from src.auth.dependencies import AuthenticatedUser, get_current_user
from src.schemas.approvals import ApprovalDecisionCreate, ApprovalResponse
from src.schemas.common import CollectionEnvelope, PaginationMeta, ResourceEnvelope
from src.supabase.client import get_user_supabase_client
from src.supabase.repository import (
    execute,
    get_business_membership,
    paginated_rows,
)


router = APIRouter()
User = Annotated[AuthenticatedUser, Depends(get_current_user)]
Database = Annotated[Client, Depends(get_user_supabase_client)]
APPROVAL_FIELDS = (
    "id,business_id,action_type,status,impact,expires_at,decided_by,decided_at,"
    "decision_note,created_at"
)


@router.get(
    "/businesses/{business_id}/approvals",
    response_model=CollectionEnvelope[ApprovalResponse],
)
def list_approvals(
    business_id: UUID,
    request: Request,
    user: User,
    client: Database,
    status_filter: Literal["pending", "approved", "rejected", "expired", "cancelled"] | None = Query(
        default=None, alias="status"
    ),
    action_type: str | None = Query(default=None, max_length=120),
    cursor: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
) -> CollectionEnvelope[ApprovalResponse]:
    get_business_membership(client, business_id, user.id)
    query = client.table("approvals").select(APPROVAL_FIELDS).eq("business_id", str(business_id))
    if status_filter:
        query = query.eq("status", status_filter)
    if action_type:
        query = query.eq("action_type", action_type)
    rows, next_cursor, has_more = paginated_rows(query, cursor=cursor, limit=limit)
    return CollectionEnvelope(
        data=rows,
        meta=PaginationMeta(next_cursor=next_cursor, has_more=has_more),
        request_id=request.state.request_id,
    )


@router.get(
    "/businesses/{business_id}/approvals/{approval_id}",
    response_model=ResourceEnvelope[ApprovalResponse],
)
def get_approval(
    business_id: UUID,
    approval_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[ApprovalResponse]:
    get_business_membership(client, business_id, user.id)
    approval = execute(
        client.table("approvals")
        .select(APPROVAL_FIELDS)
        .eq("business_id", str(business_id))
        .eq("id", str(approval_id))
        .maybe_single()
    )
    if not approval:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested resource was not found."},
        )
    return ResourceEnvelope(data=ApprovalResponse(**approval), request_id=request.state.request_id)


@router.post(
    "/businesses/{business_id}/approvals/{approval_id}/decision",
    response_model=ResourceEnvelope[ApprovalResponse],
)
def decide_approval(
    business_id: UUID,
    approval_id: UUID,
    body: ApprovalDecisionCreate,
    request: Request,
    user: User,
    client: Database,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ResourceEnvelope[ApprovalResponse]:
    get_business_membership(client, business_id, user.id)
    if idempotency_key is None or not idempotency_key.strip() or len(idempotency_key) > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "idempotency_key_required", "message": "A valid Idempotency-Key header is required."},
        )
    row = execute(
        client.rpc(
            "decide_approval",
            {
                "target_business_id": str(business_id),
                "target_approval_id": str(approval_id),
                "requested_decision": body.decision,
                "requested_note": body.note,
                "requested_idempotency_key": idempotency_key,
            },
        )
    )
    if isinstance(row, list):
        row = row[0] if row else None
    if not isinstance(row, dict):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "database_unavailable", "message": "The request could not be completed right now."},
        )
    return ResourceEnvelope(
        data=ApprovalResponse(**row),
        request_id=request.state.request_id,
    )
