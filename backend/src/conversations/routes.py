from datetime import datetime, timezone
import logging
import re
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from supabase import Client

from src.agent.customer_images import signed_customer_attachments
from src.catalog.routes import STORAGE_BUCKET
from src.auth.dependencies import AuthenticatedUser, get_current_user
from src.schemas.common import CollectionEnvelope, PaginationMeta, ResourceEnvelope
from src.schemas.conversations import (
    ConversationResponse,
    ConversationUpdate,
    CustomerMessageResponse,
    CustomerReplyAttachmentRequest,
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
from src.webhooks.routes import (
    _integration_credentials,
    _telegram_send_message,
    _telegram_send_photo,
)


router = APIRouter()
logger = logging.getLogger(__name__)
User = Annotated[AuthenticatedUser, Depends(get_current_user)]
Database = Annotated[Client, Depends(get_user_supabase_client)]
CONVERSATION_FIELDS = "id,business_id,channel,status,assignee_id,handoff_status,created_at,updated_at"
INBOX_CONVERSATION_FIELDS = (
    f"{CONVERSATION_FIELDS},customer_context,last_message_at"
)
MESSAGE_FIELDS = (
    "id,conversation_id,sender_type,sender_id,text,visibility,delivery_status,created_at,attachments"
)
CUSTOMER_MEDIA_BUCKET = "customer-chat-media"


def _resolve_reply_attachment(
    client: Client,
    business_id: UUID,
    conversation_id: UUID,
    reference: CustomerReplyAttachmentRequest,
) -> tuple[dict[str, str], str]:
    if reference.source == "catalog":
        product = execute(
            client.table("products")
            .select("id,name,provider_data,image_asset_ids")
            .eq("business_id", str(business_id))
            .eq("id", str(reference.product_id))
            .maybe_single()
        )
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "image_not_found", "message": "The selected product image was not found."},
            )
        provider_data = product.get("provider_data")
        provider_urls = (
            provider_data.get("image_urls", [])
            if isinstance(provider_data, dict)
            else []
        )
        images: list[tuple[dict[str, str], str]] = []
        seen_urls: set[str] = set()
        for image_url in provider_urls if isinstance(provider_urls, list) else []:
            if (
                isinstance(image_url, str)
                and image_url.startswith(("https://", "http://"))
                and image_url not in seen_urls
            ):
                images.append(
                    (
                        {"type": "image", "url": image_url, "alt": str(product["name"])},
                        image_url,
                    )
                )
                seen_urls.add(image_url)

        asset_ids = product.get("image_asset_ids")
        if isinstance(asset_ids, list) and asset_ids:
            assets = execute(
                client.table("media_assets")
                .select("id,delivery_path")
                .eq("business_id", str(business_id))
                .eq("status", "validated")
                .in_("id", [str(asset_id) for asset_id in asset_ids[:6]])
            )
            delivery_paths = {str(asset["id"]): asset.get("delivery_path") for asset in assets}
            for asset_id in asset_ids[:6]:
                path = delivery_paths.get(str(asset_id))
                if not isinstance(path, str):
                    continue
                signed = client.storage.from_(STORAGE_BUCKET).create_signed_url(path, 3600)
                url = signed.get("signedURL") or signed.get("signed_url")
                if isinstance(url, str) and url not in seen_urls:
                    images.append(
                        (
                            {
                                "type": "image",
                                "alt": str(product["name"]),
                                "bucket": STORAGE_BUCKET,
                                "storage_path": path,
                            },
                            url,
                        )
                    )
                    seen_urls.add(url)
        if reference.image_index >= len(images):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "image_not_found", "message": "The selected product image was not found."},
            )
        return images[reference.image_index]

    customer_message = execute(
        client.table("customer_messages")
        .select("attachments")
        .eq("business_id", str(business_id))
        .eq("conversation_id", str(conversation_id))
        .eq("id", str(reference.message_id))
        .eq("sender_type", "customer")
        .maybe_single()
    )
    source_attachments = customer_message.get("attachments") if customer_message else None
    if not isinstance(source_attachments, list) or reference.image_index >= len(source_attachments):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "image_not_found", "message": "The selected customer image was not found."},
        )
    attachment = source_attachments[reference.image_index]
    if not isinstance(attachment, dict) or attachment.get("type") != "image":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "image_not_found", "message": "The selected customer image was not found."},
        )
    path = attachment.get("storage_path")
    bucket = attachment.get("bucket", CUSTOMER_MEDIA_BUCKET)
    if (
        isinstance(path, str)
        and bucket == CUSTOMER_MEDIA_BUCKET
        and path.startswith(f"{business_id}/{conversation_id}/")
    ):
        signed = client.storage.from_(CUSTOMER_MEDIA_BUCKET).create_signed_url(path, 3600)
        url = signed.get("signedURL") or signed.get("signed_url")
        if isinstance(url, str):
            resolved = {
                "type": "image",
                "alt": str(attachment.get("alt") or "Customer-provided image"),
                "bucket": CUSTOMER_MEDIA_BUCKET,
                "storage_path": path,
            }
            return resolved, url
    source_url = attachment.get("url")
    if isinstance(source_url, str) and source_url.startswith("https://"):
        resolved = {
            "type": "image",
            "url": source_url,
            "alt": str(attachment.get("alt") or "Customer-provided image"),
        }
        return resolved, source_url
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "image_not_found", "message": "The selected customer image was not found."},
    )


