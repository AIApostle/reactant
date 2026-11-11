import base64
import asyncio
import hashlib
import hmac
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from pydantic import ValidationError
from supabase import Client

from src.schemas.common import ResourceEnvelope
from src.schemas.webhooks import ProviderWebhookPayload, WebhookAck
from src.agent.config import agent_is_enabled, get_agent_runtime_settings
from src.agent.customer_images import (
    MAX_CUSTOMER_IMAGE_BYTES,
    CustomerImage,
    history_with_customer_images,
    normalize_customer_image,
    store_customer_images,
)
from src.agent.runtime import (
    build_business_agent,
    find_business_products,
    invoke_business_agent,
    product_image_attachments,
    product_image_query,
    product_image_reply,
)
from src.supabase.client import (
    get_service_supabase_client,
    get_supabase_settings,
)
from src.supabase.repository import execute
from cryptography.fernet import Fernet, InvalidToken
from src.agentcard.paypal import PayPalError, platform_paypal_credentials
from src.agentcard.routes import process_verified_paypal_webhook


router = APIRouter()
logger = logging.getLogger(__name__)
MAX_WEBHOOK_BODY = 1024 * 1024


async def _read_payload(request: Request) -> tuple[bytes, dict[str, Any]]:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_WEBHOOK_BODY:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail={"code": "payload_too_large", "message": "The webhook payload is too large."},
                )
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "malformed_request", "message": "The webhook request is malformed."},
            ) from error
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_WEBHOOK_BODY:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={"code": "payload_too_large", "message": "The webhook payload is too large."},
            )
    try:
        payload = ProviderWebhookPayload.model_validate_json(bytes(content))
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "malformed_request", "message": "The webhook request is malformed."},
        ) from error
    return bytes(content), payload.model_dump(mode="json", exclude_none=True)


def _integration_credentials(
    client: Client,
    integration_id: UUID,
    provider: str,
) -> tuple[dict[str, Any], UUID]:
    integration = execute(
        client.table("integrations")
        .select("id,business_id,credentials_ciphertext,status")
        .eq("id", str(integration_id))
        .eq("provider", provider)
        .maybe_single()
    )
    if not integration or integration["status"] in {"disconnected", "revoked"}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The integration was not found."},
        )
    encryption_key = get_supabase_settings().credentials_encryption_key
    if not encryption_key or not integration.get("credentials_ciphertext"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "webhook_verification_unavailable", "message": "Webhook verification is not configured."},
        )
    try:
        decrypted = Fernet(encryption_key.get_secret_value().encode()).decrypt(
            integration["credentials_ciphertext"].encode()
        )
        credentials = json.loads(decrypted)
    except (ValueError, TypeError, InvalidToken, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "webhook_verification_unavailable", "message": "Webhook verification is not configured."},
        ) from error
    if not isinstance(credentials, dict):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "webhook_verification_unavailable", "message": "Webhook verification is not configured."},
        )
    return credentials, UUID(integration["business_id"])


def _persist_event(
    client: Client,
    *,
    provider: str,
    resource_id: str,
    business_id: UUID,
    event_id: str,
    event_type: str,
    payload: dict[str, Any],
    topic: str,
) -> bool:
    duplicate = False
    try:
        execute(
            client.table("provider_events").insert(
                {
                    "provider": provider,
                    "provider_event_id": event_id,
                    "resource_id": resource_id,
                    "payload": payload,
                }
            )
        )
    except HTTPException as error:
        if error.status_code != status.HTTP_409_CONFLICT:
            raise
        duplicate = True
    dedupe_key = f"{provider}:{resource_id}:{event_id}"
    try:
        execute(
            client.table("outbox_events").insert(
                {
                    "business_id": str(business_id),
                    "event_type": event_type,
                    "topic": topic,
                    "data": {
                        "provider": provider,
                        "provider_event_id": event_id,
                        "resource_id": resource_id,
                    },
                    "dedupe_key": dedupe_key,
                }
            )
        )
    except HTTPException as error:
        if error.status_code != status.HTTP_409_CONFLICT:
            raise
        duplicate = True
    return duplicate


