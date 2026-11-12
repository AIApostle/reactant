import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from fastapi import HTTPException, status
from storage3.utils import StorageException
from supabase import Client

from src.schemas.agentcard import AgentCardItemRequest
from src.supabase.client import get_supabase_settings
from src.supabase.repository import execute


CHECKOUT_TOKEN_LENGTH = 43
CHECKOUT_TTL_MINUTES = 30


def _record(result: Any) -> dict[str, Any]:
    if isinstance(result, list):
        result = result[0] if result else None
    if not isinstance(result, dict):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "agentcard_unavailable",
                "message": "The transaction could not be completed right now.",
            },
        )
    return result


def _checkout_base_url() -> str:
    settings = get_supabase_settings()
    frontend_url = settings.frontend_url
    parsed = urlparse(frontend_url)
    if settings.app_env.lower() == "production" and (
        parsed.scheme != "https"
        or parsed.hostname in {"localhost", "127.0.0.1"}
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "public_url_unavailable",
                "message": "Set PUBLIC_FRONTEND_URL to the deployed HTTPS website before enabling customer checkout.",
            },
        )
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "public_url_unavailable",
                "message": "Set PUBLIC_FRONTEND_URL to an HTTPS website before enabling customer checkout.",
            },
        )
    if not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "public_url_unavailable",
                "message": "The public checkout website is not configured.",
            },
        )
    return frontend_url.rstrip("/")


def _paypal_integration(
    client: Client,
    business_id: str,
) -> str:
    integration = execute(
        client.table("integrations")
        .select("id")
        .eq("business_id", business_id)
        .eq("provider", "paypal")
        .eq("category", "payments")
        .eq("status", "connected")
        .maybe_single()
    )
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "paypal_not_connected",
                "message": "This business has not connected its PayPal account.",
            },
        )
    return integration["id"]


def _verify_paypal_eligibility(client: Client, business_id: str) -> None:
    settings = get_supabase_settings()
    if not settings.agentcard_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "agentcard_disabled",
                "message": "AgentCard transactions are not enabled for this deployment.",
            },
        )
    business = execute(
        client.table("businesses")
        .select("country")
        .eq("id", business_id)
        .single()
    )
    country = str(business.get("country") or "").strip().upper()
    eligible_countries = {
        value.strip().upper()
        for value in settings.paypal_receiving_countries.split(",")
        if value.strip()
    }
    sandbox_api = (
        settings.paypal_api_base_url.rstrip("/")
        == "https://api-m.sandbox.paypal.com"
    )
    sandbox_nigeria_allowed = sandbox_api and country == "NG"
    if country not in eligible_countries or (country == "NG" and not sandbox_nigeria_allowed):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "paypal_merchant_ineligible",
                "message": (
                    "PayPal receiving is not enabled for this business country in this "
                    "deployment. Add the country to PAYPAL_RECEIVING_COUNTRIES; Nigeria "
                    "is allowed only when PayPal Sandbox is configured."
                ),
            },
        )


def create_agentcard_transaction(
    client: Client,
    *,
    business_id: str,
    conversation_id: str,
    customer_name: str,
    customer_reference: str,
    items: list[AgentCardItemRequest],
    idempotency_key: str,
) -> dict[str, Any]:
    _verify_paypal_eligibility(client, business_id)
    checkout_base_url = _checkout_base_url()
    provider_integration_id = _paypal_integration(client, business_id)
    normalized_items = sorted(
        (
            {"product_id": str(item.product_id), "quantity": item.quantity}
            for item in items
        ),
        key=lambda item: item["product_id"],
    )
    if not normalized_items or len(normalized_items) > 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "validation_error", "message": "At least one valid product is required."},
        )
    payload_hash = hashlib.sha256(
        json.dumps(
            {
                "business_id": business_id,
                "conversation_id": conversation_id,
                "customer_name": customer_name[:160],
                "customer_reference": customer_reference[:255],
                "items": normalized_items,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    token = secrets.token_urlsafe(32)
    checkout_id = f"chk_{secrets.token_urlsafe(24)}"
    transaction_code = f"txn_{secrets.token_urlsafe(24)}"
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=CHECKOUT_TTL_MINUTES)
    result = _record(
        execute(
            client.rpc(
                "create_agentcard_transaction",
                {
                    "target_business_id": business_id,
                    "target_conversation_id": conversation_id,
                    "target_customer_name": customer_name[:160],
                    "target_customer_reference": customer_reference[:255],
                    "requested_items": normalized_items,
                    "requested_idempotency_key": idempotency_key[:200],
                    "requested_payload_hash": payload_hash,
                    "requested_transaction_id": transaction_code,
                    "requested_checkout_id": checkout_id,
                    "requested_token_hash": hashlib.sha256(token.encode()).hexdigest(),
                    "requested_provider_integration_id": provider_integration_id,
                    "requested_expires_at": expires_at.isoformat(),
                },
            )
        )
    )
    return {
        **result,
        "checkout_url": f"{checkout_base_url}/checkout/{token}",
    }


def _checkout_session(
    client: Client,
    token: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not token or len(token) != CHECKOUT_TOKEN_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "checkout_not_found", "message": "This checkout link is unavailable."},
        )
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    session = execute(
        client.table("agentcard_checkout_sessions")
        .select("id,business_id,transaction_id,checkout_id,status,expires_at,authorization_id")
        .eq("token_hash", token_hash)
        .maybe_single()
    )
    if not session or session["status"] not in {"active", "completed"}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "checkout_not_found", "message": "This checkout link is unavailable."},
        )
    transaction = execute(
        client.table("agentcard_transactions")
        .select(
            "id,business_id,order_id,public_transaction_id,conversation_id,customer_name,"
            "provider,provider_integration_id,currency,subtotal_minor,discount_total_minor,"
            "tax_total_minor,delivery_total_minor,total_amount_minor,status,checkout_snapshot,"
            "expires_at,paid_at,updated_at"
        )
        .eq("business_id", session["business_id"])
        .eq("id", session["transaction_id"])
        .maybe_single()
    )
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "checkout_not_found", "message": "This checkout link is unavailable."},
        )
    if (
        transaction["status"]
        not in {
            "paid",
            "reconciliation",
            "receipt_generation",
            "receipt_issued",
            "receipt_delivered",
            "partially_refunded",
            "refunded",
        }
        and datetime.fromisoformat(transaction["expires_at"].replace("Z", "+00:00"))
        <= datetime.now(timezone.utc)
    ):
        execute(
            client.rpc(
                "cancel_agentcard_transaction",
                {
                    "target_business_id": session["business_id"],
                    "target_transaction_id": session["transaction_id"],
                    "cancellation_source": "expiry",
                },
            )
        )
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"code": "checkout_expired", "message": "This checkout has expired. Return to the conversation for an updated checkout."},
        )
    return session, transaction


