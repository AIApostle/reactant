import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from supabase import Client

from src.auth.dependencies import AuthenticatedUser, get_current_user
from src.schemas.common import CollectionEnvelope, PaginationMeta, ResourceEnvelope
from src.schemas.workspace import (
    BusinessCreate,
    BusinessMemberResponse,
    BusinessResponse,
    BusinessUpdate,
    InvitationAccept,
    InvitationCreate,
    InvitationResponse,
    MemberRoleUpdate,
)
from src.supabase.client import get_user_supabase_client
from src.supabase.invitations import deliver_invitation
from src.supabase.repository import (
    execute,
    get_business_membership,
    require_matching_etag,
    require_role,
)


router = APIRouter()
User = Annotated[AuthenticatedUser, Depends(get_current_user)]
Database = Annotated[Client, Depends(get_user_supabase_client)]


def _business_response(row: dict[str, Any], role: str | None = None) -> BusinessResponse:
    fields = BusinessResponse.model_fields.keys() - {"role"}
    return BusinessResponse(**{key: row[key] for key in fields if key in row}, role=role)


@router.get("/businesses", response_model=CollectionEnvelope[BusinessResponse])
def list_businesses(
    request: Request,
    user: User,
    client: Database,
) -> CollectionEnvelope[BusinessResponse]:
    memberships = execute(
        client.table("business_members")
        .select("role,businesses(*)")
        .eq("user_id", str(user.id))
        .order("created_at", desc=True)
    )
    businesses = [
        _business_response(item["businesses"], item["role"])
        for item in memberships
        if item.get("businesses")
    ]
    return CollectionEnvelope(
        data=businesses,
        meta=PaginationMeta(next_cursor=None, has_more=False),
        request_id=request.state.request_id,
    )


@router.post(
    "/businesses",
    status_code=status.HTTP_201_CREATED,
    response_model=ResourceEnvelope[BusinessResponse],
)
def create_business(
    body: BusinessCreate,
    request: Request,
    response: Response,
    user: User,
    client: Database,
) -> ResourceEnvelope[BusinessResponse]:
    row = execute(
        client.rpc(
            "create_business_with_owner",
            {
                "business_name": body.name,
                "business_country": body.country,
                "business_currency": body.currency,
                "business_timezone": body.timezone,
            },
        )
    )
    if isinstance(row, list):
        row = row[0] if row else None
    if not isinstance(row, dict):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "database_unavailable", "message": "The request could not be completed right now."},
        )
    response.headers["ETag"] = f'"{row["version"]}"'
    return ResourceEnvelope(
        data=_business_response(row, "owner"),
        request_id=request.state.request_id,
    )


@router.get(
    "/businesses/{business_id}",
    response_model=ResourceEnvelope[BusinessResponse],
)
def get_business(
    business_id: UUID,
    request: Request,
    response: Response,
    user: User,
    client: Database,
) -> ResourceEnvelope[BusinessResponse]:
    membership = get_business_membership(client, business_id, user.id)
    row = execute(
        client.table("businesses")
        .select("*")
        .eq("id", str(business_id))
        .single()
    )
    response.headers["ETag"] = f'"{row["version"]}"'
    return ResourceEnvelope(
        data=_business_response(row, membership["role"]),
        request_id=request.state.request_id,
    )


