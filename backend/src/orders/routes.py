import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from supabase import Client

from src.auth.dependencies import AuthenticatedUser, get_current_user
from src.schemas.common import CollectionEnvelope, PaginationMeta, ResourceEnvelope
from src.schemas.orders import CheckoutResponse, OrderCreate, OrderResponse
from src.supabase.client import get_user_supabase_client
from src.supabase.repository import (
    execute,
    get_business_membership,
    paginated_rows,
    require_role,
)


router = APIRouter()
User = Annotated[AuthenticatedUser, Depends(get_current_user)]
Database = Annotated[Client, Depends(get_user_supabase_client)]
ORDER_FIELDS = (
    "id,business_id,customer_name,customer_email,status,payment_status,"
    "amount_minor,currency,created_at,updated_at"
)
ORDER_STATUSES = Literal["pending", "confirmed", "processing", "completed", "cancelled", "refunded"]
PAYMENT_STATUSES = Literal["unpaid", "pending", "paid", "failed", "partially_refunded", "refunded"]


def _read_order(
    client: Client,
    business_id: UUID,
    order_id: UUID,
) -> OrderResponse:
    order = execute(
        client.table("orders")
        .select(ORDER_FIELDS)
        .eq("business_id", str(business_id))
        .eq("id", str(order_id))
        .maybe_single()
    )
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested resource was not found."},
        )
    items = execute(
        client.table("order_items")
        .select("id,product_id,product_name,quantity,unit_price_minor,total_minor")
        .eq("business_id", str(business_id))
        .eq("order_id", str(order_id))
        .order("id")
    )
    return OrderResponse(**order, items=items)


@router.get(
    "/businesses/{business_id}/orders",
    response_model=CollectionEnvelope[OrderResponse],
)
def list_orders(
    business_id: UUID,
    request: Request,
    user: User,
    client: Database,
    status_filter: ORDER_STATUSES | None = Query(default=None, alias="status"),
    payment_status: PAYMENT_STATUSES | None = None,
    q: str | None = Query(default=None, max_length=160),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
) -> CollectionEnvelope[OrderResponse]:
    get_business_membership(client, business_id, user.id)
    if from_ and to and from_ > to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "validation_error", "message": "The request could not be completed."},
        )
    query = client.table("orders").select(ORDER_FIELDS).eq("business_id", str(business_id))
    if status_filter:
        query = query.eq("status", status_filter)
    if payment_status:
        query = query.eq("payment_status", payment_status)
    if q:
        query = query.ilike("customer_name", f"%{q}%")
    if from_:
        query = query.gte("created_at", from_.isoformat())
    if to:
        query = query.lte("created_at", to.isoformat())
    rows, next_cursor, has_more = paginated_rows(query, cursor=cursor, limit=limit)
    items = []
    for row in rows:
        order_lines = execute(
            client.table("order_items")
            .select("id,product_id,product_name,quantity,unit_price_minor,total_minor")
            .eq("business_id", str(business_id))
            .eq("order_id", row["id"])
            .order("id")
        )
        items.append(OrderResponse(**row, items=order_lines))
    return CollectionEnvelope(
        data=items,
        meta=PaginationMeta(next_cursor=next_cursor, has_more=has_more),
        request_id=request.state.request_id,
    )