def checkout_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def checkout_hash(snapshot: dict[str, Any]) -> str:
    canonical = json.dumps(snapshot, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _signed_image_urls(
    client: Client,
    business_id: str,
    asset_ids: list[str],
) -> list[str]:
    if not asset_ids:
        return []
    assets = execute(
        client.table("media_assets")
        .select("id,delivery_path")
        .eq("business_id", business_id)
        .eq("status", "validated")
        .in_("id", asset_ids[:6])
    )
    urls: list[str] = []
    paths = {str(asset["id"]): asset.get("delivery_path") for asset in assets}
    for asset_id in asset_ids[:6]:
        path = paths.get(asset_id)
        if not isinstance(path, str):
            continue
        try:
            signed = client.storage.from_("product-media").create_signed_url(path, 3600)
        except (StorageException, OSError, TypeError, ValueError):
            continue
        url = signed.get("signedURL") or signed.get("signed_url")
        if isinstance(url, str):
            urls.append(url)
    return urls


def checkout_view(
    client: Client,
    session: dict[str, Any],
    transaction: dict[str, Any],
) -> dict[str, Any]:
    snapshot = transaction["checkout_snapshot"]
    items = []
    for item in snapshot["items"]:
        urls = _signed_image_urls(
            client,
            transaction["business_id"],
            [str(asset_id) for asset_id in item.get("image_asset_ids", [])],
        )
        provider_urls = item.get("provider_image_urls", [])
        if isinstance(provider_urls, list):
            urls.extend(
                url
                for url in provider_urls
                if isinstance(url, str) and url.startswith("https://")
            )
        items.append(
            {
                "product_id": item["product_id"],
                "name": item["name"],
                "description": item.get("description", ""),
                "quantity": item["quantity"],
                "unit_price_minor": item["unit_price_minor"],
                "total_minor": item["total_minor"],
                "image_urls": list(dict.fromkeys(urls))[:6],
            }
        )
    return {
        "checkout_id": session["checkout_id"],
        "public_transaction_id": transaction["public_transaction_id"],
        "business_name": snapshot["business"]["name"],
        "items": items,
        "subtotal_minor": transaction["subtotal_minor"],
        "discount_total_minor": transaction["discount_total_minor"],
        "tax_total_minor": transaction["tax_total_minor"],
        "delivery_total_minor": transaction["delivery_total_minor"],
        "total_amount_minor": transaction["total_amount_minor"],
        "currency": transaction["currency"],
        "status": transaction["status"],
        "expires_at": transaction["expires_at"],
        "authorization_required": transaction["status"] == "awaiting_customer",
    }


def checkout_status(
    client: Client,
    session: dict[str, Any],
    transaction: dict[str, Any],
) -> dict[str, Any]:
    receipt_url = None
    if transaction["status"] in {
        "paid",
        "reconciliation",
        "receipt_generation",
        "receipt_issued",
        "receipt_delivered",
        "partially_refunded",
        "refunded",
    }:
        receipt = execute(
            client.table("agentcard_receipts")
            .select("storage_path,status")
            .eq("business_id", transaction["business_id"])
            .eq("transaction_id", transaction["id"])
            .maybe_single()
        )
        if receipt and receipt.get("storage_path"):
            signed = client.storage.from_("agentcard-receipts").create_signed_url(
                receipt["storage_path"], 3600
            )
            receipt_url = signed.get("signedURL") or signed.get("signed_url")
    return {
        "public_transaction_id": transaction["public_transaction_id"],
        "status": transaction["status"],
        "amount_minor": transaction["total_amount_minor"],
        "currency": transaction["currency"],
        "updated_at": transaction["updated_at"],
        "receipt_url": receipt_url,
    }


def transaction_by_provider_order(
    client: Client,
    provider_order_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payment = execute(
        client.table("agentcard_payments")
        .select("business_id,transaction_id,provider_order_id")
        .eq("provider", "paypal")
        .eq("provider_order_id", provider_order_id)
        .maybe_single()
    )
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "agentcard_payment_not_found", "message": "The payment attempt was not found."},
        )
    transaction = execute(
        client.table("agentcard_transactions")
        .select("id,business_id,public_transaction_id,total_amount_minor,currency,provider_integration_id")
        .eq("business_id", payment["business_id"])
        .eq("id", payment["transaction_id"])
        .single()
    )
    return payment, transaction
