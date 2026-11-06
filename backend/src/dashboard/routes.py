from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from supabase import Client

from src.auth.dependencies import AuthenticatedUser, get_current_user
from src.schemas.common import CollectionEnvelope, PaginationMeta, ResourceEnvelope
from src.schemas.dashboard import (
    AuditEventResponse,
    DashboardSummaryResponse,
    NotificationResponse,
    SetupChecklistItem,
    SetupChecklistResponse,
)
from src.supabase.client import get_user_supabase_client
from src.supabase.repository import (
    count_rows,
    execute,
    get_business_membership,
    paginated_rows,
)


router = APIRouter()
User = Annotated[AuthenticatedUser, Depends(get_current_user)]
Database = Annotated[Client, Depends(get_user_supabase_client)]


@router.get(
    "/businesses/{business_id}/dashboard/summary",
    response_model=ResourceEnvelope[DashboardSummaryResponse],
)
def get_dashboard_summary(
    business_id: UUID,
    request: Request,
    user: User,
    client: Database,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
) -> ResourceEnvelope[DashboardSummaryResponse]:
    get_business_membership(client, business_id, user.id)
    if from_ and to and from_ > to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "validation_error", "message": "The request could not be completed."},
        )
    conversations_query = client.table("conversations").select("id", count="exact", head=True).eq(
        "business_id", str(business_id)
    )
    orders_query = client.table("orders").select("id", count="exact", head=True).eq(
        "business_id", str(business_id)
    )
    approvals_query = (
        client.table("approvals")
        .select("id", count="exact", head=True)
        .eq("business_id", str(business_id))
        .eq("status", "pending")
    )
    if from_:
        conversations_query = conversations_query.gte("created_at", from_.isoformat())
        orders_query = orders_query.gte("created_at", from_.isoformat())
        approvals_query = approvals_query.gte("created_at", from_.isoformat())
    if to:
        conversations_query = conversations_query.lte("created_at", to.isoformat())
        orders_query = orders_query.lte("created_at", to.isoformat())
        approvals_query = approvals_query.lte("created_at", to.isoformat())
    conversation_count = count_rows(conversations_query)
    order_count = count_rows(orders_query)
    approval_count = count_rows(approvals_query)
    agent = execute(
        client.table("agent_configs")
        .select("status")
        .eq("business_id", str(business_id))
        .maybe_single()
    )
    recent_conversations = execute(
        client.table("conversations")
        .select("id,channel,status,last_message_at")
        .eq("business_id", str(business_id))
        .order("last_message_at", desc=True)
        .limit(5)
    )
    recent_orders = execute(
        client.table("orders")
        .select("id,status,payment_status,amount_minor,currency,created_at")
        .eq("business_id", str(business_id))
        .order("created_at", desc=True)
        .limit(5)
    )
    pending_approvals = execute(
        client.table("approvals")
        .select("id,action_type,status,expires_at,created_at")
        .eq("business_id", str(business_id))
        .eq("status", "pending")
        .order("created_at", desc=True)
        .limit(5)
    )
    result = DashboardSummaryResponse(
        metrics={
            "conversations": conversation_count,
            "orders": order_count,
            "pending_approvals": approval_count,
        },
        agent_status=(agent or {}).get("status", "disabled"),
        recent_conversations=recent_conversations,
        recent_orders=recent_orders,
        pending_approvals=pending_approvals,
    )
    return ResourceEnvelope(data=result, request_id=request.state.request_id)


