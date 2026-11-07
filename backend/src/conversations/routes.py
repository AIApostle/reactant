from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from supabase import Client

from src.auth.dependencies import AuthenticatedUser, get_current_user
from src.schemas.common import CollectionEnvelope, PaginationMeta, ResourceEnvelope
from src.schemas.conversations import (
    ConversationResponse,
    ConversationUpdate,
    CustomerMessageResponse,
    CustomerReplyCreate,
    HandoffUpdate,
)
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
CONVERSATION_FIELDS = "id,business_id,channel,status,assignee_id,handoff_status,created_at,updated_at"
INBOX_CONVERSATION_FIELDS = (
    f"{CONVERSATION_FIELDS},customer_context,last_message_at"
)
MESSAGE_FIELDS = (
    "id,conversation_id,sender_type,sender_id,text,visibility,delivery_status,created_at"
)


def _customer_name(row: dict) -> str:
    context = row.get("customer_context")
    if isinstance(context, dict):
        name = context.get("customer_name") or context.get("telegram_username")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return "Customer"


def _with_inbox_summary(client: Client, rows: list[dict]) -> list[dict]:
    enriched: list[dict] = []
    for row in rows:
        latest = execute(
            client.table("customer_messages")
            .select("text,created_at,sender_type")
            .eq("business_id", row["business_id"])
            .eq("conversation_id", row["id"])
            .order("created_at", desc=True)
            .limit(1)
        )
        last_message = latest[0] if latest else None
        enriched.append(
            {
                **row,
                "customer_name": _customer_name(row),
                "last_message": (
                    {"text": last_message["text"], "created_at": last_message["created_at"]}
                    if last_message
                    else None
                ),
                "unread": bool(last_message and last_message["sender_type"] == "customer"),
            }
        )
    return [
        {
            key: value
            for key, value in row.items()
            if key not in {"customer_context", "last_message_at"}
        }
        for row in enriched
    ]


def _get_conversation(
    client: Client,
    business_id: UUID,
    conversation_id: UUID,
) -> dict:
    conversation = execute(
        client.table("conversations")
        .select(CONVERSATION_FIELDS)
        .eq("business_id", str(business_id))
        .eq("id", str(conversation_id))
        .maybe_single()
    )
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested resource was not found."},
        )
    return conversation


@router.get(
    "/businesses/{business_id}/conversations",
    response_model=CollectionEnvelope[ConversationResponse],
)
def list_conversations(
    business_id: UUID,
    request: Request,
    user: User,
    client: Database,
    status_filter: Literal["open", "needs_reply", "resolved"] | None = Query(
        default=None, alias="status"
    ),
    channel: str | None = Query(default=None, max_length=80),
    assignee_id: UUID | None = None,
    q: str | None = Query(default=None, max_length=120),
    cursor: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
) -> CollectionEnvelope[ConversationResponse]:
    get_business_membership(client, business_id, user.id)
    query = (
        client.table("conversations")
        .select(INBOX_CONVERSATION_FIELDS)
        .eq("business_id", str(business_id))
    )
    if status_filter:
        query = query.eq("status", status_filter)
    if channel:
        query = query.eq("channel", channel)
    if assignee_id:
        query = query.eq("assignee_id", str(assignee_id))
    if q:
        query = query.ilike("provider_conversation_id", f"%{q}%")
    rows, next_cursor, has_more = paginated_rows(query, cursor=cursor, limit=limit)
    rows = _with_inbox_summary(client, rows)
    return CollectionEnvelope(
        data=rows,
        meta=PaginationMeta(next_cursor=next_cursor, has_more=has_more),
        request_id=request.state.request_id,
    )


