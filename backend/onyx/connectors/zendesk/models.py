from pydantic import BaseModel


class ZendeskUser(BaseModel):
    id: int
    name: str | None = None
    email: str | None = None
    role: str | None = None
