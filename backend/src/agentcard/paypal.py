import json
import logging
import re
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status
from supabase import Client

from src.supabase.client import get_supabase_settings
from src.supabase.repository import execute


logger = logging.getLogger(__name__)


class PayPalError(RuntimeError):
    pass


PAYPAL_PARTNER_CONFIGURATION_MESSAGE = (
    "PayPal is not configured on the backend. Check PAYPAL_CLIENT_ID, "
    "PAYPAL_SECRET_KEY, PAYPAL_PARTNER_ATTRIBUTION_ID (or PAYPAL_BN_CODE), "
    "PAYPAL_ONBOARDING_AFTER_PAYMENT_ENABLED, and PAYPAL_API_BASE_URL."
)


def _log_paypal_request_failure(method: str, path: str, error: Exception) -> None:
    response = error.response if isinstance(error, httpx.HTTPStatusError) else None
    status_code = response.status_code if response is not None else None
    debug_id = (
        response.headers.get("paypal-debug-id", "")[:128]
        if response is not None
        else ""
    )
    error_name = "unknown"
    issue_codes: list[str] = []
    if response is not None:
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            provider_error = body.get("error")
            error_name = body.get("name", "unknown")
            details = body.get("details", [])
            if isinstance(provider_error, dict):
                error_name = provider_error.get("name", error_name)
                details = provider_error.get("details", details)
            if not isinstance(error_name, str):
                error_name = "unknown"
            error_name = re.sub(r"[^A-Za-z0-9_.-]", "_", error_name)[:64] or "unknown"
            if isinstance(details, list):
                issue_codes = [
                    re.sub(r"[^A-Za-z0-9_.-]", "_", item["issue"])[:64]
                    for item in details
                    if isinstance(item, dict) and isinstance(item.get("issue"), str)
                ][:10]

    logger.warning(
        "PayPal API request failed method=%s path=%s status=%s debug_id=%s error_name=%s issue_codes=%s exception_type=%s",
        method,
        path,
        status_code,
        debug_id or "unavailable",
        error_name,
        ",".join(issue_codes) or "unavailable",
        type(error).__name__,
    )


def platform_paypal_credentials() -> dict[str, str]:
    settings = get_supabase_settings()
    if (
        not settings.paypal_onboarding_after_payment_enabled
        or settings.paypal_api_base_url.rstrip("/")
        not in {"https://api-m.sandbox.paypal.com", "https://api-m.paypal.com"}
        or settings.paypal_client_id is None
        or settings.paypal_secret_key is None
        or not settings.paypal_partner_attribution_id
    ):
        raise PayPalError(PAYPAL_PARTNER_CONFIGURATION_MESSAGE)
    return {
        "client_id": settings.paypal_client_id.get_secret_value(),
        "client_secret": settings.paypal_secret_key.get_secret_value(),
        "partner_attribution_id": settings.paypal_partner_attribution_id,
    }


def _paypal_api_base() -> str:
    base_url = get_supabase_settings().paypal_api_base_url.rstrip("/")
    if base_url not in {
        "https://api-m.sandbox.paypal.com",
        "https://api-m.paypal.com",
    }:
        raise PayPalError("PayPal API endpoint is not supported.")
    return base_url


def paypal_credentials(
    client: Client,
    business_id: str,
    integration_id: str,
) -> dict[str, str]:
    integration = execute(
        client.table("integrations")
        .select("id,credentials_ciphertext,status,sync_status")
        .eq("business_id", business_id)
        .eq("id", integration_id)
        .eq("provider", "paypal")
        .eq("category", "payments")
        .maybe_single()
    )
    if not integration or integration["status"] != "connected":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "paypal_merchant_unavailable",
                "message": "The business PayPal integration is not ready.",
            },
        )
    encryption_key = get_supabase_settings().credentials_encryption_key
    if encryption_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "credential_encryption_unavailable",
                "message": "PayPal is not configured securely.",
            },
        )
    try:
        decrypted = Fernet(encryption_key.get_secret_value().encode()).decrypt(
            integration["credentials_ciphertext"].encode()
        )
        credentials = json.loads(decrypted)
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "paypal_merchant_unavailable",
                "message": "The business PayPal integration could not be read.",
            },
        ) from error
    if not isinstance(credentials, dict):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "paypal_merchant_unavailable",
                "message": "The business PayPal integration is incomplete.",
            },
        )
    seller_paypal_email = credentials.get("seller_paypal_email")
    if not isinstance(seller_paypal_email, str) or not seller_paypal_email:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "paypal_merchant_unavailable",
                "message": "The business PayPal account email is missing.",
            },
        )
    if credentials.get("mode") != "partner_after_payment":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "paypal_merchant_unavailable",
                "message": "This PayPal integration is not configured for seller after-payment onboarding.",
            },
        )
    try:
        platform_credentials = platform_paypal_credentials()
    except PayPalError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "paypal_partner_not_configured",
                "message": PAYPAL_PARTNER_CONFIGURATION_MESSAGE,
            },
        ) from error
    return {
        **platform_credentials,
        "seller_paypal_email": seller_paypal_email,
        "seller_onboarding_status": integration.get("sync_status", ""),
    }