def _redact_telegram_pairing_code(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(payload)
    message = payload.get("message")
    if not isinstance(message, dict):
        return redacted
    redacted_message = dict(message)
    for field in ("text", "caption"):
        value = redacted_message.get(field)
        if isinstance(value, str):
            redacted_message[field] = re.sub(
                r"(?i)(/pair(?:@\w+)?\s+)[A-Za-z0-9_-]{20,100}",
                r"\1[REDACTED]",
                value,
            )
    redacted["message"] = redacted_message
    return redacted


def _ack(request: Request, duplicate: bool) -> ResourceEnvelope[WebhookAck]:
    return ResourceEnvelope(
        data=WebhookAck(received=True, duplicate=duplicate),
        request_id=request.state.request_id,
    )


def _telegram_send_message(bot_token: str, chat_id: str, text: str) -> None:
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text[:4096]},
            timeout=15,
        )
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise RuntimeError("Telegram message delivery failed.") from error
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError("Telegram message delivery failed.")


def _telegram_send_long_message(bot_token: str, chat_id: str, text: str) -> None:
    for offset in range(0, len(text), 4000):
        _telegram_send_message(bot_token, chat_id, text[offset : offset + 4000])


def _telegram_send_photo(bot_token: str, chat_id: str, image_url: str, caption: str = "") -> None:
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendPhoto",
            json={"chat_id": chat_id, "photo": image_url, "caption": caption[:1024]},
            timeout=15,
        )
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise RuntimeError("Telegram image delivery failed.") from error
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError("Telegram image delivery failed.")


def _send_owner_telegram_notice(bot_token: str, chat_id: str, text: str) -> None:
    try:
        _telegram_send_long_message(bot_token, chat_id, text)
    except RuntimeError as error:
        logger.warning(
            "Owner Telegram notice could not be delivered exception_type=%s",
            type(error).__name__,
        )


