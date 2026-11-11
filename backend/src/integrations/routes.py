import json
import re
import secrets
from datetime import datetime, timezone
from typing import Annotated, Any, Callable, Literal, overload
from uuid import UUID
from urllib.parse import urlencode, urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from supabase import Client

from src.auth.dependencies import AuthenticatedUser, get_current_user
from src.agentcard.paypal import (
    PAYPAL_PARTNER_CONFIGURATION_MESSAGE,
    PayPalError,
    platform_paypal_credentials,
    validate_paypal_credentials,
)
from src.schemas.common import CollectionEnvelope, PaginationMeta, ResourceEnvelope
from src.schemas.integrations import (
    IntegrationCreate,
    IntegrationAuthorizationResponse,
    IntegrationResponse,
    PayPalWebhookConfigurationRequest,
    PayPalWebhookSetupResponse,
    TelegramSetupResponse,
)
from src.supabase.client import get_user_supabase_client, get_supabase_settings
from src.supabase.repository import execute, get_business_membership, require_role
from src.integrations.storefronts import (
    StorefrontError,
    sync_shopify,
    sync_woocommerce,
    test_shopify,
    test_woocommerce,
    test_woocommerce_mcp,
)


router = APIRouter()
User = Annotated[AuthenticatedUser, Depends(get_current_user)]
Database = Annotated[Client, Depends(get_user_supabase_client)]
VISIBLE_FIELDS = (
    "id,provider,category,status,connected_at,last_success_at,last_error,"
    "granted_scopes,sync_status,allowed_origin"
)
BASE_VISIBLE_FIELDS = (
    "id,provider,category,status,connected_at,last_success_at,last_error,"
    "granted_scopes,sync_status"
)
SHOPIFY_DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?!localhost$)(?!\d{1,3}(?:\.\d{1,3}){3}$)"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)
SHOPIFY_AUTH_TTL_SECONDS = 600


def _is_missing_allowed_origin(error: HTTPException) -> bool:
    cause = error.__cause__
    code = getattr(cause, "code", None)
    if code not in {"42703", "PGRST204", "PGRST205"}:
        return False
    details = f"{getattr(cause, 'message', '')} {getattr(cause, 'details', '')}".casefold()
    return "allowed_origin" in details


def _execute_integration_query(query_factory: Callable[[str, bool], Any]) -> Any:
    try:
        return execute(query_factory(VISIBLE_FIELDS, True))
    except HTTPException as error:
        if not _is_missing_allowed_origin(error):
            raise
        return execute(query_factory(BASE_VISIBLE_FIELDS, False))


def _shopify_domain(value: str) -> str:
    raw = value.strip().lower()
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    domain = (parsed.hostname or "").rstrip(".")
    if not SHOPIFY_DOMAIN_PATTERN.fullmatch(domain):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "shopify_domain_invalid", "message": "Enter your Shopify store domain, such as your-store.myshopify.com or shop.example.com."},
        )
    return domain


def _cipher() -> Fernet:
    key = get_supabase_settings().credentials_encryption_key
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "credential_encryption_unavailable",
                "message": "Integration setup is unavailable because the backend credential encryption key is not configured.",
            },
        )
    try:
        return Fernet(key.get_secret_value().encode())
    except (ValueError, TypeError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "credential_encryption_unavailable",
                "message": "Integration setup is unavailable because the backend credential encryption key is invalid.",
            },
        ) from error