@router.patch(
    "/businesses/{business_id}",
    response_model=ResourceEnvelope[BusinessResponse],
)
def update_business(
    business_id: UUID,
    body: BusinessUpdate,
    request: Request,
    response: Response,
    user: User,
    client: Database,
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> ResourceEnvelope[BusinessResponse]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin"})
    current = execute(
        client.table("businesses")
        .select("*")
        .eq("id", str(business_id))
        .single()
    )
    require_matching_etag(if_match, current["version"])
    changes = body.model_dump(mode="json", exclude_unset=True)
    if changes:
        row = execute(
            client.table("businesses")
            .update(changes)
            .eq("id", str(business_id))
            .eq("version", current["version"])
            .select("*")
            .maybe_single()
        )
        if not row:
            raise HTTPException(
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                detail={"code": "stale_resource", "message": "The resource has changed. Refresh and retry."},
            )
    else:
        row = current
    response.headers["ETag"] = f'"{row["version"]}"'
    return ResourceEnvelope(
        data=_business_response(row, membership["role"]),
        request_id=request.state.request_id,
    )


@router.get(
    "/businesses/{business_id}/members",
    response_model=CollectionEnvelope[BusinessMemberResponse],
)
def list_members(
    business_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> CollectionEnvelope[BusinessMemberResponse]:
    get_business_membership(client, business_id, user.id)
    rows = execute(
        client.table("business_members")
        .select("id,user_id,role,created_at")
        .eq("business_id", str(business_id))
        .order("created_at")
    )
    return CollectionEnvelope(
        data=rows,
        meta=PaginationMeta(next_cursor=None, has_more=False),
        request_id=request.state.request_id,
    )


@router.post(
    "/businesses/{business_id}/invitations",
    status_code=status.HTTP_201_CREATED,
    response_model=ResourceEnvelope[InvitationResponse],
)
def create_invitation(
    business_id: UUID,
    body: InvitationCreate,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[InvitationResponse]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin"})
    invitation_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(invitation_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    invitation = execute(
        client.table("invitations")
        .insert(
            {
                "business_id": str(business_id),
                "email": str(body.email).lower(),
                "role": body.role,
                "token_hash": token_hash,
                "invited_by": str(user.id),
                "expires_at": expires_at.isoformat(),
            }
        )
        .select("id,business_id,email,role,status,expires_at,created_at")
        .single()
    )
    try:
        deliver_invitation(
            email=invitation["email"],
            role=invitation["role"],
            business_id=str(business_id),
            invitation_token=invitation_token,
        )
    except RuntimeError as error:
        execute(
            client.table("invitations")
            .delete()
            .eq("id", invitation["id"])
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "invitation_delivery_unavailable", "message": "The invitation could not be delivered."},
        ) from error
    return ResourceEnvelope(
        data=InvitationResponse(**invitation),
        request_id=request.state.request_id,
    )


@router.patch(
    "/businesses/{business_id}/members/{member_id}",
    response_model=ResourceEnvelope[BusinessMemberResponse],
)
def update_member_role(
    business_id: UUID,
    member_id: UUID,
    body: MemberRoleUpdate,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[BusinessMemberResponse]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner"})
    row = execute(
        client.rpc(
            "update_business_member",
            {
                "target_business_id": str(business_id),
                "target_member_id": str(member_id),
                "new_role": body.role,
            },
        )
    )
    if isinstance(row, list):
        row = row[0] if row else None
    if not isinstance(row, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested resource was not found."},
        )
    return ResourceEnvelope(
        data=BusinessMemberResponse(**row),
        request_id=request.state.request_id,
    )


@router.delete(
    "/businesses/{business_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_member(
    business_id: UUID,
    member_id: UUID,
    user: User,
    client: Database,
) -> None:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner"})
    execute(
        client.rpc(
            "remove_business_member",
            {
                "target_business_id": str(business_id),
                "target_member_id": str(member_id),
            },
        )
    )


@router.post(
    "/invitations/{invitation_token}/accept",
    response_model=ResourceEnvelope[dict[str, UUID]],
)
def accept_invitation(
    invitation_token: str,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[dict[str, UUID]]:
    if len(invitation_token) < 32 or len(invitation_token) > 512:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested resource was not found."},
        )
    business_id = execute(
        client.rpc(
            "accept_business_invitation",
            {"invitation_token_hash": hashlib.sha256(invitation_token.encode()).hexdigest()},
        )
    )
    if isinstance(business_id, list):
        business_id = business_id[0] if business_id else None
    try:
        resolved_business_id = UUID(str(business_id))
    except (ValueError, TypeError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "database_unavailable", "message": "The request could not be completed right now."},
        ) from error
    return ResourceEnvelope(
        data={"business_id": resolved_business_id},
        request_id=request.state.request_id,
    )