def _handle_owner_telegram_update(
    client: Client,
    *,
    channel_id: UUID,
    business_id: UUID,
    bot_token: str,
    chat: dict[str, Any],
    sender: dict[str, Any],
    text: str,
    update_id: str,
) -> bool:
    chat_id = str(chat.get("id", ""))
    sender_id = str(sender.get("id", ""))
    private_chat = chat.get("type") == "private" and chat_id and sender_id == chat_id
    pair_command = text.strip().startswith("/pair")
    if pair_command:
        if not private_chat:
            return True
        match = re.fullmatch(r"/pair(?:@\w+)?\s+([A-Za-z0-9_-]{20,100})", text.strip())
        if not match:
            _send_owner_telegram_notice(
                bot_token,
                chat_id,
                "That pairing code is invalid. Generate a new code in Reactant and send `/pair <code>` here.",
            )
            return True
        token_hash = hashlib.sha256(match.group(1).encode()).hexdigest()
        try:
            owner_id = execute(
                client.rpc(
                    "pair_owner_telegram_chat",
                    {
                        "target_business_id": str(business_id),
                        "target_integration_id": str(channel_id),
                        "requested_token_hash": token_hash,
                        "requested_chat_id": chat_id,
                    },
                )
            )
        except HTTPException as error:
            logger.warning(
                "Telegram owner pairing is unavailable business_id=%s error_code=%s",
                business_id,
                (error.detail.get("code") if isinstance(error.detail, dict) else "database_unavailable"),
            )
            _send_owner_telegram_notice(
                bot_token,
                chat_id,
                "Owner pairing is not available right now. Apply the latest Reactant database migration and try again.",
            )
            return True
        if owner_id:
            _send_owner_telegram_notice(
                bot_token,
                chat_id,
                "Owner channel connected. This private chat can now message your Reactant agent and review approvals.",
            )
        else:
            _send_owner_telegram_notice(
                bot_token,
                chat_id,
                "That pairing code has expired or is invalid. Generate a new code in Reactant.",
            )
        return True

    if not private_chat:
        return False


    try:
        channel = execute(
            client.table("owner_telegram_channels")
            .select("owner_user_id")
            .eq("business_id", str(business_id))
            .eq("integration_id", str(channel_id))
            .eq("telegram_chat_id", chat_id)
            .not_.is_("paired_at", "null")
            .maybe_single()
        )
    except HTTPException as error:
        detail = error.detail if isinstance(error.detail, dict) else {}
        if detail.get("code") != "database_schema_outdated":
            raise
        logger.warning(
            "Owner Telegram channel is unavailable until migrations are applied business_id=%s",
            business_id,
        )
        return False
    if not channel:
        return False

    stripped_text = text.strip()
    if re.fullmatch(r"/(?:help|start)(?:@\w+)?", stripped_text):
        _send_owner_telegram_notice(
            bot_token,
            chat_id,
            "Send a message to talk to your business agent. For an approval, reply with `/approve <approval-id>` or `/reject <approval-id>`.",
        )
        return True

    decision = re.fullmatch(
        r"/(approve|reject)(?:@\w+)?\s+([0-9a-fA-F-]{36})",
        stripped_text,
    )
    if decision:
        try:
            approval_id = UUID(decision.group(2))
            result = execute(
                client.rpc(
                    "decide_telegram_approval",
                    {
                        "target_business_id": str(business_id),
                        "target_integration_id": str(channel_id),
                        "target_chat_id": chat_id,
                        "target_approval_id": str(approval_id),
                        "requested_decision": (
                            "approved" if decision.group(1) == "approve" else "rejected"
                        ),
                        "requested_note": "Decided from the verified Telegram owner channel.",
                        "requested_idempotency_key": (
                            f"telegram-owner-approval:{channel_id}:{update_id}"
                        ),
                    },
                )
            )
        except HTTPException as error:
            message = (
                "That approval is no longer pending."
                if error.status_code in {404, 409}
                else "This owner account can no longer decide approvals for the workspace."
            )
            _send_owner_telegram_notice(bot_token, chat_id, message)
            return True
        decision_text = "approved" if decision.group(1) == "approve" else "rejected"
        _send_owner_telegram_notice(
            bot_token,
            chat_id,
            f"Approval {result['id']} was {decision_text}.",
        )
        return True

    if stripped_text.startswith("/"):
        _send_owner_telegram_notice(
            bot_token,
            chat_id,
            "Command not recognized. Send `/help` for owner-channel commands.",
        )
        return True
    if not stripped_text:
        _send_owner_telegram_notice(
            bot_token,
            chat_id,
            "Send a text message to talk to your business agent.",
        )
        return True
    if len(stripped_text) > 4000:
        _send_owner_telegram_notice(
            bot_token,
            chat_id,
            "Keep owner-channel messages under 4,000 characters, then send again.",
        )
        return True
    try:
        execute(
            client.rpc(
                "enqueue_owner_telegram_message",
                {
                    "target_business_id": str(business_id),
                    "target_integration_id": str(channel_id),
                    "target_chat_id": chat_id,
                    "requested_text": stripped_text,
                    "requested_idempotency_key": (
                        f"telegram-owner:{channel_id}:{update_id}"
                    ),
                },
            )
        )
    except HTTPException as error:
        logger.warning(
            "Owner Telegram message could not be queued business_id=%s exception_type=%s",
            business_id,
            type(error).__name__,
        )
        _send_owner_telegram_notice(
            bot_token,
            chat_id,
            "Your message could not be sent to the agent. Confirm owner access is still active and try again.",
        )
        return True
    _send_owner_telegram_notice(bot_token, chat_id, "Message sent to your Reactant agent.")
    return True


def _wants_product_images(text: str) -> bool:
    return bool(re.search(r"\b(image|images|photo|photos|picture|pictures|show me|send me|see it)\b", text, re.I))