def _validate_provider_credentials(body: IntegrationCreate) -> dict[str, str]:
    credentials = body.credentials.model_dump(mode="json", exclude_none=True)
    if body.provider == "woocommerce":
        required = {"store_url", "consumer_key", "consumer_secret", "webhook_secret"}
        if (
            not required.issubset(credentials)
            or not credentials["store_url"].startswith("https://")
            or (
                credentials.get("mcp_endpoint")
                and not credentials["mcp_endpoint"].startswith("https://")
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "validation_error", "message": "The request could not be completed."},
            )
    elif body.provider == "shopify":
        if not credentials.get("shop_domain") or not credentials.get("access_token"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "validation_error", "message": "Shopify domain and access token are required."},
            )
    elif body.provider == "telegram":
        if not credentials.get("bot_token") or not credentials.get("webhook_secret"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "validation_error", "message": "The request could not be completed."},
            )
    elif body.provider == "paypal":
        if credentials.get("consumer_key") or credentials.get("consumer_secret"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "paypal_business_credentials_not_allowed",
                    "message": "Do not submit PayPal REST app credentials for a business. Reactant uses its backend-only partner app credentials.",
                },
            )
        seller_email = credentials.get("seller_paypal_email")
        if not isinstance(seller_email, str) or not seller_email:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "paypal_seller_email_required",
                    "message": "Enter the business's PayPal account email.",
                },
            )
        try:
            platform_paypal_credentials()
        except PayPalError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "paypal_partner_not_configured",
                    "message": PAYPAL_PARTNER_CONFIGURATION_MESSAGE,
                },
            ) from error
        credentials = {
            "mode": "partner_after_payment",
            "seller_paypal_email": seller_email,
        }
    elif body.provider == "website_chat":
        origin = credentials.get("allowed_origin", "").strip().rstrip("/")
        try:
            parsed = urlparse(origin)
            port = parsed.port
            hostname = parsed.hostname
        except ValueError:
            parsed = urlparse("")
            port = -1
            hostname = None
        if (
            parsed.scheme not in {"https", "http"}
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or port == -1
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or (parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"})
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "website_origin_invalid", "message": "Enter a secure website origin, such as https://shop.example.com."},
            )
        hostname = hostname.lower()
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        default_port = 443 if parsed.scheme == "https" else 80
        netloc = hostname if port is None or port == default_port else f"{hostname}:{port}"
        credentials["allowed_origin"] = f"{parsed.scheme}://{netloc}"
    else:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={"code": "provider_not_supported", "message": "This provider is not available yet."},
        )
    return credentials


def _decrypt_credentials(ciphertext: str) -> dict[str, str]:
    key = get_supabase_settings().credentials_encryption_key
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "credential_encryption_unavailable",
                "message": "Integration setup is unavailable because the backend credential encryption key is not configured.",
            },
        )
    try:
        credentials = json.loads(
            Fernet(key.get_secret_value().encode()).decrypt(ciphertext.encode())
        )
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "credential_encryption_unavailable", "message": "Integration credentials could not be read."},
        ) from error
    if not isinstance(credentials, dict):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "credential_encryption_unavailable", "message": "Integration credentials could not be read."},
        )
    return credentials


def _telegram_setup(request: Request, integration_id: UUID) -> tuple[str, str]:
    settings = get_supabase_settings()
    base_url = (settings.public_api_base_url or str(request.base_url)).rstrip("/")
    if not base_url.startswith("https://"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "public_url_unavailable", "message": "Set PUBLIC_API_BASE_URL to an HTTPS backend URL before connecting Telegram."},
        )
    return f"{base_url}/webhooks/telegram/{integration_id}", base_url


def _paypal_webhook_url(request: Request, integration_id: UUID) -> str:
    settings = get_supabase_settings()
    base_url = (settings.public_api_base_url or str(request.base_url)).rstrip("/")
    if not base_url.startswith("https://"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "public_url_unavailable", "message": "Set PUBLIC_API_BASE_URL to an HTTPS backend URL before configuring PayPal webhooks."},
        )
    return f"{base_url}/webhooks/paypal/{integration_id}"


@overload
def _telegram_api(
    bot_token: str,
    method: Literal["getMe"],
    payload: dict[str, object],
) -> dict[str, object]: ...


@overload
def _telegram_api(
    bot_token: str,
    method: Literal["setWebhook"],
    payload: dict[str, object],
) -> bool: ...


