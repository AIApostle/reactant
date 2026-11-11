import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client

from src.agent.worker import require_agent_runtime
from src.agent.config import get_agent_runtime_settings
from src.auth.dependencies import AuthenticatedUser, get_current_user
from src.schemas.common import CollectionEnvelope, PaginationMeta, ResourceEnvelope
from src.schemas.owner_assistant import (
    AgentRunStatusResponse,
    InternalOwnerMessageCreate,
    OwnerMessageAccepted,
    OwnerMessageCreate,
    OwnerMessageResponse,
    OwnerThreadResponse,
    OwnerAssistantStatusResponse,
    OwnerTelegramChannelStatusResponse,
    OwnerTelegramPairingResponse,
)
from src.supabase.client import (
    get_service_supabase_client,
    get_supabase_settings,
    get_user_supabase_client,
)
from src.supabase.repository import (
    execute,
    get_business_membership,
    paginated_rows,
    require_role,
)
from src.integrations.routes import _decrypt_credentials, _telegram_api
from src.webhooks.routes import _integration_credentials, _telegram_send_long_message


router = APIRouter()
service_router = APIRouter()
logger = logging.getLogger(__name__)
User = Annotated[AuthenticatedUser, Depends(get_current_user)]
Database = Annotated[Client, Depends(get_user_supabase_client)]
Bearer = HTTPBearer(auto_error=False)
ServiceDatabase = Annotated[Client, Depends(get_service_supabase_client)]
MESSAGE_FIELDS = (
    "id,thread_id,sender_type,sender_id,display_name,kind,text,approval_id,created_at,read_at"
)
MESSAGE_RESPONSE_FIELDS = (
    "id",
    "thread_id",
    "sender_type",
    "sender_id",
    "display_name",
    "kind",
    "text",
    "approval_id",
    "created_at",
    "read_at",
)


def _owner_message_response(message: dict[str, Any]) -> OwnerMessageResponse:
    return OwnerMessageResponse(
        **{field: message[field] for field in MESSAGE_RESPONSE_FIELDS}
    )


def _owner_thread(
    client: Client,
    business_id: UUID,
) -> dict[str, Any]:
    row = execute(
        client.rpc(
            "get_or_create_owner_thread",
            {"target_business_id": str(business_id)},
        )
    )
    if isinstance(row, list):
        row = row[0] if row else None
    if not isinstance(row, dict):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "database_unavailable", "message": "The request could not be completed right now."},
        )
    return row


def _connected_telegram_integration(client: Client, business_id: UUID) -> dict[str, Any]:
    integration = execute(
        client.table("integrations")
        .select("id,credentials_ciphertext")
        .eq("business_id", str(business_id))
        .eq("provider", "telegram")
        .eq("status", "connected")
        .order("created_at", desc=True)
        .limit(1)
    )
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "telegram_not_connected", "message": "Connect Telegram before pairing an owner channel."},
        )
    return integration[0]


@router.get(
    "/businesses/{business_id}/owner-assistant/telegram",
    response_model=ResourceEnvelope[OwnerTelegramChannelStatusResponse],
)
def get_owner_telegram_channel_status(
    business_id: UUID,
    request: Request,
    user: User,
    client: Database,
    service_client: ServiceDatabase,
) -> ResourceEnvelope[OwnerTelegramChannelStatusResponse]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner"})
    integrations = execute(
        client.table("integrations")
        .select("id")
        .eq("business_id", str(business_id))
        .eq("provider", "telegram")
        .eq("status", "connected")
        .order("created_at", desc=True)
        .limit(1)
    )
    if not integrations:
        return ResourceEnvelope(
            data=OwnerTelegramChannelStatusResponse(
                telegram_connected=False,
                paired=False,
                paired_at=None,
            ),
            request_id=request.state.request_id,
        )
    integration = integrations[0]
    channel = execute(
        service_client.table("owner_telegram_channels")
        .select("telegram_chat_id,paired_at")
        .eq("business_id", str(business_id))
        .eq("integration_id", integration["id"])
        .eq("owner_user_id", str(user.id))
        .maybe_single()
    )
    paired_at = channel.get("paired_at") if channel and channel.get("telegram_chat_id") else None
    return ResourceEnvelope(
        data=OwnerTelegramChannelStatusResponse(
            telegram_connected=True,
            paired=paired_at is not None,
            paired_at=paired_at,
        ),
        request_id=request.state.request_id,
    )


