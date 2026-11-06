from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AnyHttpUrl, EmailStr, Field, field_validator

from src.schemas.common import RequestModel
from src.schemas.workspace import BusinessResponse


class NotificationPreferences(RequestModel):
    new_conversations: bool = True
    approval_requests: bool = True
    payment_updates: bool = True
    weekly_summary: bool = True


class NotificationPreferencesUpdate(RequestModel):
    new_conversations: bool | None = None
    approval_requests: bool | None = None
    payment_updates: bool | None = None
    weekly_summary: bool | None = None


class BusinessSettingsResponse(RequestModel):
    business: BusinessResponse
    notifications: NotificationPreferences
    privacy: dict[str, str | int | bool | None] = Field(default_factory=dict)


class BusinessSettingsUpdate(RequestModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    support_email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    website: AnyHttpUrl | None = None
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    return_policy: str | None = Field(default=None, max_length=10000)
    delivery_policy: str | None = Field(default=None, max_length=10000)
    notifications: NotificationPreferencesUpdate | None = None

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