def _telegram_api(
    bot_token: str,
    method: str,
    payload: dict[str, object],
) -> dict[str, object] | bool:
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{bot_token}/{method}",
            json=payload,
            timeout=15,
        )
    except httpx.TimeoutException as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "telegram_timeout", "message": "Telegram did not respond in time. Try the connection test again."},
        ) from error
    except httpx.RequestError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "telegram_network_error", "message": "The backend could not reach Telegram. Check the backend outbound network and try again."},
        ) from error

    try:
        result = response.json()
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "telegram_invalid_response", "message": "Telegram returned an invalid response. Try again later."},
        ) from error

    if response.status_code in {401, 403}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "telegram_credentials_invalid", "message": "Telegram rejected the bot token. Copy the token again from BotFather."},
        )
    if response.status_code >= 500 or response.status_code == 429:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "telegram_unavailable", "message": "Telegram is temporarily unavailable. Try the connection test again."},
        )
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "telegram_request_rejected", "message": f"Telegram rejected the {method} request. Check the bot token and webhook settings."},
        )
    data = result.get("result")
    if method == "getMe" and isinstance(data, dict):
        return data
    if method == "setWebhook" and data is True:
        return True
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={"code": "telegram_invalid_response", "message": "Telegram returned an invalid response."},
    )


@router.get(
    "/businesses/{business_id}/integrations",
    response_model=CollectionEnvelope[IntegrationResponse],
)
def list_integrations(
    business_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> CollectionEnvelope[IntegrationResponse]:
    get_business_membership(client, business_id, user.id)
    rows = _execute_integration_query(
        lambda fields, _include_origin: client.table("integrations")
        .select(fields)
        .eq("business_id", str(business_id))
        .order("created_at", desc=True)
    )
    return CollectionEnvelope(
        data=[IntegrationResponse(**row) for row in rows],
        meta=PaginationMeta(next_cursor=None, has_more=False),
        request_id=request.state.request_id,
    )


@router.post(
    "/businesses/{business_id}/integrations",
    status_code=status.HTTP_201_CREATED,
    response_model=ResourceEnvelope[IntegrationResponse],
)
def create_integration(
    business_id: UUID,
    body: IntegrationCreate,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[IntegrationResponse]:
    local_website_chat = (
        body.provider == "website_chat"
        and request.url.scheme == "http"
        and request.client is not None
        and request.client.host in {"localhost", "127.0.0.1", "::1"}
    )
    if request.url.scheme != "https" and not local_website_chat:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "tls_required", "message": "Integration credentials must be submitted over HTTPS."},
        )
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin"})
    if body.provider == "paypal":
        existing = execute(
            client.table("integrations")
            .select("id")
            .eq("business_id", str(business_id))
            .eq("provider", "paypal")
            .neq("status", "disconnected")
            .limit(1)
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "paypal_integration_already_exists",
                    "message": "Disconnect the existing PayPal integration before connecting a seller account.",
                },
            )
    credentials = _validate_provider_credentials(body)
    ciphertext = _cipher().encrypt(
        json.dumps(credentials, separators=(",", ":"), sort_keys=True).encode()
    ).decode()
    def create_query(fields: str, include_origin: bool) -> Any:
        if body.provider == "website_chat" and not include_origin:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "database_schema_outdated",
                    "message": "Website chat requires the latest Supabase migrations. Apply the integration allowed-origin migration and retry.",
                },
            )
        values = {
            "business_id": str(business_id),
            "provider": body.provider,
            "category": {
                "woocommerce": "commerce",
                "telegram": "messaging",
                "paypal": "payments",
                "website_chat": "messaging",
            }[body.provider],
            "status": "connected" if body.provider == "website_chat" else "pending",
            "credentials_ciphertext": ciphertext,
            "connected_at": datetime.now(timezone.utc).isoformat() if body.provider == "website_chat" else None,
            "last_success_at": datetime.now(timezone.utc).isoformat() if body.provider == "website_chat" else None,
            "sync_status": "ready" if body.provider == "website_chat" else "idle",
            "last_error": None,
        }
        if include_origin:
            values["allowed_origin"] = credentials.get("allowed_origin")
        if credentials.get("webhook_id"):
            values["webhook_id"] = credentials["webhook_id"]
        return client.table("integrations").insert(values).select(fields).single()

    integration = _execute_integration_query(create_query)
    return ResourceEnvelope(
        data=IntegrationResponse(**integration),
        request_id=request.state.request_id,
    )


