import base64
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from postgrest.exceptions import APIError
from supabase import Client


def execute_response(query: Any) -> Any:
    try:
        return query.execute()
    except APIError as error:
        if error.code == "23505":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "conflict", "message": "The request conflicts with existing data."},
            ) from error
        if error.code == "23503" or error.code == "23514":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "validation_error", "message": "The request could not be completed."},
            ) from error
        if error.code == "42501":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "not_authorized", "message": "You are not allowed to perform this action."},
            ) from error
        if error.code == "40001":
            raise HTTPException(
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                detail={"code": "stale_resource", "message": "The resource has changed. Refresh and retry."},
            ) from error
        if error.code == "P0002":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "The requested resource was not found."},
            ) from error
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "database_unavailable", "message": "The request could not be completed right now."},
        ) from error
    except httpx.HTTPError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "database_unavailable", "message": "The request could not be completed right now."},
        ) from error


def execute(query: Any) -> Any:
    return execute_response(query).data


def count_rows(query: Any) -> int:
    response = execute_response(query)
    if response.count is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "database_unavailable", "message": "The request could not be completed right now."},
        )
    return response.count


def get_business_membership(
    client: Client,
    business_id: UUID,
    user_id: UUID,
) -> dict[str, Any]:
    membership = execute(
        client.table("business_members")
        .select("id,role")
        .eq("business_id", str(business_id))
        .eq("user_id", str(user_id))
        .maybe_single()
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested resource was not found."},
        )
    return membership


def require_role(
    membership: dict[str, Any],
    allowed_roles: set[str],
) -> None:
    if membership["role"] not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "not_authorized", "message": "You are not allowed to perform this action."},
        )


def require_matching_etag(if_match: str | None, version: int) -> None:
    if if_match is None:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={"code": "if_match_required", "message": "An If-Match header is required."},
        )
    try:
        supplied_version = int(if_match.strip('"'))
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_if_match", "message": "The If-Match header is invalid."},
        ) from error
    if supplied_version != version:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail={"code": "stale_resource", "message": "The resource has changed. Refresh and retry."},
        )


def encode_cursor(created_at: str, resource_id: str) -> str:
    payload = f"{created_at}|{resource_id}".encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[str, str] | None:
    if cursor is None:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        created_at, resource_id = base64.urlsafe_b64decode(padded).decode().split("|", 1)
        parsed_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if parsed_date.tzinfo is None:
            raise ValueError
        parsed_date = parsed_date.astimezone(timezone.utc)
        parsed_id = UUID(resource_id)
        return parsed_date.isoformat(), str(parsed_id)
    except (ValueError, UnicodeDecodeError) as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_cursor", "message": "The cursor is invalid."},
        ) from error


def paginated_rows(
    query: Any,
    *,
    cursor: str | None,
    limit: int,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    decoded = decode_cursor(cursor)
    query = query.order("created_at", desc=True).order("id", desc=True)
    if decoded:
        created_at, resource_id = decoded
        query = query.or_(
            f"created_at.lt.{created_at},and(created_at.eq.{created_at},id.lt.{resource_id})"
        )
    rows = execute(query.limit(limit + 1))
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        next_cursor = encode_cursor(rows[-1]["created_at"], rows[-1]["id"])
    return rows, next_cursor, has_more
