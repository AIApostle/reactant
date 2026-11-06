from datetime import datetime
import logging

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from supabase_auth.errors import AuthApiError, AuthRetryableError

from src.supabase.client import get_supabase_client


bearer_scheme = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


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
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        logger.warning("authentication_missing request_id=%s", getattr(request.state, "request_id", "unknown"))
        raise _unauthenticated()

    try:
        response = get_supabase_client().auth.get_user(credentials.credentials)
    except AuthApiError as error:
        logger.warning(
            "authentication_provider_error request_id=%s status=%s",
            getattr(request.state, "request_id", "unknown"),
            error.status,
        )
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
        logger.error(
            "authentication_provider_unavailable request_id=%s error_type=%s",
            getattr(request.state, "request_id", "unknown"),
            type(error).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "identity_provider_unavailable",
                "message": "Authentication could not be completed right now.",
            },
        ) from error

    if response is None or response.user is None:
        logger.warning("authentication_empty_user request_id=%s", getattr(request.state, "request_id", "unknown"))
        raise _unauthenticated()

    user = response.user
    logger.info(
        "authentication_succeeded request_id=%s user_id=%s",
        getattr(request.state, "request_id", "unknown"),
        user.id,
    )
    return AuthenticatedUser(
        id=user.id,
        email=user.email,
        created_at=user.created_at,
    )