@router.post(
    "/businesses/{business_id}/owner-assistant/telegram/pairing",
    response_model=ResourceEnvelope[OwnerTelegramPairingResponse],
)
def create_owner_telegram_pairing(
    business_id: UUID,
    request: Request,
    user: User,
    client: Database,
    service_client: ServiceDatabase,
) -> ResourceEnvelope[OwnerTelegramPairingResponse]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner"})
    integration = _connected_telegram_integration(client, business_id)
    credentials = _decrypt_credentials(integration["credentials_ciphertext"])
    bot_token = credentials.get("bot_token")
    if not isinstance(bot_token, str):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "telegram_credentials_unavailable", "message": "Telegram credentials could not be read."},
        )
    bot = _telegram_api(bot_token, "getMe", {})
    bot_username = bot.get("username")
    if not isinstance(bot_username, str) or not bot_username.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "telegram_bot_unavailable", "message": "The connected Telegram bot has no username."},
        )

    pairing_code = secrets.token_urlsafe(24)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    execute(
        service_client.table("owner_telegram_channels").upsert(
            {
                "business_id": str(business_id),
                "integration_id": integration["id"],
                "owner_user_id": str(user.id),
                "telegram_chat_id": None,
                "paired_at": None,
                "pairing_token_hash": hashlib.sha256(pairing_code.encode()).hexdigest(),
                "pairing_expires_at": expires_at.isoformat(),
            },
            on_conflict="business_id",
        )
    )
    return ResourceEnvelope(
        data=OwnerTelegramPairingResponse(
            pairing_code=pairing_code,
            bot_username=bot_username,
            expires_at=expires_at,
        ),
        request_id=request.state.request_id,
    )


@router.delete(
    "/businesses/{business_id}/owner-assistant/telegram",
    status_code=status.HTTP_204_NO_CONTENT,
)
def disconnect_owner_telegram_channel(
    business_id: UUID,
    user: User,
    client: Database,
    service_client: ServiceDatabase,
) -> None:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner"})
    execute(
        service_client.table("owner_telegram_channels")
        .delete()
        .eq("business_id", str(business_id))
        .eq("owner_user_id", str(user.id))
    )