def _mark_telegram_connected(client: Client, integration_id: UUID) -> None:
    now = datetime.now(timezone.utc).isoformat()
    execute(
        client.table("integrations")
        .update(
            {
                "status": "connected",
                "connected_at": now,
                "last_success_at": now,
                "last_error": None,
                "sync_status": "ready",
                "updated_at": now,
            }
        )
        .eq("id", str(integration_id))
        .eq("provider", "telegram")
    )


def _telegram_download_image(bot_token: str, file_id: str) -> CustomerImage:
    try:
        with httpx.Client(timeout=20, follow_redirects=False) as http:
            file_response = http.get(
                f"https://api.telegram.org/bot{bot_token}/getFile",
                params={"file_id": file_id},
            )
            file_response.raise_for_status()
            file_payload = file_response.json()
            file_data = file_payload.get("result") if isinstance(file_payload, dict) else None
            file_path = file_data.get("file_path") if isinstance(file_data, dict) else None
            file_size = file_data.get("file_size") if isinstance(file_data, dict) else None
            if (
                not isinstance(file_payload, dict)
                or not file_payload.get("ok")
                or not isinstance(file_path, str)
                or not file_path
                or ".." in file_path.split("/")
                or len(file_path) > 512
                or not re.fullmatch(r"[A-Za-z0-9_./-]+", file_path)
            ):
                raise ValueError("Telegram did not return a valid image file.")
            if isinstance(file_size, int) and file_size > MAX_CUSTOMER_IMAGE_BYTES:
                raise ValueError("The Telegram image is larger than 5 MB.")
            file_url = (
                f"https://api.telegram.org/file/bot{bot_token}/{quote(file_path, safe='/')}"
            )
            with http.stream("GET", file_url) as image_response:
                image_response.raise_for_status()
                content_length = image_response.headers.get("content-length")
                if content_length and int(content_length) > MAX_CUSTOMER_IMAGE_BYTES:
                    raise ValueError("The Telegram image is larger than 5 MB.")
                content = bytearray()
                for chunk in image_response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_CUSTOMER_IMAGE_BYTES:
                        raise ValueError("The Telegram image is larger than 5 MB.")
    except (httpx.HTTPError, ValueError) as error:
        raise RuntimeError("The Telegram image could not be downloaded.") from error
    return normalize_customer_image(bytes(content), file_path.rsplit("/", 1)[-1])


def _telegram_message_images(
    bot_token: str,
    message: dict[str, Any],
) -> list[CustomerImage]:
    photo_sizes = message.get("photo")
    file_id: str | None = None
    file_name = "telegram-image"
    if isinstance(photo_sizes, list):
        candidates = [
            photo
            for photo in photo_sizes
            if isinstance(photo, dict) and isinstance(photo.get("file_id"), str)
        ]
        if candidates:
            largest = max(
                candidates,
                key=lambda photo: int(photo.get("file_size") or 0)
                or int(photo.get("width") or 0) * int(photo.get("height") or 0),
            )
            file_id = largest["file_id"]
    document = message.get("document")
    if (
        file_id is None
        and isinstance(document, dict)
        and document.get("mime_type") in {"image/jpeg", "image/png", "image/webp"}
        and isinstance(document.get("file_id"), str)
    ):
        file_id = document["file_id"]
        file_name = str(document.get("file_name") or file_name)
    if file_id is None:
        return []
    image = _telegram_download_image(bot_token, file_id)
    return [CustomerImage(image.data, image.content_type, file_name or image.file_name)]