@router.get(
    "/businesses/{business_id}/integrations/{integration_id}/paypal-webhook",
    response_model=ResourceEnvelope[PayPalWebhookSetupResponse],
)
def get_paypal_webhook_setup(
    business_id: UUID,
    integration_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[PayPalWebhookSetupResponse]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin"})
    integration = execute(
        client.table("integrations")
        .select("id,provider,credentials_ciphertext")
        .eq("business_id", str(business_id))
        .eq("id", str(integration_id))
        .maybe_single()
    )
    if not integration or integration["provider"] != "paypal":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The PayPal integration was not found."},
        )
    credentials = _decrypt_credentials(integration["credentials_ciphertext"])
    return ResourceEnvelope(
        data=PayPalWebhookSetupResponse(
            webhook_url=_paypal_webhook_url(request, integration_id),
            configured=bool(credentials.get("webhook_id")),
        ),
        request_id=request.state.request_id,
    )


@router.put(
    "/businesses/{business_id}/integrations/{integration_id}/paypal-webhook",
    response_model=ResourceEnvelope[PayPalWebhookSetupResponse],
)
def configure_paypal_webhook(
    business_id: UUID,
    integration_id: UUID,
    body: PayPalWebhookConfigurationRequest,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[PayPalWebhookSetupResponse]:
    webhook_id = body.webhook_id.strip()
    if not webhook_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "validation_error", "message": "Enter the PayPal webhook ID."},
        )
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin"})
    integration = execute(
        client.table("integrations")
        .select("id,provider,credentials_ciphertext")
        .eq("business_id", str(business_id))
        .eq("id", str(integration_id))
        .maybe_single()
    )
    if not integration or integration["provider"] != "paypal":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The PayPal integration was not found."},
        )
    credentials = _decrypt_credentials(integration["credentials_ciphertext"])
    credentials["webhook_id"] = webhook_id
    encryption_key = get_supabase_settings().credentials_encryption_key
    if encryption_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "credential_encryption_unavailable", "message": "Integration credentials could not be stored securely."},
        )
    ciphertext = Fernet(encryption_key.get_secret_value().encode()).encrypt(
        json.dumps(credentials, separators=(",", ":"), sort_keys=True).encode()
    ).decode()
    execute(
        client.table("integrations")
        .update({
            "credentials_ciphertext": ciphertext,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("business_id", str(business_id))
        .eq("id", str(integration_id))
    )
    return ResourceEnvelope(
        data=PayPalWebhookSetupResponse(
            webhook_url=_paypal_webhook_url(request, integration_id),
            configured=True,
        ),
        request_id=request.state.request_id,
    )


@router.get(
    "/businesses/{business_id}/integrations/{integration_id}",
    response_model=ResourceEnvelope[IntegrationResponse],
)
def get_integration(
    business_id: UUID,
    integration_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[IntegrationResponse]:
    get_business_membership(client, business_id, user.id)
    integration = _execute_integration_query(
        lambda fields, _include_origin: client.table("integrations")
        .select(fields)
        .eq("business_id", str(business_id))
        .eq("id", str(integration_id))
        .maybe_single()
    )
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested resource was not found."},
        )
    return ResourceEnvelope(
        data=IntegrationResponse(**integration),
        request_id=request.state.request_id,
    )


@router.get(
    "/businesses/{business_id}/integrations/{integration_id}/website-chat-install",
    response_model=ResourceEnvelope[dict[str, str]],
)
def get_website_chat_install(
    business_id: UUID,
    integration_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[dict[str, str]]:
    get_business_membership(client, business_id, user.id)
    integration = execute(
        client.table("integrations")
        .select("id,provider,status")
        .eq("business_id", str(business_id))
        .eq("id", str(integration_id))
        .maybe_single()
    )
    if not integration or integration["provider"] != "website_chat" or integration["status"] != "connected":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The website chat integration was not found."},
        )
    settings = get_supabase_settings()
    frontend = settings.public_frontend_url.rstrip("/")
    api_base = (settings.public_api_base_url or str(request.base_url)).rstrip("/")
    script = (
        f'<script async src="{frontend}/reactant-chat.js" '
        f'data-business-id="{business_id}" '
        f'data-api-url="{api_base}/api/v1"></script>'
    )
    return ResourceEnvelope(
        data={"script": script, "business_id": str(business_id)},
        request_id=request.state.request_id,
    )


@router.post(
    "/businesses/{business_id}/integrations/{provider}/authorization",
    response_model=ResourceEnvelope[IntegrationAuthorizationResponse],
)
def start_authorization(
    business_id: UUID,
    provider: str,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[IntegrationAuthorizationResponse]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin"})
    if provider != "shopify":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={"code": "provider_not_supported", "message": "Authorization is not available for this provider yet."},
        )
    settings = get_supabase_settings()
    if not settings.shopify_client_id or not settings.shopify_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "oauth_unavailable", "message": "Shopify authorization is not configured yet."},
        )
    shop = _shopify_domain(str(request.query_params.get("shop", "")))
    callback_base = (settings.public_api_base_url or str(request.base_url)).rstrip("/")
    if not callback_base.startswith("https://") and settings.public_frontend_url.startswith("https://"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "public_url_unavailable", "message": "Set PUBLIC_API_BASE_URL to an HTTPS backend URL before connecting Shopify."},
        )
    state_payload = {
        "business_id": str(business_id),
        "user_id": str(user.id),
        "shop": shop,
        "nonce": secrets.token_urlsafe(24),
        "issued_at": int(datetime.now(timezone.utc).timestamp()),
    }
    state_key = get_supabase_settings().credentials_encryption_key
    if state_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "credential_encryption_unavailable", "message": "Shopify authorization is unavailable until credential encryption is configured."},
        )
    state = Fernet(state_key.get_secret_value().encode()).encrypt(
        json.dumps(state_payload, separators=(",", ":"), sort_keys=True).encode()
    ).decode()
    redirect_uri = f"{callback_base}/api/v1/integrations/callback/shopify"
    authorization_url = f"https://{shop}/admin/oauth/authorize?" + urlencode(
        {
            "client_id": settings.shopify_client_id,
            "scope": settings.shopify_scopes,
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    expires_at = datetime.fromtimestamp(
        state_payload["issued_at"] + SHOPIFY_AUTH_TTL_SECONDS, timezone.utc
    )
    return ResourceEnvelope(
        data=IntegrationAuthorizationResponse(
            authorization_url=authorization_url,
            expires_at=expires_at,
        ),
        request_id=request.state.request_id,
    )


@router.post(
    "/businesses/{business_id}/integrations/{integration_id}/test",
    response_model=ResourceEnvelope[IntegrationResponse],
)
def test_integration(
    business_id: UUID,
    integration_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[IntegrationResponse]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin"})
    integration = execute(
        client.table("integrations")
        .select("id,provider,credentials_ciphertext,sync_status")
        .eq("business_id", str(business_id))
        .eq("id", str(integration_id))
        .maybe_single()
    )
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested resource was not found."},
        )
    if integration["provider"] not in {"telegram", "woocommerce", "shopify", "paypal", "website_chat"}:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={"code": "provider_adapter_unavailable", "message": "Testing this provider is not configured."},
        )
    credentials = _decrypt_credentials(integration["credentials_ciphertext"])
    if integration["provider"] == "woocommerce":
        try:
            if credentials.get("mcp_endpoint"):
                test_woocommerce_mcp(
                    str(credentials["store_url"]),
                    credentials["mcp_endpoint"],
                    credentials["consumer_key"],
                    credentials["consumer_secret"],
                )
            else:
                test_woocommerce(
                    str(credentials["store_url"]),
                    credentials["consumer_key"],
                    credentials["consumer_secret"],
                )
        except (KeyError, StorefrontError) as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "woocommerce_unavailable", "message": "WooCommerce rejected the connection."},
            ) from error
    elif integration["provider"] == "shopify":
        try:
            test_shopify(credentials["shop_domain"], credentials["access_token"])
        except (KeyError, StorefrontError) as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "shopify_unavailable", "message": "Shopify rejected the connection."},
            ) from error
    elif integration["provider"] == "paypal":
        if integration.get("sync_status") == "seller_reauthorization_required":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "paypal_seller_reauthorization_required",
                    "message": "Disconnect this PayPal connection and reconnect the seller account.",
                },
            )
        if credentials.get("mode") != "partner_after_payment":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "paypal_after_payment_mode_required",
                    "message": "Disconnect this legacy PayPal integration and connect the business PayPal account instead.",
                },
            )
        try:
            paypal_app_credentials = platform_paypal_credentials()
        except PayPalError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "paypal_partner_not_configured",
                    "message": PAYPAL_PARTNER_CONFIGURATION_MESSAGE,
                },
            ) from error
        try:
            validate_paypal_credentials(paypal_app_credentials)
        except PayPalError as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "paypal_credentials_invalid",
                    "message": "PayPal did not accept Reactant's partner app credentials.",
                },
            ) from error
    elif integration["provider"] == "website_chat":
        pass
    elif integration["provider"] == "telegram":
        return _test_telegram_integration(
            business_id, integration_id, request, integration, credentials, client
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={"code": "provider_not_supported", "message": "This provider is not available yet."},
        )
    now = datetime.now(timezone.utc).isoformat()
    sync_status = (
        (
            "seller_connected"
            if integration.get("sync_status") == "seller_connected"
            else "seller_onboarding_pending"
        )
        if integration["provider"] == "paypal"
        else "ready"
    )
    updated = _execute_integration_query(
        lambda fields, _include_origin: client.table("integrations")
        .update(
            {
                "status": "connected",
                "connected_at": now,
                "last_success_at": now,
                "last_error": None,
                "sync_status": sync_status,
                "updated_at": now,
            }
        )
        .eq("business_id", str(business_id))
        .eq("id", str(integration_id))
        .select(fields)
        .single()
    )
    return ResourceEnvelope(data=IntegrationResponse(**updated), request_id=request.state.request_id)


