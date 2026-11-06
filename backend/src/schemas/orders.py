from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import EmailStr, Field

from src.schemas.common import RequestModel


class OrderLineCreate(RequestModel):
    product_id: UUID
    quantity: int = Field(ge=1, le=10000)


class OrderCreate(RequestModel):
    customer_name: str = Field(min_length=1, max_length=160)
    customer_email: EmailStr | None = None
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    items: list[OrderLineCreate] = Field(min_length=1, max_length=100)


class OrderLineResponse(RequestModel):
    id: UUID
    product_id: UUID
    product_name: str
    quantity: int
    unit_price_minor: int
    total_minor: int


class OrderResponse(RequestModel):
    id: UUID
    business_id: UUID
    customer_name: str
    customer_email: str | None
    status: str
    payment_status: str
    amount_minor: int
    currency: str
    items: list[OrderLineResponse]
    created_at: datetime
    updated_at: datetime


class CheckoutResponse(RequestModel):
    order_id: UUID
    payment_id: UUID | None = None
    provider: Literal["paypal"]
    status: Literal["checkout_created", "approval_required"]
    checkout_url: str | None = None
    approval_id: UUID | None = None
    amount_minor: int
    currency: str
    expires_at: datetime | None = None
