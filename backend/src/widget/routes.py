import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from supabase import Client

from src.agent.config import get_agent_runtime_settings
from src.agent.customer_images import (
    CustomerImage,
    decode_customer_image_data_uri,
    history_with_customer_images,
    signed_customer_attachments,
    store_customer_images,
)
from src.agent.runtime import build_business_agent, find_business_products, invoke_business_agent
from src.supabase.client import get_service_supabase_client, get_supabase_settings
from src.supabase.repository import execute


router = APIRouter()
logger = logging.getLogger(__name__)
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30
IMAGE_REQUEST = re.compile(r"\b(image|images|photo|photos|picture|pictures|show me|send me|see it)\b", re.I)
IMAGE_QUERY_STOP_WORDS = {
    "a", "an", "and", "can", "could", "do", "for", "get", "i", "image",
    "images", "it", "me", "of", "please", "picture", "pictures", "photo",
    "photos", "see", "show", "some", "the", "this", "that", "to", "want",
    "you", "one", "product", "products", "item", "items",
}


class WidgetSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visitor_id: str = Field(min_length=16, max_length=80)
    customer_name: str = Field(default="Website visitor", min_length=1, max_length=120)
    memory_consent: bool = False


class WidgetMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(default="", max_length=4000)
    images: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("images")
    @classmethod
    def validate_images(cls, images: list[str]) -> list[str]:
        if sum(len(image) for image in images) > 7_000_000:
            raise ValueError("Images in a message cannot exceed 5 MB.")
        return images

    @model_validator(mode="after")
    def validate_message(self) -> "WidgetMessageCreate":
        if not self.text.strip() and not self.images:
            raise ValueError("A message must contain text or an image.")
        return self


def _origin(request: Request | WebSocket) -> str:
    value = request.headers.get("origin", "").strip().rstrip("/")
    if not value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "widget_origin_required", "message": "The website origin is required."},
        )
    return value.lower()


def _integration_for_origin(client: Client, business_id: str, origin: str) -> dict[str, Any]:
    rows = execute(
        client.table("integrations")
        .select("id,credentials_ciphertext")
        .eq("business_id", business_id)
        .eq("provider", "website_chat")
        .eq("status", "connected")
        .limit(100)
    )
    key = get_supabase_settings().credentials_encryption_key
    for row in rows:
        ciphertext = row.get("credentials_ciphertext")
        if not isinstance(ciphertext, str) or key is None:
            continue
        try:
            credentials = json.loads(
                Fernet(key.get_secret_value().encode()).decrypt(ciphertext.encode())
            )
        except (InvalidToken, ValueError, TypeError, json.JSONDecodeError):
            logger.error("Website chat credentials could not be read integration_id=%s", row["id"])
            continue
        if isinstance(credentials, dict) and credentials.get("allowed_origin") == origin:
            return row
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "widget_origin_not_allowed", "message": "This website is not authorized to use the chat."},
    )


def _signing_key() -> bytes:
    key = get_supabase_settings().credentials_encryption_key
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "widget_unavailable", "message": "Website chat is not configured."},
        )
    return hashlib.sha256(key.get_secret_value().encode()).digest()


def _issue_session_token(
    *,
    business_id: str,
    conversation_id: str,
    visitor_id: str,
    origin: str,
    memory_consent: bool,
) -> str:
    payload = {
        "business_id": business_id,
        "conversation_id": conversation_id,
        "visitor_id": visitor_id,
        "origin": origin,
        "memory_consent": memory_consent,
        "exp": int(time.time()) + SESSION_TTL_SECONDS,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).decode().rstrip("=")
    signature = hmac.new(_signing_key(), encoded.encode(), hashlib.sha256).digest()
    return f"{encoded}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"


def _read_session_token(token: str) -> dict[str, Any]:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected = hmac.new(_signing_key(), encoded.encode(), hashlib.sha256).digest()
        signature = base64.urlsafe_b64decode(supplied_signature + "=" * (-len(supplied_signature) % 4))
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(
            base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        )
        if not isinstance(payload, dict) or int(payload["exp"]) < int(time.time()):
            raise ValueError
        return payload
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "widget_session_invalid", "message": "The chat session has expired. Start a new conversation."},
        ) from error


def _request_claims(request: Request) -> dict[str, Any]:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 2048:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "widget_session_invalid", "message": "A valid chat session is required."},
        )
    return _read_session_token(token)