def _test_telegram_integration(
    business_id: UUID,
    integration_id: UUID,
    request: Request,
    integration: dict[str, Any],
    credentials: dict[str, str],
    client: Client,
) -> ResourceEnvelope[IntegrationResponse]:
    bot_token = credentials.get("bot_token")
    webhook_secret = credentials.get("webhook_secret")
    if not isinstance(bot_token, str) or not isinstance(webhook_secret, str):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "telegram_credentials_invalid", "message": "Telegram credentials are incomplete."},
        )
    webhook_url, _ = _telegram_setup(request, integration_id)
    bot = _telegram_api(bot_token, "getMe", {})
    _telegram_api(
        bot_token,
        "setWebhook",
        {"url": webhook_url, "secret_token": webhook_secret, "drop_pending_updates": "false"},
    )
    now = datetime.now(timezone.utc).isoformat()
    updated = _execute_integration_query(
        lambda fields, _include_origin: client.table("integrations")
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
        .eq("business_id", str(business_id))
        .eq("id", str(integration_id))
        .select(fields)
        .single()
    )
    return ResourceEnvelope(data=IntegrationResponse(**updated), request_id=request.state.request_id)


@router.get(
    "/businesses/{business_id}/integrations/{integration_id}/telegram-setup",
    response_model=ResourceEnvelope[TelegramSetupResponse],
)
def telegram_setup(
    business_id: UUID,
    integration_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[TelegramSetupResponse]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin"})
    integration = execute(
        client.table("integrations")
        .select("id,provider,credentials_ciphertext,status")
        .eq("business_id", str(business_id))
        .eq("id", str(integration_id))
        .maybe_single()
    )
    if not integration or integration["provider"] != "telegram":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The Telegram integration was not found."},
        )
    if integration["status"] != "connected":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "integration_not_connected", "message": "Test the Telegram connection before viewing setup details."},
        )
    credentials = _decrypt_credentials(integration["credentials_ciphertext"])
    bot = _telegram_api(credentials["bot_token"], "getMe", {})
    webhook_url, _ = _telegram_setup(request, integration_id)
    return ResourceEnvelope(
        data=TelegramSetupResponse(
            webhook_url=webhook_url,
            bot_username=bot.get("username", ""),
            bot_name=bot.get("first_name", ""),
        ),
        request_id=request.state.request_id,
    )


