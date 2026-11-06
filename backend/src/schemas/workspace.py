from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AnyHttpUrl, EmailStr, Field, field_validator

from src.schemas.common import RequestModel


MembershipRole = Literal["owner", "admin", "staff", "read_only"]


class BusinessCreate(RequestModel):
    name: str = Field(min_length=1, max_length=160)
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    timezone: str = Field(default="UTC", min_length=1, max_length=64)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Invalid timezone.") from error
        return value


class BusinessUpdate(RequestModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    support_email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    website: AnyHttpUrl | None = None
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    return_policy: str | None = Field(default=None, max_length=10000)
    delivery_policy: str | None = Field(default=None, max_length=10000)

    @field_validator("name", "currency", "timezone", mode="before")
    @classmethod
    def reject_null_required_values(cls, value: object) -> object:
        if value is None:
            raise ValueError("This field cannot be null.")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError as error:
                raise ValueError("Invalid timezone.") from error
        return value


class BusinessResponse(RequestModel):
    id: UUID
    name: str
    country: str | None
    currency: str
    timezone: str
    support_email: str | None = None
    phone: str | None = None
    website: str | None = None
    return_policy: str | None = None
    delivery_policy: str | None = None
    role: MembershipRole | None = None
    created_at: datetime
    updated_at: datetime


class InvitationCreate(RequestModel):
    email: EmailStr
    role: Literal["admin", "staff", "read_only"]


class InvitationResponse(RequestModel):
    id: UUID
    business_id: UUID
    email: EmailStr
    role: Literal["admin", "staff", "read_only"]
    status: Literal["pending", "accepted", "expired", "revoked"]
    expires_at: datetime
    created_at: datetime


class InvitationAccept(RequestModel):
    token: str = Field(min_length=32, max_length=512)


class MemberRoleUpdate(RequestModel):
    role: MembershipRole


class BusinessMemberResponse(RequestModel):
    id: UUID
    user_id: UUID
    role: MembershipRole
    created_at: datetime