def _validate_session_origin(client: Client, request: Request | WebSocket, claims: dict[str, Any]) -> None:
    origin = _origin(request)
    if not hmac.compare_digest(origin, str(claims.get("origin", ""))):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "widget_origin_not_allowed", "message": "This website is not authorized to use the chat."},
        )
    _integration_for_origin(client, str(claims["business_id"]), origin)


def _agent_settings(client: Client, business_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    business = execute(
        client.table("businesses")
        .select("name,country,currency,return_policy,delivery_policy")
        .eq("id", business_id)
        .single()
    )
    agent_config = execute(
        client.table("agent_configs")
        .select("business_context,tone,handoff_rule,permissions,approval_policy")
        .eq("business_id", business_id)
        .maybe_single()
    )
    return business, agent_config


def _image_query(text: str, history: list[dict[str, Any]]) -> str:
    def clean(value: str) -> str:
        words = re.findall(r"[\w'-]+", value.lower())
        return " ".join(word for word in words if word not in IMAGE_QUERY_STOP_WORDS)[:100]

    query = clean(IMAGE_REQUEST.sub(" ", text))
    if query:
        return query
    for row in history:
        if row.get("sender_type") == "customer":
            query = clean(str(row.get("text", "")))
            if query:
                return query
    return ""


def _process_widget_message(
    client: Client,
    *,
    claims: dict[str, Any],
    user_text: str,
    message_id: str,
    images: list[CustomerImage],
) -> None:
    business_id = str(claims["business_id"])
    conversation_id = str(claims["conversation_id"])
    history_rows = execute(
        client.table("customer_messages")
        .select("id,sender_type,text,attachments")
        .eq("business_id", business_id)
        .eq("conversation_id", conversation_id)
        .neq("id", message_id)
        .order("created_at", desc=True)
        .limit(8)
    )
    business, agent_config = _agent_settings(client, business_id)
    conversation = execute(
        client.table("conversations")
        .select("customer_context")
        .eq("business_id", business_id)
        .eq("id", conversation_id)
        .single()
    )
    customer_context = conversation.get("customer_context") or {}
    memory_opt_in = (
        bool(claims.get("memory_consent"))
        and isinstance(customer_context, dict)
        and customer_context.get("memory_opt_in") is True
    )
    settings = get_agent_runtime_settings()
    if not settings.strands_agent_enabled or settings.openrouter_api_key is None:
        logger.error("Website chat agent is unavailable business_id=%s", business_id)
        _save_widget_agent_message(
            client,
            business_id=business_id,
            conversation_id=conversation_id,
            message_id=message_id,
            text="I couldn't respond just now. Please try again later.",
        )
        return
    agent = build_business_agent(
        client=client,
        business_id=business_id,
        settings=settings,
        business=business,
        agent_config=agent_config,
        history=history_with_customer_images(
            client,
            business_id=business_id,
            conversation_id=conversation_id,
            rows=history_rows,
        ),
        audience="customer",
        memory_opt_in=memory_opt_in,
        memory_customer_reference=str(claims["visitor_id"]),
        conversation_id=conversation_id,
        customer_name="Website visitor",
        customer_reference=str(claims["visitor_id"]),
        idempotency_key=f"website:{message_id}",
        created_checkout_urls=[],
        vision_enabled=bool(images),
    )
    response_text = invoke_business_agent(
        agent,
        user_text,
        audience="customer",
        images=images,
    )
    attachments: list[dict[str, str]] = []
    if IMAGE_REQUEST.search(user_text):
        query = _image_query(user_text, history_rows)
        if query:
            for product in find_business_products(client, business_id, query, limit=3):
                for url in product.get("image_urls", [])[:2]:
                    attachments.append(
                        {"type": "image", "url": url, "alt": product["name"]}
                    )
        if attachments and re.search(r"\b(can't|cannot|don't have|unavailable|no access)\b.*\b(image|photo|picture)s?\b", response_text, re.I):
            response_text = "Here are the product photos."

    _save_widget_agent_message(
        client,
        business_id=business_id,
        conversation_id=conversation_id,
        message_id=message_id,
        text=response_text,
        attachments=attachments,
    )


def _save_widget_agent_message(
    client: Client,
    *,
    business_id: str,
    conversation_id: str,
    message_id: str,
    text: str,
    attachments: list[dict[str, str]] | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    execute(
        client.table("customer_messages").insert(
            {
                "business_id": business_id,
                "conversation_id": conversation_id,
                "sender_type": "agent",
                "sender_id": "business-agent",
                "text": text,
                "attachments": attachments or [],
                "visibility": "customer",
                "delivery_status": "sent",
                "provider_message_id": f"website-agent:{message_id}",
                "idempotency_key": f"website-agent:{message_id}",
                "created_at": now,
            }
        )
    )
    execute(
        client.table("conversations")
        .update({"status": "open", "last_message_at": now})
        .eq("business_id", business_id)
        .eq("id", conversation_id)
    )
    execute(
        client.table("outbox_events").insert(
            {
                "business_id": business_id,
                "event_type": "conversation.message_created",
                "topic": "conversations",
                "data": {"conversation_id": conversation_id},
                "dedupe_key": f"website-agent:{message_id}",
            }
        )
    )


@router.get("/public/widgets/{business_id}/config")
def widget_config(business_id: UUID, request: Request) -> dict[str, Any]:
    client = get_service_supabase_client()
    _integration_for_origin(client, str(business_id), _origin(request))
    business = execute(
        client.table("businesses").select("name").eq("id", str(business_id)).single()
    )
    return {"business_name": business["name"], "greeting": f"Hi, how can {business['name']} help you?"}


@router.post("/public/widgets/{business_id}/sessions")
def create_widget_session(
    business_id: UUID,
    body: WidgetSessionCreate,
    request: Request,
) -> dict[str, Any]:
    origin = _origin(request)
    client = get_service_supabase_client()
    _integration_for_origin(client, str(business_id), origin)
    try:
        visitor_id = str(UUID(body.visitor_id))
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_visitor_id", "message": "The chat visitor ID is invalid."},
        ) from error
    provider_id = f"website:{visitor_id}"
    existing = execute(
        client.table("conversations")
        .select("id,customer_context")
        .eq("business_id", str(business_id))
        .eq("provider_conversation_id", provider_id)
        .limit(1)
    )
    now = datetime.now(timezone.utc).isoformat()
    if existing:
        conversation = existing[0]
        context = conversation.get("customer_context") or {}
        context.update(
            {
                "customer_name": body.customer_name.strip() or "Website visitor",
                "customer_reference": visitor_id,
                "memory_opt_in": body.memory_consent,
            }
        )
        execute(
            client.table("conversations")
            .update({"customer_context": context, "last_message_at": now})
            .eq("business_id", str(business_id))
            .eq("id", conversation["id"])
        )
        conversation_id = str(conversation["id"])
    else:
        conversation = execute(
            client.table("conversations")
            .insert(
                {
                    "business_id": str(business_id),
                    "channel": "website",
                    "provider_conversation_id": provider_id,
                    "status": "open",
                    "customer_context": {
                        "customer_name": body.customer_name.strip() or "Website visitor",
                        "customer_reference": visitor_id,
                        "memory_opt_in": body.memory_consent,
                        "website_origin": origin,
                    },
                    "last_message_at": now,
                }
            )
            .select("id")
            .single()
        )
        conversation_id = str(conversation["id"])
    token = _issue_session_token(
        business_id=str(business_id),
        conversation_id=conversation_id,
        visitor_id=visitor_id,
        origin=origin,
        memory_consent=body.memory_consent,
    )
    return {"session_token": token, "conversation_id": conversation_id}


@router.get("/public/widgets/sessions/messages")
def list_widget_messages(request: Request) -> list[dict[str, Any]]:
    claims = _request_claims(request)
    client = get_service_supabase_client()
    _validate_session_origin(client, request, claims)
    rows = execute(
        client.table("customer_messages")
        .select("id,sender_type,text,attachments,created_at")
        .eq("business_id", claims["business_id"])
        .eq("conversation_id", claims["conversation_id"])
        .eq("visibility", "customer")
        .order("created_at")
        .limit(100)
    )
    return [
        {
            **row,
            "attachments": signed_customer_attachments(
                client,
                business_id=claims["business_id"],
                conversation_id=claims["conversation_id"],
                attachments=row.get("attachments"),
            ),
        }
        for row in rows
    ]


@router.post("/public/widgets/sessions/messages", status_code=status.HTTP_202_ACCEPTED)
def post_widget_message(
    body: WidgetMessageCreate,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    claims = _request_claims(request)
    client = get_service_supabase_client()
    _validate_session_origin(client, request, claims)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            body_size = int(content_length)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "malformed_request", "message": "The request is malformed."},
            ) from error
        if body_size > 8_000_000:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={
                    "code": "payload_too_large",
                    "message": "The chat message and images are too large.",
                },
            )
    try:
        images = [
            decode_customer_image_data_uri(image, f"website-image-{index}")
            for index, image in enumerate(body.images, start=1)
        ]
        if sum(len(image.data) for image in images) > 5 * 1024 * 1024:
            raise ValueError("Images in a message cannot exceed 5 MB in total.")
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_image", "message": str(error)},
        ) from error
    message_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    attachments = store_customer_images(
        client,
        business_id=claims["business_id"],
        conversation_id=claims["conversation_id"],
        images=images,
    )
    execute(
        client.table("customer_messages").insert(
            {
                "id": message_id,
                "business_id": claims["business_id"],
                "conversation_id": claims["conversation_id"],
                "sender_type": "customer",
                "sender_id": claims["visitor_id"],
                "text": body.text.strip()
                or "Please look at the image I sent and help me with it.",
                "attachments": attachments,
                "visibility": "customer",
                "delivery_status": "sent",
                "provider_message_id": f"website:{message_id}",
                "idempotency_key": f"website:{message_id}",
                "created_at": now,
            }
        )
    )
    execute(
        client.table("conversations")
        .update({"status": "needs_reply", "last_message_at": now})
        .eq("business_id", claims["business_id"])
        .eq("id", claims["conversation_id"])
    )
    execute(
        client.table("outbox_events").insert(
            {
                "business_id": claims["business_id"],
                "event_type": "conversation.message_created",
                "topic": "conversations",
                "data": {"conversation_id": claims["conversation_id"]},
                "dedupe_key": f"website:{message_id}",
            }
        )
    )
    background_tasks.add_task(
        _process_widget_message,
        client,
        claims=claims,
        user_text=body.text.strip(),
        message_id=message_id,
        images=images,
    )
    return {"status": "accepted", "message_id": message_id}