def _process_telegram_update(
    client: Client,
    *,
    channel_id: UUID,
    business_id: UUID,
    credentials: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    message = payload.get("message")
    if not isinstance(message, dict):
        return
    chat = message.get("chat")
    sender = message.get("from")
    if not isinstance(chat, dict) or not isinstance(sender, dict):
        return
    chat_id = str(chat.get("id", ""))
    update_id = str(payload["update_id"])
    text = message.get("text") or message.get("caption") or ""
    if not isinstance(text, str):
        text = ""
    if _handle_owner_telegram_update(
        client,
        channel_id=channel_id,
        business_id=business_id,
        bot_token=credentials["bot_token"],
        chat=chat,
        sender=sender,
        text=text,
        update_id=update_id,
    ):
        return
    try:
        customer_images = _telegram_message_images(credentials["bot_token"], message)
    except (RuntimeError, ValueError) as error:
        logger.warning(
            "Telegram customer image could not be processed update_id=%s exception_type=%s",
            update_id,
            type(error).__name__,
        )
        _telegram_send_message(
            credentials["bot_token"],
            chat_id,
            "I couldn't read that image. Please resend it as a JPEG, PNG, or WebP under 5 MB.",
        )
        return
    if customer_images and not text.strip():
        text = "Please look at the image I sent and help me with it."
    elif customer_images:
        text = f"{text}\n[Customer included an image with this message.]"
    if not chat_id or not isinstance(text, str) or not text.strip():
        return
    provider_conversation_id = f"telegram:{chat_id}"
    customer_name = " ".join(
        part
        for part in (sender.get("first_name"), sender.get("last_name"))
        if isinstance(part, str) and part.strip()
    ).strip()
    if not customer_name:
        username = sender.get("username")
        customer_name = f"@{username}" if isinstance(username, str) and username.strip() else "Telegram customer"
    conversation_rows = execute(
        client.table("conversations")
        .select("id")
        .eq("business_id", str(business_id))
        .eq("provider_conversation_id", provider_conversation_id)
        .limit(1)
    )
    conversation = conversation_rows[0] if conversation_rows else None
    now = datetime.now(timezone.utc).isoformat()
    if not conversation:
        conversation = execute(
            client.table("conversations")
            .insert(
                {
                    "business_id": str(business_id),
                    "channel": "telegram",
                    "provider_conversation_id": provider_conversation_id,
                    "status": "needs_reply",
                    "customer_context": {
                        "telegram_chat_id": chat_id,
                        "telegram_user_id": str(sender.get("id", "")),
                        "telegram_username": sender.get("username"),
                        "customer_name": customer_name,
                    },
                    "last_message_at": now,
                }
            )
            .select("id")
            .single()
        )
    message_id = str(uuid4())
    image_attachments = store_customer_images(
        client,
        business_id=str(business_id),
        conversation_id=str(conversation["id"]),
        images=customer_images,
    )
    customer_message = execute(
        client.table("customer_messages")
        .insert(
            {
                "id": message_id,
                "business_id": str(business_id),
                "conversation_id": conversation["id"],
                "sender_type": "customer",
                "sender_id": str(sender.get("id", "")),
                "text": text[:10000],
                "visibility": "customer",
                "delivery_status": "sent",
                "attachments": image_attachments,
                "provider_message_id": update_id,
                "idempotency_key": f"telegram:{channel_id}:{update_id}",
                "created_at": now,
            }
        )
        .select("id")
        .single()
    )
    del customer_message
    execute(
        client.table("outbox_events").insert(
            {
                "business_id": str(business_id),
                "event_type": "conversation.message_created",
                "topic": "conversations",
                "data": {"conversation_id": conversation["id"]},
                "dedupe_key": f"telegram-message:{channel_id}:{update_id}",
            }
        )
    )
    business = execute(
        client.table("businesses")
        .select("name,country,currency,return_policy,delivery_policy")
        .eq("id", str(business_id))
        .single()
    )
    agent_config = execute(
        client.table("agent_configs")
        .select("enabled,business_context,tone,handoff_rule,permissions,approval_policy")
        .eq("business_id", str(business_id))
        .maybe_single()
    )
    if not agent_is_enabled(agent_config):
        logger.info(
            "Telegram agent response skipped because the business agent is disabled business_id=%s",
            business_id,
        )
        return
    settings = get_agent_runtime_settings()
    if not settings.strands_agent_enabled or settings.openrouter_api_key is None:
        return
    history_rows = execute(
        client.table("customer_messages")
        .select("id,sender_type,text,attachments")
        .eq("business_id", str(business_id))
        .eq("conversation_id", conversation["id"])
        .neq("id", message_id)
        .order("created_at", desc=True)
        .limit(8)
    )
    history = history_with_customer_images(
        client,
        business_id=str(business_id),
        conversation_id=str(conversation["id"]),
        rows=history_rows,
    )
    created_checkout_urls: list[str] = []
    selected_product_images: list[dict[str, Any]] = []
    agent = build_business_agent(
        client=client,
        business_id=str(business_id),
        settings=settings,
        business=business,
        agent_config=agent_config,
        history=history,
        audience="customer",
        conversation_id=str(conversation["id"]),
        customer_name=customer_name,
        customer_reference=chat_id,
        idempotency_key=f"telegram:{channel_id}:{update_id}",
        created_checkout_urls=created_checkout_urls,
        selected_product_images=selected_product_images,
        vision_enabled=bool(customer_images),
    )
    response_text = invoke_business_agent(
        agent,
        text,
        audience="customer",
        images=customer_images,
    )
    image_requested = _wants_product_images(text)
    image_products = selected_product_images
    if image_requested:
        image_query = product_image_query(text, history_rows)
        if image_query:
            matching_products = find_business_products(
                client,
                str(business_id),
                image_query,
                limit=3,
            )
            if matching_products:
                image_products = matching_products
    image_attachments = product_image_attachments(
        image_products,
        response_text,
        explicitly_requested=image_requested,
    )
    sent_image_attachments: list[dict[str, str]] = []
    image_delivery_failed = False
    if created_checkout_urls:
        response_text = (
            f"{response_text}\n\nSecure checkout: {created_checkout_urls[-1]}"
        )
    for attachment in image_attachments:
        try:
            _telegram_send_photo(
                credentials["bot_token"],
                chat_id,
                attachment["url"],
                caption=attachment["alt"],
            )
        except RuntimeError as error:
            image_delivery_failed = True
            logger.error(
                "Telegram product image delivery failed conversation_id=%s exception_type=%s",
                conversation["id"],
                type(error).__name__,
            )
        else:
            sent_image_attachments.append(attachment)
    response_text = product_image_reply(
        response_text,
        sent_image_attachments,
        explicitly_requested=image_requested,
        delivery_failed=image_delivery_failed,
    )
    _telegram_send_message(credentials["bot_token"], chat_id, response_text)
    execute(
        client.table("customer_messages")
        .insert(
            {
                "business_id": str(business_id),
                "conversation_id": conversation["id"],
                "sender_type": "agent",
                "sender_id": "business-agent",
                "text": response_text,
                "visibility": "customer",
                "delivery_status": "sent",
                "attachments": sent_image_attachments,
                "provider_message_id": f"agent:{update_id}",
                "idempotency_key": f"agent:telegram:{channel_id}:{update_id}",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    )
    execute(
        client.table("outbox_events").insert(
            {
                "business_id": str(business_id),
                "event_type": "conversation.message_created",
                "topic": "conversations",
                "data": {"conversation_id": conversation["id"]},
                "dedupe_key": f"telegram-agent-message:{channel_id}:{update_id}",
            }
        )
    )
    execute(
        client.table("conversations")
        .update({"status": "open", "last_message_at": datetime.now(timezone.utc).isoformat()})
        .eq("business_id", str(business_id))
        .eq("id", conversation["id"])
    )


@router.post(
    "/webhooks/woocommerce/{integration_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ResourceEnvelope[WebhookAck],
)
async def receive_woocommerce_webhook(
    integration_id: UUID,
    request: Request,
) -> ResourceEnvelope[WebhookAck]:
    signature = request.headers.get("x-wc-webhook-signature")
    event_id = request.headers.get("x-wc-webhook-id")
    event_type = request.headers.get("x-wc-webhook-event")
    if not signature or not event_id or len(event_id) > 255 or not event_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "malformed_request", "message": "The webhook request is malformed."},
        )
    content, payload = await _read_payload(request)
    client = get_service_supabase_client()
    credentials, business_id = await asyncio.to_thread(
        _integration_credentials, client, integration_id, "woocommerce"
    )
    webhook_secret = credentials.get("webhook_secret")
    if not isinstance(webhook_secret, str):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "webhook_verification_unavailable", "message": "Webhook verification is not configured."},
        )
    expected = base64.b64encode(
        hmac.new(webhook_secret.encode(), content, hashlib.sha256).digest()
    ).decode()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_webhook_signature", "message": "The webhook signature is invalid."},
        )
    duplicate = await asyncio.to_thread(
        _persist_event,
        client,
        provider="woocommerce",
        resource_id=str(integration_id),
        business_id=business_id,
        event_id=event_id,
        event_type=f"woocommerce.{event_type}",
        payload=payload,
        topic="integrations",
    )
    return _ack(request, duplicate)


