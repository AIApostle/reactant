"""Reactant API auth routes; sign-in and signup are handled directly by Supabase."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from src.auth.dependencies import AuthenticatedUser, get_current_user


router = APIRouter()


class CurrentUserEnvelope(BaseModel):
    data: AuthenticatedUser
    request_id: str


@router.get("/users/me", response_model=CurrentUserEnvelope)
def get_me(
    request: Request,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> CurrentUserEnvelope:
    return CurrentUserEnvelope(
        data=current_user,
        request_id=request.state.request_id,
    )