@router.websocket("/public/widgets/ws")
async def widget_websocket(
    websocket: WebSocket,
) -> None:
    try:
        token = next(
            (
                protocol[len("reactant-widget."):]
                for protocol in websocket.scope.get("subprotocols", [])
                if protocol.startswith("reactant-widget.")
            ),
            "",
        )
        claims = _read_session_token(token)
        client = get_service_supabase_client()
        _validate_session_origin(client, websocket, claims)
    except HTTPException as error:
        await websocket.close(code=4401 if error.status_code == 401 else 4403, reason="Widget session is not authorized.")
        return
    await websocket.accept(subprotocol=f"reactant-widget.{token}")
    try:
        while True:
            rows = await asyncio.to_thread(
                execute,
                client.table("customer_messages")
                .select("id,sender_type,text,attachments,created_at")
                .eq("business_id", claims["business_id"])
                .eq("conversation_id", claims["conversation_id"])
                .eq("visibility", "customer")
                .order("created_at", desc=True)
                .limit(40),
            )
            for row in reversed(rows):
                await websocket.send_json(
                    {
                        **row,
                        "attachments": signed_customer_attachments(
                            client,
                            business_id=claims["business_id"],
                            conversation_id=claims["conversation_id"],
                            attachments=row.get("attachments"),
                        ),
                    }
                )
            break
        last_created_at = rows[0]["created_at"] if rows else datetime.now(timezone.utc).isoformat()
        seen_ids = {row["id"] for row in rows}
        while True:
            await asyncio.sleep(1)
            new_rows = await asyncio.to_thread(
                execute,
                client.table("customer_messages")
                .select("id,sender_type,text,attachments,created_at")
                .eq("business_id", claims["business_id"])
                .eq("conversation_id", claims["conversation_id"])
                .eq("visibility", "customer")
                .gte("created_at", last_created_at)
                .order("created_at")
                .limit(40),
            )
            for row in new_rows:
                if row["id"] in seen_ids:
                    continue
                await websocket.send_json(
                    {
                        **row,
                        "attachments": signed_customer_attachments(
                            client,
                            business_id=claims["business_id"],
                            conversation_id=claims["conversation_id"],
                            attachments=row.get("attachments"),
                        ),
                    }
                )
                seen_ids.add(row["id"])
                last_created_at = max(last_created_at, row["created_at"])
    except WebSocketDisconnect:
        return
