from typing import Literal
from uuid import UUID

from pydantic import AnyUrl

from src.schemas.common import RequestModel


class SearchResult(RequestModel):
    type: Literal["conversation", "order", "product", "business"]
    id: UUID
    title: str
    subtitle: str | None
    resource_url: AnyUrl | str
