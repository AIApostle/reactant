import json
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request, status
from supabase import Client

from src.auth.dependencies import AuthenticatedUser, get_current_user
from src.schemas.common import CollectionEnvelope, PaginationMeta, ResourceEnvelope
from src.schemas.integrations import IntegrationCreate, IntegrationResponse
from src.supabase.client import get_user_supabase_client, get_supabase_settings
from src.supabase.repository import execute, get_business_membership, require_role


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
    openapi_extra={"x-implementation-status": "planned"},
)
def test_integration(
    business_id: UUID,
    integration_id: UUID,
    user: User,
    client: Database,
) -> None:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin"})
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "provider_adapter_unavailable", "message": "Provider connectivity testing is not configured."},
    )


@router.post(
    "/businesses/{business_id}/integrations/{integration_id}/sync",
    openapi_extra={"x-implementation-status": "planned"},
)
def sync_integration(
    business_id: UUID,
    integration_id: UUID,
    user: User,
    client: Database,
) -> None:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin"})
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "sync_worker_unavailable", "message": "Integration synchronization is not available right now."},
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
