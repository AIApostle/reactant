from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from supabase import Client

from src.auth.dependencies import AuthenticatedUser, get_current_user
from src.schemas.common import ResourceEnvelope
from src.schemas.settings import (
    BusinessSettingsResponse,
    BusinessSettingsUpdate,
    NotificationPreferences,
)
from src.schemas.workspace import BusinessResponse
from src.supabase.client import get_user_supabase_client
from src.supabase.repository import (
    execute,
    get_business_membership,
    require_matching_etag,
    require_role,
)


router = APIRouter()
User = Annotated[AuthenticatedUser, Depends(get_current_user)]
Database = Annotated[Client, Depends(get_user_supabase_client)]


def _business_response(row: dict[str, Any], role: str) -> BusinessResponse:
    response_data = {key: value for key, value in row.items() if key != "version"}
    return BusinessResponse(**response_data, role=role)


@router.get(
    "/businesses/{business_id}/settings",
    response_model=ResourceEnvelope[BusinessSettingsResponse],
)
def get_settings(
    business_id: UUID,
    request: Request,
    response: Response,
    user: User,
    client: Database,
) -> ResourceEnvelope[BusinessSettingsResponse]:
    membership = get_business_membership(client, business_id, user.id)
    business = execute(
        client.table("businesses")
        .select("*")
        .eq("id", str(business_id))
        .single()
    )
    response.headers["ETag"] = f'"{business["version"]}"'
    settings = execute(
        client.table("business_settings")
        .select("notifications,privacy")
        .eq("business_id", str(business_id))
        .maybe_single()
    )
    result = BusinessSettingsResponse(
        business=_business_response(business, membership["role"]),
        notifications=NotificationPreferences(
            **(settings or {}).get("notifications", {})
        ),
        privacy=(settings or {}).get("privacy", {}),
    )
    return ResourceEnvelope(data=result, request_id=request.state.request_id)


@router.patch(
    "/businesses/{business_id}/settings",
    response_model=ResourceEnvelope[BusinessSettingsResponse],
)
def update_settings(
    business_id: UUID,
    body: BusinessSettingsUpdate,
    request: Request,
    response: Response,
    user: User,
    client: Database,
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> ResourceEnvelope[BusinessSettingsResponse]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin"})
    business = execute(
        client.table("businesses")
        .select("*")
        .eq("id", str(business_id))
        .single()
    )
    require_matching_etag(if_match, business["version"])
    data = body.model_dump(mode="json", exclude_unset=True)
    notifications = data.pop("notifications", None) or {}
    notification_changes = {
        key: value for key, value in notifications.items() if value is not None
    }
    result = execute(
        client.rpc(
            "patch_business_settings",
            {
                "target_business_id": str(business_id),
                "expected_version": business["version"],
                "business_changes": data,
                "notification_changes": notification_changes,
            },
        )
    )
    if isinstance(result, list):
        result = result[0] if result else None
    if not isinstance(result, dict) or not isinstance(result.get("business"), dict):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "database_unavailable", "message": "The request could not be completed right now."},
        )

    updated_business = result["business"]
    updated_settings = result.get("settings") or {}
    response.headers["ETag"] = f'"{updated_business["version"]}"'
    return ResourceEnvelope(
        data=BusinessSettingsResponse(
            business=_business_response(updated_business, membership["role"]),
            notifications=NotificationPreferences(
                **(updated_settings.get("notifications") or {})
            ),
            privacy=updated_settings.get("privacy") or {},
        ),
        request_id=request.state.request_id,
    )
