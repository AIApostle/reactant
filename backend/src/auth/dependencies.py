from datetime import datetime

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from supabase_auth.errors import AuthApiError, AuthRetryableError

from src.client.supabase import get_supabase_client


bearer_scheme = HTTPBearer(auto_error=False)


class AuthenticatedUser(BaseModel):
    id: str
    email: str | None
    created_at: datetime


def _unauthenticated() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "unauthenticated",
            "message": "Authentication is required.",
        },
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthenticated()

    try:
        response = get_supabase_client().auth.get_user(credentials.credentials)
    except AuthApiError as error:
        if error.status == 429:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "rate_limited",
                    "message": "Authentication could not be completed right now.",
                },
            ) from error
        if error.status < 500:
            raise _unauthenticated() from error
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "identity_provider_unavailable",
                "message": "Authentication could not be completed right now.",
            },
        ) from error
    except (AuthRetryableError, httpx.HTTPError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "identity_provider_unavailable",
                "message": "Authentication could not be completed right now.",
            },
        ) from error

    if response is None or response.user is None:
        raise _unauthenticated()

    user = response.user
    return AuthenticatedUser(
        id=user.id,
        email=user.email,
        created_at=user.created_at,
    )
