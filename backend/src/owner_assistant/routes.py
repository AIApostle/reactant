import hmac
from datetime import datetime, timezone
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


router = APIRouter()
service_router = APIRouter()
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
    elif settings.openrouter_api_key is None:
        reason = "missing_openrouter_key"
    elif get_supabase_settings().supabase_secret_key is None:
        reason = "missing_service_key"
    else:
        reason = "ready"
    return ResourceEnvelope(
        data=OwnerAssistantStatusResponse(
            provider="strands",
            enabled=settings.strands_agent_enabled,
            available=reason == "ready",
            model_id=settings.openrouter_model_id if reason == "ready" else None,
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
    if existing is None:
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
    return ResourceEnvelope(
        data=OwnerMessageResponse(**existing),
        request_id=request.state.request_id,
    )
