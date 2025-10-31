from pydantic import BaseModel

from onyx.auth.schemas import ApiKeyType
from onyx.auth.schemas import UserRole


class APIKeyArgs(BaseModel):
    name: str | None = None  # Optional name
    type: ApiKeyType | None = (
        None  # Required for creating new API keys, optional/ignored when updating existing API keys
    )
    role: UserRole | None = (
        None  # Required for Service Account type API keys, omitted for Personal Access Token type API keys
    )