@router.get(
    "/businesses/{business_id}/owner-assistant/status",
    response_model=ResourceEnvelope[OwnerAssistantStatusResponse],
)
def get_owner_assistant_status(
    business_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[OwnerAssistantStatusResponse]:
    get_business_membership(client, business_id, user.id)
    settings = get_agent_runtime_settings()
    if not settings.strands_agent_enabled:
        reason = "disabled"
    elif settings.model_api_key is None:
        reason = (
            "missing_google_key"
            if settings.agent_model_provider == "google"
            else "missing_openrouter_key"
        )
    elif get_supabase_settings().supabase_secret_key is None:
        reason = "missing_service_key"
    else:
        reason = "ready"
    return ResourceEnvelope(
        data=OwnerAssistantStatusResponse(
            provider="strands",
            enabled=settings.strands_agent_enabled,
            available=reason == "ready",
            model_id=settings.selected_model_id() if reason == "ready" else None,
            reason=reason,
        ),
        request_id=request.state.request_id,
    )


@router.get(
    "/businesses/{business_id}/owner-assistant/thread",
    response_model=ResourceEnvelope[dict[str, Any]],
)
def get_owner_thread(
    business_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[dict[str, Any]]:
    get_business_membership(client, business_id, user.id)
    thread = _owner_thread(client, business_id)
    messages = execute(
        client.table("owner_messages")
        .select(MESSAGE_FIELDS)
        .eq("business_id", str(business_id))
        .eq("thread_id", thread["id"])
        .order("created_at", desc=True)
        .limit(25)
    )
    return ResourceEnvelope(
        data={"thread": OwnerThreadResponse(**thread), "messages": messages},
        request_id=request.state.request_id,
    )


@router.get(
    "/businesses/{business_id}/owner-assistant/messages",
    response_model=CollectionEnvelope[OwnerMessageResponse],
)
def list_owner_messages(
    business_id: UUID,
    request: Request,
    user: User,
    client: Database,
    cursor: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
) -> CollectionEnvelope[OwnerMessageResponse]:
    get_business_membership(client, business_id, user.id)
    thread = _owner_thread(client, business_id)
    rows, next_cursor, has_more = paginated_rows(
        client.table("owner_messages")
        .select(MESSAGE_FIELDS)
        .eq("business_id", str(business_id))
        .eq("thread_id", thread["id"]),
        cursor=cursor,
        limit=limit,
    )
    return CollectionEnvelope(
        data=rows,
        meta=PaginationMeta(next_cursor=next_cursor, has_more=has_more),
        request_id=request.state.request_id,
    )


@router.post(
    "/businesses/{business_id}/owner-assistant/messages",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ResourceEnvelope[OwnerMessageAccepted],
)
def send_owner_message(
    business_id: UUID,
    body: OwnerMessageCreate,
    request: Request,
    user: User,
    client: Database,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ResourceEnvelope[OwnerMessageAccepted]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin", "staff"})
    require_agent_runtime()
    thread = _owner_thread(client, business_id)
    if body.client_message_id is None and (
        idempotency_key is None or not idempotency_key.strip() or len(idempotency_key) > 200
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "idempotency_key_required", "message": "A message ID or valid Idempotency-Key is required."},
        )
    if body.client_message_id is not None:
        stable_key = str(body.client_message_id)
    else:
        assert idempotency_key is not None
        stable_key = idempotency_key.strip()
    result = execute(
        client.rpc(
            "enqueue_owner_assistant_message",
            {
                "target_business_id": str(business_id),
                "target_thread_id": thread["id"],
                "requested_text": body.text,
                "requested_idempotency_key": stable_key,
                "requested_client_message_id": (
                    str(body.client_message_id)
                    if body.client_message_id
                    else None
                ),
            },
        )
    )
    if isinstance(result, list):
        result = result[0] if result else None
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("message"), dict)
        or not isinstance(result.get("run"), dict)
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "agent_queue_unavailable",
                "message": "The request could not be completed right now.",
            },
        )
    message = result["message"]
    run = result["run"]
    return ResourceEnvelope(
        data=OwnerMessageAccepted(
            message=_owner_message_response(message),
            agent_run_id=run["id"],
            agent_run_status=run["status"],
        ),
        request_id=request.state.request_id,
    )


@router.get(
    "/businesses/{business_id}/owner-assistant/runs/{run_id}",
    response_model=ResourceEnvelope[AgentRunStatusResponse],
)
def get_owner_agent_run(
    business_id: UUID,
    run_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[AgentRunStatusResponse]:
    get_business_membership(client, business_id, user.id)
    run = execute(
        client.table("agent_runs")
        .select("id,status,created_at,started_at,completed_at,error_code")
        .eq("business_id", str(business_id))
        .eq("id", str(run_id))
        .maybe_single()
    )
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested resource was not found."},
        )
    return ResourceEnvelope(
        data=AgentRunStatusResponse(**run),
        request_id=request.state.request_id,
    )


@router.post(
    "/businesses/{business_id}/owner-assistant/messages/{message_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
)
def mark_owner_message_read(
    business_id: UUID,
    message_id: UUID,
    user: User,
    client: Database,
) -> None:
    get_business_membership(client, business_id, user.id)
    updated = execute(
        client.table("owner_messages")
        .update({"read_at": datetime.now(timezone.utc).isoformat()})
        .eq("business_id", str(business_id))
        .eq("id", str(message_id))
        .eq("sender_type", "agent")
        .select("id")
        .maybe_single()
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested resource was not found."},
        )


def _require_service_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(Bearer),
    ],
) -> None:
    expected = get_supabase_settings().internal_service_token
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or expected is None
        or not hmac.compare_digest(
            credentials.credentials,
            expected.get_secret_value(),
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthenticated", "message": "Service authentication is required."},
            headers={"WWW-Authenticate": "Bearer"},
        )


