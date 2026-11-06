import base64
import asyncio
import hashlib
import hmac
import json
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError
from supabase import Client

from src.schemas.common import ResourceEnvelope
from src.schemas.webhooks import ProviderWebhookPayload, WebhookAck
from src.supabase.client import (
    get_service_supabase_client,
    get_supabase_settings,
)
from src.supabase.repository import execute
from cryptography.fernet import Fernet, InvalidToken


router = APIRouter()
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


def _ack(request: Request, duplicate: bool) -> ResourceEnvelope[WebhookAck]:
    return ResourceEnvelope(
        data=WebhookAck(received=True, duplicate=duplicate),
        request_id=request.state.request_id,
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
) -> ResourceEnvelope[WebhookAck]:
    secret = request.headers.get("x-telegram-bot-api-secret-token")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_webhook_signature", "message": "The webhook signature is invalid."},
        )
    _, payload = await _read_payload(request)
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
    duplicate = await asyncio.to_thread(
        _persist_event,
        client,
        provider="telegram",
        resource_id=str(channel_id),
        business_id=business_id,
        event_id=str(update_id),
        event_type="telegram.update_received",
        payload=payload,
        topic="conversations",
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
    client_id = credentials.get("consumer_key")
    client_secret = credentials.get("consumer_secret")
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
            access_token = token_response.json().get("access_token")
            if not isinstance(access_token, str):
                raise ValueError("PayPal access token missing.")
            verification_response = await http.post(
                f"{api_base}/v1/notifications/verify-webhook-signature",
                headers={"Authorization": f"Bearer {access_token}"},
                json=verification_payload,
            )
            verification_response.raise_for_status()
            verification = verification_response.json()
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
