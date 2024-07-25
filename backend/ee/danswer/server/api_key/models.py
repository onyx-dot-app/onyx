from pydantic import BaseModel


class APIKeyArgs(BaseModel):
    name: str | None = None