def _request_json(
    method: str,
    url: str,
    *,
    client_id: str,
    client_secret: str,
    payload: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if request_id:
        headers["PayPal-Request-Id"] = request_id
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as http:
            response = http.request(
                method,
                url,
                auth=(client_id, client_secret)
                if url.endswith("/v1/oauth2/token")
                else None,
                headers=headers,
                data={"grant_type": "client_credentials"}
                if url.endswith("/v1/oauth2/token")
                else None,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError) as error:
        _log_paypal_request_failure(method, urlparse(url).path, error)
        raise PayPalError("PayPal could not complete the request.") from error
    if not isinstance(result, dict):
        raise PayPalError("PayPal returned an invalid response.")
    return result


def _access_token(credentials: dict[str, str]) -> str:
    result = _request_json(
        "POST",
        f"{_paypal_api_base()}/v1/oauth2/token",
        client_id=credentials["client_id"],
        client_secret=credentials["client_secret"],
    )
    token = result.get("access_token")
    if not isinstance(token, str) or not token:
        raise PayPalError("PayPal authentication did not return an access token.")
    return token


def _authenticated_request(
    method: str,
    path: str,
    credentials: dict[str, str],
    *,
    payload: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    token = _access_token(credentials)
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as http:
            response = http.request(
                method,
                f"{_paypal_api_base()}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    **(
                        {
                            "PayPal-Partner-Attribution-Id": credentials[
                                "partner_attribution_id"
                            ]
                        }
                        if credentials.get("partner_attribution_id")
                        else {}
                    ),
                    **({"PayPal-Request-Id": request_id} if request_id else {}),
                },
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError) as error:
        _log_paypal_request_failure(method, path, error)
        raise PayPalError("PayPal could not complete the request.") from error
    if not isinstance(result, dict):
        raise PayPalError("PayPal returned an invalid response.")
    return result


def minor_to_paypal_amount(amount_minor: int) -> str:
    return format(Decimal(amount_minor) / Decimal(100), ".2f")


def paypal_amount_to_minor(value: str) -> int:
    try:
        amount = Decimal(value)
    except Exception as error:
        raise PayPalError("PayPal returned an invalid amount.") from error
    if not amount.is_finite() or amount < 0 or amount * 100 != (amount * 100).to_integral_value():
        raise PayPalError("PayPal returned an invalid amount.")
    return int(amount * 100)


def create_paypal_order(
    credentials: dict[str, str],
    *,
    public_transaction_id: str,
    business_name: str,
    seller_paypal_email: str,
    amount_minor: int,
    currency: str,
    checkout_url: str,
) -> tuple[str, str]:
    parsed_checkout_url = urlparse(checkout_url)
    if parsed_checkout_url.scheme != "https" and parsed_checkout_url.hostname not in {
        "localhost",
        "127.0.0.1",
    }:
        raise PayPalError("The public checkout URL must use HTTPS.")
    request_id = f"AGC{public_transaction_id.removeprefix('txn_')[:32]}"
    result = _authenticated_request(
        "POST",
        "/v2/checkout/orders",
        credentials,
        request_id=request_id,
        payload={
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": public_transaction_id,
                    "custom_id": public_transaction_id,
                    "invoice_id": public_transaction_id,
                    "payee": {"email_address": seller_paypal_email},
                    "amount": {
                        "currency_code": currency,
                        "value": minor_to_paypal_amount(amount_minor),
                    },
                    "payment_instruction": {"disbursement_mode": "INSTANT"},
                }
            ],
            "application_context": {
                "brand_name": business_name[:127],
                "user_action": "PAY_NOW",
                "return_url": f"{checkout_url}?paypal_return=1",
                "cancel_url": f"{checkout_url}?paypal_cancelled=1",
            },
        },
    )
    order_id = result.get("id")
    links = result.get("links")
    if not isinstance(order_id, str) or not isinstance(links, list):
        raise PayPalError("PayPal did not create an order.")
    approval_url = next(
        (
            link.get("href")
            for link in links
            if isinstance(link, dict) and link.get("rel") in {"approve", "payer-action"}
        ),
        None,
    )
    parsed_approval = urlparse(approval_url) if isinstance(approval_url, str) else None
    if (
        not isinstance(approval_url, str)
        or parsed_approval is None
        or parsed_approval.scheme != "https"
        or not (
            parsed_approval.hostname == "paypal.com"
            or parsed_approval.hostname.endswith(".paypal.com")
        )
    ):
        raise PayPalError("PayPal did not return a valid approval URL.")
    return order_id, approval_url