def _notify_paired_telegram_owner(
    client: Client,
    business_id: UUID,
    message: dict[str, Any],
) -> None:
    try:
        channel = execute(
            client.table("owner_telegram_channels")
            .select("integration_id,telegram_chat_id,paired_at")
            .eq("business_id", str(business_id))
            .maybe_single()
        )
        if not channel or not channel.get("telegram_chat_id") or not channel.get("paired_at"):
            return
        integration = execute(
            client.table("integrations")
            .select("id")
            .eq("business_id", str(business_id))
            .eq("id", channel["integration_id"])
            .eq("provider", "telegram")
            .eq("status", "connected")
            .maybe_single()
        )
        if not integration:
            return
        credentials, resolved_business_id = _integration_credentials(
            client,
            UUID(integration["id"]),
            "telegram",
        )
        bot_token = credentials.get("bot_token")
        if resolved_business_id != business_id or not isinstance(bot_token, str):
            logger.error("Paired Telegram owner notification is missing valid bot credentials business_id=%s", business_id)
            return
        text = str(message["text"])
        if message.get("kind") == "approval_request" and message.get("approval_id"):
            text = (
                f"{text}\n\nReply with:\n"
                f"/approve {message['approval_id']}\n"
                f"/reject {message['approval_id']}"
            )
        _telegram_send_long_message(bot_token, str(channel["telegram_chat_id"]), text)
    except (HTTPException, RuntimeError) as error:
        logger.warning(
            "Paired Telegram owner notification failed business_id=%s exception_type=%s",
            business_id,
            type(error).__name__,
        )


@service_router.post(
    "/businesses/{business_id}/owner-assistant/messages",
    status_code=status.HTTP_201_CREATED,
    response_model=ResourceEnvelope[OwnerMessageResponse],
)
def create_agent_owner_message(
    business_id: UUID,
    body: InternalOwnerMessageCreate,
    request: Request,
    _: Annotated[None, Depends(_require_service_token)],
    client: ServiceDatabase,
) -> ResourceEnvelope[OwnerMessageResponse]:
    run = execute(
        client.table("agent_runs")
        .select("id")
        .eq("business_id", str(business_id))
        .eq("id", str(body.agent_run_id))
        .maybe_single()
    )
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested agent run was not found."},
        )
    if body.kind == "approval_request":
        if body.approval_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "validation_error", "message": "An approval request must reference an approval."},
            )
        approval = execute(
            client.table("approvals")
            .select("id")
            .eq("business_id", str(business_id))
            .eq("id", str(body.approval_id))
            .eq("status", "pending")
            .maybe_single()
        )
        if not approval:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "validation_error", "message": "The approval is unavailable."},
            )
    thread = execute(
        client.table("owner_threads")
        .upsert(
            {"business_id": str(business_id)},
            on_conflict="business_id",
        )
        .select("id,business_id,created_at")
        .single()
    )
    if not isinstance(thread, dict):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "database_unavailable", "message": "The request could not be completed right now."},
        )
    existing = execute(
        client.table("owner_messages")
        .select(MESSAGE_FIELDS)
        .eq("business_id", str(business_id))
        .eq("idempotency_key", str(body.idempotency_key))
        .maybe_single()
    )
    if existing and (
        existing["sender_id"] != body.sender_id
        or existing["text"] != body.text
        or existing["agent_run_id"] != str(body.agent_run_id)
        or existing["approval_id"] != (str(body.approval_id) if body.approval_id else None)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "idempotency_conflict", "message": "The idempotency key has already been used."},
        )
    is_new_message = existing is None
    if is_new_message:
        existing = execute(
            client.table("owner_messages")
            .insert(
                {
                    "business_id": str(business_id),
                    "thread_id": thread["id"],
                    "sender_type": "agent",
                    "sender_id": body.sender_id,
                    "display_name": body.display_name,
                    "kind": body.kind,
                    "text": body.text,
                    "approval_id": str(body.approval_id) if body.approval_id else None,
                    "agent_run_id": str(body.agent_run_id),
                    "idempotency_key": str(body.idempotency_key),
                }
            )
            .select(MESSAGE_FIELDS)
            .single()
        )
    event_key = f"owner-message:{existing['id']}"
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
                    "event_type": "owner_assistant.message_created",
                    "topic": "owner_assistant",
                    "data": {"message_id": existing["id"], "thread_id": thread["id"]},
                    "dedupe_key": event_key,
                }
            )
        )
    if is_new_message:
        _notify_paired_telegram_owner(client, business_id, existing)
    return ResourceEnvelope(
        data=OwnerMessageResponse(**existing),
        request_id=request.state.request_id,
    )