@router.post(
    "/webhooks/telegram/{channel_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ResourceEnvelope[WebhookAck],
)
async def receive_telegram_webhook(
    channel_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
) -> ResourceEnvelope[WebhookAck]:
    secret = request.headers.get("x-telegram-bot-api-secret-token")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_webhook_signature", "message": "The webhook signature is invalid."},
        )
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            too_large = int(content_length) > MAX_WEBHOOK_BODY
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "malformed_request", "message": "The webhook request is malformed."},
            ) from error
        if too_large:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={"code": "payload_too_large", "message": "The webhook payload is too large."},
            )
    try:
        payload = json.loads(await request.body())
    except (ValueError, UnicodeDecodeError) as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "malformed_request", "message": "The webhook request is malformed."},
        ) from error
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "malformed_request", "message": "The webhook request is malformed."},
        )
    update_id = payload.get("update_id")
    if not isinstance(update_id, (int, str)) or len(str(update_id)) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "malformed_request", "message": "The webhook request is malformed."},
        )
    client = get_service_supabase_client()
    credentials, business_id = await asyncio.to_thread(
        _integration_credentials, client, channel_id, "telegram"
    )
    configured_secret = credentials.get("webhook_secret")
    if not isinstance(configured_secret, str) or not hmac.compare_digest(secret, configured_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_webhook_signature", "message": "The webhook signature is invalid."},
        )
    await asyncio.to_thread(_mark_telegram_connected, client, channel_id)
    duplicate = await asyncio.to_thread(
        _persist_event,
        client,
        provider="telegram",
        resource_id=str(channel_id),
        business_id=business_id,
        event_id=str(update_id),
        event_type="telegram.update_received",
        payload=_redact_telegram_pairing_code(payload),
        topic="conversations",
    )
    if not duplicate:
        background_tasks.add_task(
            _process_telegram_update,
            client,
            channel_id=channel_id,
            business_id=business_id,
            credentials=credentials,
            payload=payload,
        )
    return _ack(request, duplicate)