def get_paypal_order(credentials: dict[str, str], order_id: str) -> dict[str, Any]:
    if not order_id or len(order_id) > 128:
        raise PayPalError("PayPal order reference is invalid.")
    return _authenticated_request(
        "GET",
        f"/v2/checkout/orders/{order_id}",
        credentials,
    )


def capture_paypal_order(
    credentials: dict[str, str],
    order_id: str,
    *,
    request_id: str,
) -> dict[str, Any]:
    if not order_id or len(order_id) > 128:
        raise PayPalError("PayPal order reference is invalid.")
    return _authenticated_request(
        "POST",
        f"/v2/checkout/orders/{order_id}/capture",
        credentials,
        request_id=request_id,
        payload={},
    )


def create_paypal_refund(
    credentials: dict[str, str],
    capture_id: str,
    *,
    amount_minor: int,
    currency: str,
    request_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    if not capture_id or len(capture_id) > 128:
        raise PayPalError("PayPal capture reference is invalid.")
    payload: dict[str, Any] = {
        "amount": {
            "currency_code": currency,
            "value": minor_to_paypal_amount(amount_minor),
        }
    }
    if reason:
        payload["note_to_payer"] = reason[:255]
    return _authenticated_request(
        "POST",
        f"/v2/payments/captures/{capture_id}/refund",
        credentials,
        request_id=request_id,
        payload=payload,
    )


def get_paypal_refund(credentials: dict[str, str], refund_id: str) -> dict[str, Any]:
    if not refund_id or len(refund_id) > 128:
        raise PayPalError("PayPal refund reference is invalid.")
    return _authenticated_request(
        "GET",
        f"/v2/payments/refunds/{refund_id}",
        credentials,
    )


def verified_refund_details(
    refund: dict[str, Any],
    *,
    expected_refund_id: str,
    expected_amount_minor: int,
    expected_currency: str,
) -> tuple[str, str, int, str, bool]:
    refund_id = refund.get("id")
    if not isinstance(refund_id, str) or refund_id != expected_refund_id:
        raise PayPalError("PayPal refund reference does not match the request.")
    amount = refund.get("amount")
    if not isinstance(amount, dict):
        raise PayPalError("PayPal refund amount is missing.")
    amount_minor = paypal_amount_to_minor(str(amount.get("value", "")))
    currency = str(amount.get("currency_code", ""))
    verified = (
        refund.get("status") == "COMPLETED"
        and amount_minor == expected_amount_minor
        and currency == expected_currency
    )
    return refund_id, str(refund.get("status", "")), amount_minor, currency, verified


def verified_capture_details(
    order: dict[str, Any],
    *,
    expected_transaction_id: str,
) -> tuple[str, str, int, str, bool]:
    if order.get("status") != "COMPLETED":
        return str(order.get("id", "")), "", 0, "", False
    purchase_units = order.get("purchase_units")
    if not isinstance(purchase_units, list) or not purchase_units:
        raise PayPalError("PayPal order has no purchase details.")
    unit = purchase_units[0]
    if not isinstance(unit, dict) or unit.get("custom_id") != expected_transaction_id:
        raise PayPalError("PayPal order does not match the Reactant transaction.")
    amount = unit.get("amount")
    payments = unit.get("payments")
    captures = payments.get("captures") if isinstance(payments, dict) else None
    if not isinstance(amount, dict) or not isinstance(captures, list) or not captures:
        raise PayPalError("PayPal order has no verified capture.")
    capture = next(
        (
            entry
            for entry in captures
            if isinstance(entry, dict) and entry.get("status") == "COMPLETED"
        ),
        None,
    )
    if not isinstance(capture, dict):
        pending = captures[0]
        pending_amount = pending.get("amount", {}) if isinstance(pending, dict) else {}
        return (
            str(order.get("id", "")),
            "",
            paypal_amount_to_minor(str(pending_amount.get("value", "0"))),
            str(pending_amount.get("currency_code", "")),
            False,
        )
    captured_amount = capture.get("amount")
    if not isinstance(captured_amount, dict):
        raise PayPalError("PayPal capture amount is missing.")
    return (
        str(order.get("id", "")),
        str(capture.get("id", "")),
        paypal_amount_to_minor(str(captured_amount.get("value", "0"))),
        str(captured_amount.get("currency_code", "")),
        True,
    )


def validate_paypal_credentials(credentials: dict[str, str]) -> None:
    _access_token(credentials)