@router.get(
    "/businesses/{business_id}/conversations/{conversation_id}",
    response_model=ResourceEnvelope[ConversationResponse],
)
def get_conversation(
    business_id: UUID,
    conversation_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[ConversationResponse]:
    get_business_membership(client, business_id, user.id)
    row = _get_conversation(client, business_id, conversation_id)
    return ResourceEnvelope(data=row, request_id=request.state.request_id)


@router.get(
    "/businesses/{business_id}/conversations/{conversation_id}/messages",
    response_model=CollectionEnvelope[CustomerMessageResponse],
)
def list_conversation_messages(
    business_id: UUID,
    conversation_id: UUID,
    request: Request,
    user: User,
    client: Database,
    cursor: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
) -> CollectionEnvelope[CustomerMessageResponse]:
    get_business_membership(client, business_id, user.id)
    _get_conversation(client, business_id, conversation_id)
    rows, next_cursor, has_more = paginated_rows(
        client.table("customer_messages")
        .select(MESSAGE_FIELDS)
        .eq("business_id", str(business_id))
        .eq("conversation_id", str(conversation_id)),
        cursor=cursor,
        limit=limit,
    )
    return CollectionEnvelope(
        data=rows,
        meta=PaginationMeta(next_cursor=next_cursor, has_more=has_more),
        request_id=request.state.request_id,
    )


@router.post(
    "/businesses/{business_id}/conversations/{conversation_id}/messages",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ResourceEnvelope[CustomerMessageResponse],
    openapi_extra={"x-implementation-status": "queued; provider delivery worker planned"},
)
def send_customer_reply(
    business_id: UUID,
    conversation_id: UUID,
    body: CustomerReplyCreate,
    request: Request,
    user: User,
    client: Database,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ResourceEnvelope[CustomerMessageResponse]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin", "staff"})
    conversation = _get_conversation(client, business_id, conversation_id)
    if conversation["status"] == "resolved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "conversation_resolved", "message": "The conversation is resolved."},
        )
    if idempotency_key is None or not idempotency_key.strip() or len(idempotency_key) > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "idempotency_key_required", "message": "A valid Idempotency-Key header is required."},
        )
    now = datetime.now(timezone.utc).isoformat()
    message = execute(
        client.table("customer_messages")
        .select(MESSAGE_FIELDS)
        .eq("business_id", str(business_id))
        .eq("idempotency_key", idempotency_key)
        .maybe_single()
    )
    if message and (
        message["sender_type"] != "staff"
        or message["text"] != body.text
        or message["conversation_id"] != str(conversation_id)
        or message["sender_id"] != str(user.id)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "idempotency_conflict", "message": "The idempotency key has already been used."},
        )
    if message is None:
        message = execute(
            client.table("customer_messages")
            .insert(
                {
                "business_id": str(business_id),
                "conversation_id": str(conversation_id),
                "sender_type": "staff",
                "sender_id": str(user.id),
                "text": body.text,
                "visibility": "customer",
                "delivery_status": "queued",
                "idempotency_key": idempotency_key,
                "created_at": now,
            }
            )
            .select(MESSAGE_FIELDS)
            .single()
        )
    execute(
        client.table("conversations")
        .update({"status": "needs_reply", "last_message_at": now})
        .eq("business_id", str(business_id))
        .eq("id", str(conversation_id))
    )
    event_key = f"customer-message:{message['id']}"
    existing_event = execute(
        client.table("outbox_events")
        .select("id")
        .eq("business_id", str(business_id))
        .eq("dedupe_key", event_key)
        .maybe_single()
    )
    if not existing_event:
        execute(
            client.table("outbox_events").insert(
                {
                "business_id": str(business_id),
                "event_type": "conversation.reply_requested",
                "topic": "conversations",
                "data": {"conversation_id": str(conversation_id), "message_id": message["id"]},
                "dedupe_key": event_key,
            }
            )
        )
    return ResourceEnvelope(
        data=CustomerMessageResponse(
            **{
                key: value
                for key, value in message.items()
                if key in CustomerMessageResponse.model_fields
            }
        ),
        request_id=request.state.request_id,
    )


@router.patch(
    "/businesses/{business_id}/conversations/{conversation_id}",
    response_model=ResourceEnvelope[ConversationResponse],
)
def update_conversation(
    business_id: UUID,
    conversation_id: UUID,
    body: ConversationUpdate,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[ConversationResponse]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin", "staff"})
    _get_conversation(client, business_id, conversation_id)
    changes = body.model_dump(exclude_unset=True)
    if "assignee_id" in changes and changes["assignee_id"] is not None:
        assignee = execute(
            client.table("business_members")
            .select("id")
            .eq("business_id", str(business_id))
            .eq("id", str(changes["assignee_id"]))
            .maybe_single()
        )
        if not assignee:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "validation_error", "message": "The assignee is not a member of this business."},
            )
        changes["assignee_id"] = str(changes["assignee_id"])
    row = execute(
        client.table("conversations")
        .update(changes)
        .eq("business_id", str(business_id))
        .eq("id", str(conversation_id))
        .select(CONVERSATION_FIELDS)
        .single()
    )
    execute(
        client.table("outbox_events").insert(
            {
                "business_id": str(business_id),
                "event_type": "conversation.updated",
                "topic": "conversations",
                "data": {"conversation_id": str(conversation_id)},
            }
        )
    )
    return ResourceEnvelope(data=row, request_id=request.state.request_id)


@router.post(
    "/businesses/{business_id}/conversations/{conversation_id}/handoff",
    response_model=ResourceEnvelope[ConversationResponse],
)
def update_handoff(
    business_id: UUID,
    conversation_id: UUID,
    body: HandoffUpdate,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[ConversationResponse]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin", "staff"})
    _get_conversation(client, business_id, conversation_id)
    handoff_status = "accepted" if body.action == "accept" else "returned"
    row = execute(
        client.table("conversations")
        .update({"handoff_status": handoff_status})
        .eq("business_id", str(business_id))
        .eq("id", str(conversation_id))
        .select(CONVERSATION_FIELDS)
        .single()
    )
    return ResourceEnvelope(data=row, request_id=request.state.request_id)


@router.post(
    "/businesses/{business_id}/conversations/{conversation_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
)
def mark_conversation_read(
    business_id: UUID,
    conversation_id: UUID,
    user: User,
    client: Database,
) -> Response:
    get_business_membership(client, business_id, user.id)
    _get_conversation(client, business_id, conversation_id)
    execute(
        client.table("conversation_reads")
        .upsert(
            {
                "business_id": str(business_id),
                "conversation_id": str(conversation_id),
                "user_id": str(user.id),
                "read_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="business_id,conversation_id,user_id",
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
