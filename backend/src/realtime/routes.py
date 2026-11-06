import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError
from supabase import Client

from src.auth.dependencies import AuthenticatedUser, get_current_user
from src.schemas.common import ResourceEnvelope
from src.schemas.realtime import RealtimeEvent, RealtimeSubscribe, RealtimeTicketResponse
from src.supabase.client import (
    get_service_supabase_client,
    get_supabase_client,
    get_supabase_settings,
    get_user_supabase_client,
)
from src.supabase.repository import (
    decode_cursor,
    encode_cursor,
    execute,
    get_business_membership,
)


router = APIRouter()
User = Annotated[AuthenticatedUser, Depends(get_current_user)]
Database = Annotated[Client, Depends(get_user_supabase_client)]
TOPIC_EVENT_PREFIXES = {
    "conversations": ("conversation.",),
    "owner_assistant": ("owner_assistant.",),
    "approvals": ("approval.",),
    "orders": ("order.", "payment."),
    "integrations": ("integration.", "catalog."),
    "notifications": ("notification.",),
}
TICKET_PROTOCOL_PREFIX = "reactant-ticket."


@router.post(
    "/businesses/{business_id}/realtime-ticket",
    response_model=ResourceEnvelope[RealtimeTicketResponse],
)
def create_realtime_ticket(
    business_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[RealtimeTicketResponse]:
    get_business_membership(client, business_id, user.id)
    ticket = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=60)
    execute(
        client.table("realtime_tickets").insert(
            {
                "token_hash": hashlib.sha256(ticket.encode()).hexdigest(),
                "business_id": str(business_id),
                "user_id": str(user.id),
                "expires_at": expires_at.isoformat(),
            }
        )
    )
    scheme = "wss" if request.url.scheme == "https" else "ws"
    websocket_url = f"{scheme}://{request.url.netloc}/api/v1/realtime/ws"
    return ResourceEnvelope(
        data=RealtimeTicketResponse(
            ticket=ticket,
            websocket_url=websocket_url,
            expires_at=expires_at,
        ),
        request_id=request.state.request_id,
    )


@router.websocket("/realtime/ws")
async def realtime_websocket(
    websocket: WebSocket,
    cursor: str | None = Query(default=None, max_length=512),
) -> None:
    allowed_origins = {
        origin.strip()
        for origin in get_supabase_settings().allowed_web_origins.split(",")
        if origin.strip()
    }
    origin = websocket.headers.get("origin")
    if not origin or origin not in allowed_origins:
        await websocket.close(code=4403, reason="Origin is not allowed.")
        return

    offered = websocket.scope.get("subprotocols", [])
    ticket = next(
        (
            protocol[len(TICKET_PROTOCOL_PREFIX) :]
            for protocol in offered
            if protocol.startswith(TICKET_PROTOCOL_PREFIX)
        ),
        None,
    )
    if not ticket or len(ticket) > 256:
        await websocket.close(code=4401, reason="A valid realtime ticket is required.")
        return

    try:
        consumed = await asyncio.to_thread(
            execute,
            get_supabase_client().rpc(
                "consume_realtime_ticket",
                {"ticket_token_hash": hashlib.sha256(ticket.encode()).hexdigest()},
            ),
        )
        if isinstance(consumed, list):
            consumed = consumed[0] if consumed else None
        if not isinstance(consumed, dict):
            await websocket.close(code=4401, reason="The realtime ticket is unavailable.")
            return
        business_id = UUID(consumed["business_id"])
        client = get_service_supabase_client()
    except (HTTPException, KeyError, ValueError):
        await websocket.close(code=4401, reason="The realtime ticket is unavailable.")
        return

    await websocket.accept()
    try:
        subscribe_body = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        subscription = RealtimeSubscribe.model_validate(subscribe_body)
    except (asyncio.TimeoutError, ValidationError, ValueError):
        await websocket.close(code=1008, reason="A valid subscription is required.")
        return
    if subscription.type != "subscribe":
        await websocket.close(code=1008, reason="A valid subscription is required.")
        return

    event_prefixes = tuple(
        prefix
        for topic in subscription.topics
        for prefix in TOPIC_EVENT_PREFIXES[topic]
    )
    try:
        last_cursor = decode_cursor(subscription.cursor or cursor)
    except HTTPException:
        await websocket.close(code=1008, reason="The resume cursor is invalid.")
        return
    if last_cursor is None:
        last_created_at = datetime.now(timezone.utc).isoformat()
        last_id = "00000000-0000-0000-0000-000000000000"
    else:
        last_created_at, last_id = last_cursor

    try:
        while True:
            await asyncio.sleep(1)
            rows = await asyncio.to_thread(
                execute,
                client.table("outbox_events")
                .select("id,business_id,event_type,topic,data,created_at")
                .eq("business_id", str(business_id))
                .in_("topic", subscription.topics)
                .or_(
                    f"created_at.gt.{last_created_at},and(created_at.eq.{last_created_at},id.gt.{last_id})"
                )
                .order("created_at")
                .order("id")
                .limit(100),
            )
            for row in rows:
                if not row["event_type"].startswith(event_prefixes):
                    continue
                event = RealtimeEvent(
                    id=row["id"],
                    type=row["event_type"],
                    business_id=row["business_id"],
                    occurred_at=row["created_at"],
                    data=row["data"],
                )
                await websocket.send_json(
                    {
                        **event.model_dump(mode="json"),
                        "cursor": encode_cursor(row["created_at"], row["id"]),
                    }
                )
            if rows:
                last_cursor = decode_cursor(encode_cursor(rows[-1]["created_at"], rows[-1]["id"]))
                if last_cursor:
                    last_created_at, last_id = last_cursor
    except WebSocketDisconnect:
        return
    except HTTPException:
        await websocket.close(code=1011, reason="Realtime delivery is unavailable.")