@router.get(
    "/businesses/{business_id}/dashboard/setup",
    response_model=ResourceEnvelope[SetupChecklistResponse],
)
def get_setup(
    business_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[SetupChecklistResponse]:
    get_business_membership(client, business_id, user.id)
    integrations = count_rows(
        client.table("integrations")
        .select("id", count="exact", head=True)
        .eq("business_id", str(business_id))
        .eq("status", "connected")
    )
    products = count_rows(
        client.table("products")
        .select("id", count="exact", head=True)
        .eq("business_id", str(business_id))
        .eq("status", "active")
    )
    agent = execute(
        client.table("agent_configs")
        .select("enabled")
        .eq("business_id", str(business_id))
        .maybe_single()
    )
    items = [
        SetupChecklistItem(
            key="product_catalog",
            label="Add a product to your catalog",
            status="complete" if products else "not_started",
            action_url=None if products else f"/businesses/{business_id}/products",
        ),
        SetupChecklistItem(
            key="integration",
            label="Connect a commerce or messaging integration",
            status="complete" if integrations else "not_started",
            action_url=None if integrations else f"/businesses/{business_id}/integrations",
        ),
        SetupChecklistItem(
            key="business_agent",
            label="Configure the Business Agent",
            status="complete" if (agent or {}).get("enabled") else "not_started",
            action_url=None if (agent or {}).get("enabled") else f"/businesses/{business_id}/agent",
        ),
    ]
    return ResourceEnvelope(
        data=SetupChecklistResponse(items=items),
        request_id=request.state.request_id,
    )


@router.get(
    "/businesses/{business_id}/audit-events",
    response_model=CollectionEnvelope[AuditEventResponse],
)
def list_audit_events(
    business_id: UUID,
    request: Request,
    user: User,
    client: Database,
    cursor: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    actor: UUID | None = None,
    event_type: str | None = Query(default=None, max_length=120),
    resource_type: str | None = Query(default=None, max_length=120),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
) -> CollectionEnvelope[AuditEventResponse]:
    get_business_membership(client, business_id, user.id)
    if from_ and to and from_ > to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "validation_error", "message": "The request could not be completed."},
        )
    query = client.table("audit_events").select("*").eq("business_id", str(business_id))
    if actor:
        query = query.eq("actor_id", str(actor))
    if event_type:
        query = query.eq("event_type", event_type)
    if resource_type:
        query = query.eq("resource_type", resource_type)
    if from_:
        query = query.gte("created_at", from_.isoformat())
    if to:
        query = query.lte("created_at", to.isoformat())
    rows, next_cursor, has_more = paginated_rows(query, cursor=cursor, limit=limit)
    return CollectionEnvelope(
        data=rows,
        meta=PaginationMeta(next_cursor=next_cursor, has_more=has_more),
        request_id=request.state.request_id,
    )


@router.get(
    "/businesses/{business_id}/notifications",
    response_model=CollectionEnvelope[NotificationResponse],
)
def list_notifications(
    business_id: UUID,
    request: Request,
    user: User,
    client: Database,
    cursor: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
) -> CollectionEnvelope[NotificationResponse]:
    get_business_membership(client, business_id, user.id)
    rows, next_cursor, has_more = paginated_rows(
        client.table("notifications")
        .select("id,type,title,body,data,read_at,created_at")
        .eq("business_id", str(business_id)),
        cursor=cursor,
        limit=limit,
    )
    return CollectionEnvelope(
        data=rows,
        meta=PaginationMeta(next_cursor=next_cursor, has_more=has_more),
        request_id=request.state.request_id,
    )


@router.post(
    "/businesses/{business_id}/notifications/{notification_id}/read",
    response_model=ResourceEnvelope[NotificationResponse],
)
def mark_notification_read(
    business_id: UUID,
    notification_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[NotificationResponse]:
    get_business_membership(client, business_id, user.id)
    notification = execute(
        client.table("notifications")
        .update({"read_at": datetime.now().astimezone().isoformat()})
        .eq("business_id", str(business_id))
        .eq("id", str(notification_id))
        .select("id,type,title,body,data,read_at,created_at")
        .maybe_single()
    )
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested resource was not found."},
        )
    return ResourceEnvelope(
        data=NotificationResponse(**notification),
        request_id=request.state.request_id,
    )