@router.post(
    "/webhooks/paypal/{integration_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ResourceEnvelope[WebhookAck],
)
async def receive_paypal_webhook(
    integration_id: UUID,
    request: Request,
) -> ResourceEnvelope[WebhookAck]:
    _, payload = await _read_payload(request)
    event_id = payload.get("id")
    event_type = payload.get("event_type")
    if not isinstance(event_id, str) or not event_id or len(event_id) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "malformed_request", "message": "The webhook request is malformed."},
        )
    if not isinstance(event_type, str) or not event_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "malformed_request", "message": "The webhook request is malformed."},
        )
    client = get_service_supabase_client()
    credentials, business_id = await asyncio.to_thread(
        _integration_credentials, client, integration_id, "paypal"
    )
    webhook_id = credentials.get("webhook_id")
    if credentials.get("mode") != "partner_after_payment":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "webhook_verification_unavailable", "message": "This integration is not configured for PayPal seller onboarding webhook verification."},
        )
    try:
        platform_credentials = platform_paypal_credentials()
    except PayPalError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "webhook_verification_unavailable", "message": "PayPal partner credentials are not configured for webhook verification."},
        ) from error
    client_id = platform_credentials["client_id"]
    client_secret = platform_credentials["client_secret"]
    api_base = get_supabase_settings().paypal_api_base_url.rstrip("/")
    if (
        not isinstance(webhook_id, str)
        or not isinstance(client_id, str)
        or not isinstance(client_secret, str)
        or api_base not in {"https://api-m.paypal.com", "https://api-m.sandbox.paypal.com"}
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "webhook_verification_unavailable", "message": "Webhook verification is not configured."},
        )
    verification_payload = {
        "auth_algo": request.headers.get("paypal-auth-algo"),
        "cert_url": request.headers.get("paypal-cert-url"),
        "transmission_id": request.headers.get("paypal-transmission-id"),
        "transmission_sig": request.headers.get("paypal-transmission-sig"),
        "transmission_time": request.headers.get("paypal-transmission-time"),
        "webhook_id": webhook_id,
        "webhook_event": payload,
    }
    if not all(
        isinstance(verification_payload[key], str)
        for key in (
            "auth_algo",
            "cert_url",
            "transmission_id",
            "transmission_sig",
            "transmission_time",
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_webhook_signature", "message": "The webhook signature is invalid."},
        )
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as http:
            token_response = await http.post(
                f"{api_base}/v1/oauth2/token",
                auth=(client_id, client_secret),
                data={"grant_type": "client_credentials"},
            )
            token_response.raise_for_status()
            token_payload = token_response.json()
            access_token = (
                token_payload.get("access_token")
                if isinstance(token_payload, dict)
                else None
            )
            if not isinstance(access_token, str):
                raise ValueError("PayPal access token missing.")
            verification_response = await http.post(
                f"{api_base}/v1/notifications/verify-webhook-signature",
                headers={"Authorization": "Bearer {}".format(access_token)},
                json=verification_payload,
            )
            verification_response.raise_for_status()
            verification = verification_response.json()
            if not isinstance(verification, dict):
                raise ValueError("PayPal webhook verification response is invalid.")
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "webhook_verification_unavailable", "message": "The webhook could not be verified right now."},
        ) from error
    if verification.get("verification_status") != "SUCCESS":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_webhook_signature", "message": "The webhook signature is invalid."},
        )
    topic = "orders" if event_type.startswith(("CHECKOUT.ORDER.", "PAYMENT.CAPTURE.")) else "integrations"
    duplicate = await asyncio.to_thread(
        _persist_event,
        client,
        provider="paypal",
        resource_id=str(integration_id),
        business_id=business_id,
        event_id=event_id,
        event_type=f"paypal.{event_type.lower()}",
        payload=payload,
        topic=topic,
    )
    try:
        await asyncio.to_thread(
            process_verified_paypal_webhook,
            client,
            integration_id=str(integration_id),
            business_id=str(business_id),
            payload=payload,
        )
    except (HTTPException, PayPalError) as error:
        try:
            await asyncio.to_thread(
                execute,
                client.table("agentcard_webhook_events")
                .update(
                    {
                        "processing_status": "failed",
                        "failure_reason": type(error).__name__,
                        "processed_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                .eq("provider", "paypal")
                .eq("provider_event_id", event_id),
            )
        except HTTPException as persistence_error:
            logger.error(
                "PayPal webhook failure state could not be saved event_id=%s exception_type=%s",
                event_id,
                type(persistence_error).__name__,
            )
        logger.error(
            "Verified PayPal webhook processing failed event_id=%s exception_type=%s",
            event_id,
            type(error).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "paypal_event_processing_unavailable",
                "message": "The verified PayPal event could not be processed yet.",
            },
        ) from error
    return _ack(request, duplicate)


@router.post(
    "/webhooks/whatsapp/{channel_id}",
    openapi_extra={"x-implementation-status": "planned"},
)
async def receive_whatsapp_webhook(channel_id: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "webhook_not_configured", "message": "WhatsApp webhooks are not configured."},
    )