@router.post(
    "/businesses/{business_id}/orders",
    status_code=status.HTTP_201_CREATED,
    response_model=ResourceEnvelope[OrderResponse],
)
def create_order(
    business_id: UUID,
    body: OrderCreate,
    request: Request,
    user: User,
    client: Database,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ResourceEnvelope[OrderResponse]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin", "staff"})
    if idempotency_key is None or not idempotency_key.strip() or len(idempotency_key) > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "idempotency_key_required", "message": "A valid Idempotency-Key header is required."},
        )
    payload = body.model_dump(mode="json")
    request_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    row = execute(
        client.rpc(
            "create_order_from_cart",
            {
                "target_business_id": str(business_id),
                "customer_name": body.customer_name,
                "customer_email": str(body.customer_email) if body.customer_email else None,
                "requested_currency": body.currency,
                "requested_items": [
                    {"product_id": str(item.product_id), "quantity": item.quantity}
                    for item in body.items
                ],
                "request_idempotency_key": idempotency_key,
                "request_hash": request_hash,
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
    order = _read_order(client, business_id, UUID(row["id"]))
    return ResourceEnvelope(data=order, request_id=request.state.request_id)


@router.get(
    "/businesses/{business_id}/orders/{order_id}",
    response_model=ResourceEnvelope[OrderResponse],
)
def get_order(
    business_id: UUID,
    order_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[OrderResponse]:
    get_business_membership(client, business_id, user.id)
    return ResourceEnvelope(
        data=_read_order(client, business_id, order_id),
        request_id=request.state.request_id,
    )


@router.post(
    "/businesses/{business_id}/orders/{order_id}/checkout",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ResourceEnvelope[CheckoutResponse],
    openapi_extra={"x-implementation-status": "approval-flow implemented; PayPal adapter planned"},
)
def create_checkout(
    business_id: UUID,
    order_id: UUID,
    request: Request,
    user: User,
    client: Database,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ResourceEnvelope[CheckoutResponse]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin", "staff"})
    if idempotency_key is None or not idempotency_key.strip() or len(idempotency_key) > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "idempotency_key_required", "message": "A valid Idempotency-Key header is required."},
        )
    order = execute(
        client.table("orders")
        .select("id,status,payment_status,amount_minor,currency")
        .eq("business_id", str(business_id))
        .eq("id", str(order_id))
        .maybe_single()
    )
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested resource was not found."},
        )
    if order["status"] != "pending" or order["payment_status"] != "unpaid":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "order_not_checkout_eligible", "message": "The order cannot be checked out."},
        )
    config = execute(
        client.table("agent_configs")
        .select("approval_policy")
        .eq("business_id", str(business_id))
        .maybe_single()
    )
    policy = (config or {}).get("approval_policy", {})
    threshold = policy.get("checkout_threshold_minor")
    approval_required = policy.get("require_approval_for_checkout", True) and (
        threshold is None
        or (
            order["currency"] == policy.get("currency", order["currency"])
            and order["amount_minor"] >= threshold
        )
    )
    if approval_required:
        existing = execute(
            client.table("approvals")
            .select("id,status,impact")
            .eq("business_id", str(business_id))
            .eq("request_idempotency_key", idempotency_key)
            .maybe_single()
        )
        if existing:
            if existing.get("impact", {}).get("order_id") != str(order_id):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "idempotency_conflict", "message": "The idempotency key has already been used."},
                )
            if existing["status"] != "pending":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "approval_already_decided", "message": "The approval request is no longer pending."},
                )
            approval_id = existing["id"]
        else:
            approval = execute(
                client.table("approvals")
                .insert(
                    {
                        "business_id": str(business_id),
                        "action_type": "create_paypal_checkout",
                        "status": "pending",
                        "impact": {
                            "order_id": str(order_id),
                            "amount_minor": order["amount_minor"],
                            "currency": order["currency"],
                        },
                        "expires_at": (
                            datetime.now(timezone.utc) + timedelta(minutes=15)
                        ).isoformat(),
                        "requested_by": str(user.id),
                        "request_idempotency_key": idempotency_key,
                    }
                )
                .select("id")
                .single()
            )
            approval_id = approval["id"]
            execute(
                client.table("outbox_events").insert(
                    {
                        "business_id": str(business_id),
                        "event_type": "approval.created",
                        "topic": "approvals",
                        "data": {"approval_id": approval_id},
                    }
                )
            )
        return ResourceEnvelope(
            data=CheckoutResponse(
                order_id=order_id,
                provider="paypal",
                status="approval_required",
                approval_id=approval_id,
                amount_minor=order["amount_minor"],
                currency=order["currency"],
            ),
            request_id=request.state.request_id,
        )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "paypal_unavailable", "message": "Customer checkout is not available right now."},
    )


@router.post(
    "/businesses/{business_id}/orders/{order_id}/cancel",
    response_model=ResourceEnvelope[OrderResponse],
)
def cancel_order(
    business_id: UUID,
    order_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[OrderResponse]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin", "staff"})
    row = execute(
        client.rpc(
            "cancel_unpaid_order",
            {
                "target_business_id": str(business_id),
                "target_order_id": str(order_id),
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
        data=_read_order(client, business_id, order_id),
        request_id=request.state.request_id,
    )
