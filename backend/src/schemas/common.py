from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PaginationMeta(BaseModel):
    next_cursor: str | None
    has_more: bool


DataT = TypeVar("DataT")


class ResourceEnvelope(BaseModel, Generic[DataT]):
    data: DataT
    request_id: str


class CollectionEnvelope(BaseModel, Generic[DataT]):
    data: list[DataT]
    meta: PaginationMeta
    request_id: str


class CursorQuery(RequestModel):
    cursor: str | None = None
    limit: int = Field(default=25, ge=1, le=100)