@router.post(
    "/businesses/{business_id}/integrations/{integration_id}/sync",
    response_model=ResourceEnvelope[dict[str, int]],
)
def sync_integration(
    business_id: UUID,
    integration_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[dict[str, int]]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin"})
    integration = execute(
        client.table("integrations")
        .select("id,provider,credentials_ciphertext,status")
        .eq("business_id", str(business_id))
        .eq("id", str(integration_id))
        .maybe_single()
    )
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested resource was not found."},
        )
    if integration["provider"] not in {"woocommerce", "shopify"}:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={"code": "sync_worker_unavailable", "message": "Synchronization is not available for this provider."},
        )
    credentials = _decrypt_credentials(integration["credentials_ciphertext"])
    try:
        if integration["provider"] == "woocommerce":
            products = sync_woocommerce(
                str(credentials["store_url"]),
                credentials["consumer_key"],
                credentials["consumer_secret"],
            )
        else:
            products = sync_shopify(credentials["shop_domain"], credentials["access_token"])
    except (KeyError, StorefrontError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "storefront_sync_failed", "message": "The storefront could not be synchronized."},
        ) from error
    for product in products:
        product["business_id"] = str(business_id)
    if products:
        execute(
            client.table("products").upsert(
                products,
                on_conflict="business_id,source,provider_product_id",
            )
        )
    now = datetime.now(timezone.utc).isoformat()
    execute(
        client.table("integrations")
        .update(
            {
                "status": "connected",
                "last_success_at": now,
                "last_error": None,
                "sync_status": "ready",
                "updated_at": now,
            }
        )
        .eq("business_id", str(business_id))
        .eq("id", str(integration_id))
    )
    return ResourceEnvelope(
        data={"imported": len(products)},
        request_id=request.state.request_id,
    )