def _send_telegram_reply(
    client: Client,
    business_id: UUID,
    provider_conversation_id: str | None,
    text: str,
    image_urls: list[tuple[str, str]],
) -> None:
    chat_id = (
        provider_conversation_id.removeprefix("telegram:")
        if isinstance(provider_conversation_id, str)
        else ""
    )
    if not re.fullmatch(r"-?\d{1,20}", chat_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "invalid_channel_conversation", "message": "This Telegram conversation cannot receive replies."},
        )
    integration = execute(
        client.table("integrations")
        .select("id")
        .eq("business_id", str(business_id))
        .eq("provider", "telegram")
        .eq("status", "connected")
        .limit(1)
    )
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "channel_not_connected", "message": "Telegram is not connected for this business."},
        )
    credentials, integration_business_id = _integration_credentials(
        client,
        UUID(integration[0]["id"]),
        "telegram",
    )
    bot_token = credentials.get("bot_token")
    if integration_business_id != business_id or not isinstance(bot_token, str):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "channel_credentials_unavailable", "message": "Telegram delivery is not configured."},
        )
    for image_url, alt in image_urls:
        _telegram_send_photo(bot_token, chat_id, image_url, caption=alt)
    if text.strip():
        _telegram_send_message(bot_token, chat_id, text.strip())


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
    rows = [
        {
            **row,
            "attachments": signed_customer_attachments(
                client,
                business_id=str(business_id),
                conversation_id=str(conversation_id),
                attachments=row.get("attachments"),
            ),
        }
        for row in rows
    ]
    return CollectionEnvelope(
        data=rows,
        meta=PaginationMeta(next_cursor=next_cursor, has_more=has_more),
        request_id=request.state.request_id,
    )


@router.post(
    "/businesses/{business_id}/conversations/{conversation_id}/messages",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ResourceEnvelope[CustomerMessageResponse],
    openapi_extra={"x-implementation-status": "website and Telegram replies are delivered synchronously"},
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
    channel = conversation["channel"]
    if channel not in {"website", "telegram"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "channel_reply_unsupported",
                "message": f"Replies are not supported for the {channel} channel yet.",
            },
        )
    if idempotency_key is None or not idempotency_key.strip() or len(idempotency_key) > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "idempotency_key_required", "message": "A valid Idempotency-Key header is required."},
        )
    now = datetime.now(timezone.utc).isoformat()
    attachments: list[dict[str, str]] = []
    image_urls: list[tuple[str, str]] = []
    for reference in body.attachments:
        attachment, image_url = _resolve_reply_attachment(
            client,
            business_id,
            conversation_id,
            reference,
        )
        attachments.append(attachment)
        image_urls.append((image_url, attachment["alt"]))
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
        or message.get("attachments", []) != attachments
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "idempotency_conflict", "message": "The idempotency key has already been used."},
        )
    is_new_message = message is None
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
                "attachments": attachments,
            }
            )
            .select(MESSAGE_FIELDS)
            .single()
        )
    if is_new_message or message["delivery_status"] == "queued":
        if channel == "telegram":
            provider_conversation = execute(
                client.table("conversations")
                .select("provider_conversation_id")
                .eq("business_id", str(business_id))
                .eq("id", str(conversation_id))
                .single()
            )
            try:
                _send_telegram_reply(
                    client,
                    business_id,
                    provider_conversation.get("provider_conversation_id"),
                    body.text,
                    image_urls,
                )
                delivery_status = "sent"
            except RuntimeError as error:
                logger.warning(
                    "Inbox Telegram reply delivery failed business_id=%s conversation_id=%s error_type=%s",
                    business_id,
                    conversation_id,
                    type(error).__name__,
                )
                delivery_status = "failed"
            except HTTPException as error:
                error_detail = error.detail if isinstance(error.detail, dict) else {}
                logger.warning(
                    "Inbox Telegram reply could not be delivered business_id=%s conversation_id=%s error_code=%s",
                    business_id,
                    conversation_id,
                    error_detail.get("code", "delivery_unavailable"),
                )
                delivery_status = "failed"
        else:
            delivery_status = "sent"
        message = execute(
            client.table("customer_messages")
            .update({"delivery_status": delivery_status})
            .eq("business_id", str(business_id))
            .eq("id", message["id"])
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
    message["attachments"] = signed_customer_attachments(
        client,
        business_id=str(business_id),
        conversation_id=str(conversation_id),
        attachments=message.get("attachments"),
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
