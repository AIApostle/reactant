from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from src.schemas.common import RequestModel


class ApprovalDecisionCreate(RequestModel):
    decision: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=4000)


class ApprovalResponse(RequestModel):
    id: UUID
    business_id: UUID
    action_type: str
    status: str
    impact: dict[str, object]
    expires_at: datetime | None
    decided_by: UUID | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime
