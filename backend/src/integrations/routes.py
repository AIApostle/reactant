import json
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request, status
from supabase import Client

from src.auth.dependencies import AuthenticatedUser, get_current_user
from src.schemas.common import CollectionEnvelope, PaginationMeta, ResourceEnvelope
from src.schemas.integrations import (
    IntegrationCreate,
    IntegrationResponse,
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
)


router = APIRouter()
User = Annotated[AuthenticatedUser, Depends(get_current_user)]
Database = Annotated[Client, Depends(get_user_supabase_client)]
VISIBLE_FIELDS = (
    "id,provider,category,status,connected_at,last_success_at,last_error,"
    "granted_scopes,sync_status"
)


def _cipher() -> Fernet:
    key = get_supabase_settings().credentials_encryption_key
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "credential_encryption_unavailable", "message": "Integration setup is not available right now."},
        )
    try:
        return Fernet(key.get_secret_value().encode())
    except (ValueError, TypeError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "credential_encryption_unavailable", "message": "Integration setup is not available right now."},
        ) from error


def _validate_provider_credentials(body: IntegrationCreate) -> dict[str, str]:
    credentials = body.credentials.model_dump(mode="json", exclude_none=True)
    if body.provider == "woocommerce":
        required = {"store_url", "consumer_key", "consumer_secret", "webhook_secret"}
        if not required.issubset(credentials) or not credentials["store_url"].startswith("https://"):
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
        required = {"consumer_key", "consumer_secret", "webhook_id"}
        if not required.issubset(credentials):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "validation_error", "message": "The request could not be completed."},
            )
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
            detail={"code": "credential_encryption_unavailable", "message": "Integration setup is not available right now."},
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


def _telegram_api(
    bot_token: str,
    method: str,
    payload: dict[str, object],
) -> dict[str, object]:
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{bot_token}/{method}",
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "telegram_unavailable", "message": "Telegram could not be reached right now."},
        ) from error
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "telegram_credentials_invalid", "message": "Telegram rejected this bot token."},
        )
    data = result.get("result")
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "telegram_invalid_response", "message": "Telegram returned an invalid response."},
        )
    return data


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
    rows = execute(
        client.table("integrations")
        .select(VISIBLE_FIELDS)
        .eq("business_id", str(business_id))
        .order("created_at", desc=True)
    )
    return CollectionEnvelope(
        data=rows,
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
    if request.url.scheme != "https":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "tls_required", "message": "Integration credentials must be submitted over HTTPS."},
        )
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin"})
    credentials = _validate_provider_credentials(body)
    ciphertext = _cipher().encrypt(
        json.dumps(credentials, separators=(",", ":"), sort_keys=True).encode()
    ).decode()
    integration = execute(
        client.table("integrations")
        .insert(
            {
                "business_id": str(business_id),
                "provider": body.provider,
                "category": {
                    "woocommerce": "commerce",
                    "telegram": "messaging",
                    "paypal": "payments",
                }[body.provider],
                "status": "pending",
                "credentials_ciphertext": ciphertext,
                "last_error": None,
            }
        )
        .select(VISIBLE_FIELDS)
        .single()
    )
    return ResourceEnvelope(
        data=IntegrationResponse(**integration),
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
    integration = execute(
        client.table("integrations")
        .select(VISIBLE_FIELDS)
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


@router.post(
    "/businesses/{business_id}/integrations/{provider}/authorization",
    openapi_extra={"x-implementation-status": "planned"},
)
def start_authorization(
    business_id: UUID,
    provider: str,
    user: User,
    client: Database,
) -> None:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin"})
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "oauth_unavailable", "message": "Provider authorization is not configured."},
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
        .select("id,provider,credentials_ciphertext")
        .eq("business_id", str(business_id))
        .eq("id", str(integration_id))
        .maybe_single()
    )
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested resource was not found."},
        )
    if integration["provider"] not in {"telegram", "woocommerce", "shopify"}:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={"code": "provider_adapter_unavailable", "message": "Testing this provider is not configured."},
        )
    credentials = _decrypt_credentials(integration["credentials_ciphertext"])
    if integration["provider"] == "woocommerce":
        try:
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
    else:
        return _test_telegram_integration(
            business_id, integration_id, request, integration, credentials, client
        )
    now = datetime.now(timezone.utc).isoformat()
    updated = execute(
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
        .eq("business_id", str(business_id))
        .eq("id", str(integration_id))
        .select(VISIBLE_FIELDS)
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
    updated = execute(
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
        .eq("business_id", str(business_id))
        .eq("id", str(integration_id))
        .select(VISIBLE_FIELDS)
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


@router.get(
    "/integrations/callback/{provider}",
    openapi_extra={"x-implementation-status": "planned"},
)
def integration_callback(provider: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "oauth_unavailable", "message": "Provider authorization is not configured."},
    )
