from typing import Any

from pydantic import BaseModel


class ZendeskUser(BaseModel):
    id: int
    name: str | None = None
    email: str | None = None
    role: str | None = None


class ZendeskPageResponse(BaseModel):
    data: list[dict[str, Any]]
    meta: dict[str, Any]
    has_more: bool