@router.delete(
    "/businesses/{business_id}/integrations/{integration_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def disconnect_integration(
    business_id: UUID,
    integration_id: UUID,
    user: User,
    client: Database,
) -> None:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin"})
    integration = execute(
        client.table("integrations")
        .update(
            {
                "status": "disconnected",
                "credentials_ciphertext": None,
                "allowed_origin": None,
                "last_error": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("business_id", str(business_id))
        .eq("id", str(integration_id))
        .select("id")
        .maybe_single()
    )
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested resource was not found."},
        )


@router.get("/integrations/callback/{provider}")
def integration_callback(provider: str, request: Request) -> RedirectResponse:
    settings = get_supabase_settings()
    frontend = settings.public_frontend_url.rstrip("/")
    if provider != "shopify":
        return RedirectResponse(f"{frontend}/?integration=error&provider={provider}&reason=unsupported")
    state_key = settings.credentials_encryption_key
    state = request.query_params.get("state")
    if state_key is None or not state:
        return RedirectResponse(f"{frontend}/?integration=error&provider=shopify&reason=invalid_state")
    try:
        payload = json.loads(Fernet(state_key.get_secret_value().encode()).decrypt(state.encode()))
        issued_at = int(payload["issued_at"])
        business_id = UUID(payload["business_id"])
        shop = _shopify_domain(str(payload["shop"]))
    except (InvalidToken, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return RedirectResponse(f"{frontend}/?integration=error&provider=shopify&reason=invalid_state")
    if int(datetime.now(timezone.utc).timestamp()) - issued_at > SHOPIFY_AUTH_TTL_SECONDS:
        return RedirectResponse(f"{frontend}/?integration=error&provider=shopify&reason=expired")
    code = request.query_params.get("code")
    if not code or not settings.shopify_client_id or not settings.shopify_client_secret:
        return RedirectResponse(f"{frontend}/?integration=error&provider=shopify&reason=authorization_failed")
    try:
        response = httpx.post(
            f"https://{shop}/admin/oauth/access_token",
            json={
                "client_id": settings.shopify_client_id,
                "client_secret": settings.shopify_client_secret.get_secret_value(),
                "code": code,
            },
            timeout=20,
        )
        response.raise_for_status()
        token_payload = response.json()
        access_token = token_payload["access_token"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return RedirectResponse(f"{frontend}/?integration=error&provider=shopify&reason=authorization_failed")
    if not isinstance(access_token, str) or not access_token:
        return RedirectResponse(f"{frontend}/?integration=error&provider=shopify&reason=authorization_failed")
    try:
        service_client = get_service_supabase_client()
        credentials = {"shop_domain": shop, "access_token": access_token}
        encryption_key = get_supabase_settings().credentials_encryption_key
        if encryption_key is None:
            raise RuntimeError("credential encryption unavailable")
        ciphertext = Fernet(encryption_key.get_secret_value().encode()).encrypt(
            json.dumps(credentials, separators=(",", ":"), sort_keys=True).encode()
        ).decode()
        existing = execute(
            service_client.table("integrations")
            .select("id")
            .eq("business_id", str(business_id))
            .eq("provider", "shopify")
            .maybe_single()
        )
        integration_query = service_client.table("integrations")
        if existing:
            integration = _execute_integration_query(
                lambda fields, _include_origin: integration_query.update({
                    "status": "pending",
                    "credentials_ciphertext": ciphertext,
                    "last_error": None,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", existing["id"]).select(fields).single()
            )
        else:
            integration = _execute_integration_query(
                lambda fields, _include_origin: integration_query.insert({
                    "business_id": str(business_id),
                    "provider": "shopify",
                    "category": "commerce",
                    "status": "pending",
                    "credentials_ciphertext": ciphertext,
                    "last_error": None,
                }).select(fields).single()
            )
        test_shopify(shop, access_token)
        now = datetime.now(timezone.utc).isoformat()
        execute(
            service_client.table("integrations").update({
                "status": "connected",
                "connected_at": now,
                "last_success_at": now,
                "sync_status": "ready",
                "updated_at": now,
            }).eq("id", integration["id"])
        )
    except (HTTPException, RuntimeError, StorefrontError, httpx.HTTPError, ValueError, KeyError, TypeError):
        return RedirectResponse(f"{frontend}/?integration=error&provider=shopify&reason=connection_failed")
    return RedirectResponse(f"{frontend}/?integration=connected&provider=shopify")
