from datetime import datetime
from typing import Any
from typing import Dict
from typing import Optional

from pydantic import BaseModel
from pydantic import Field


class FieldSpec(BaseModel):
    """Model for describing a field specification."""

    type: str = Field(
        ..., description="The type of the field (e.g., 'str', 'bool', 'list[str]')"
    )
    description: str = Field(
        ..., description="Description of what this field represents"
    )
    required: bool = Field(default=False, description="Whether this field is required")
    default: Optional[Any] = Field(
        default=None, description="Default value if not provided"
    )
    example: Optional[Any] = Field(
        default=None, description="Example value for documentation"
    )
    secret: bool = Field(
        default=False, description="Whether this field contains sensitive data"
    )


class EntityField(FieldSpec):
    """Model for describing an entity field in the entities specification."""


class CredentialField(FieldSpec):
    """Model for describing a credential field in the credentials specification."""


class OAuthResult(BaseModel):
    """Standardized OAuth result that all federated connectors should return from callback."""

    access_token: Optional[str] = Field(
        default=None, description="The bot access token for bot operations"
    )
    user_token: Optional[str] = Field(
        default=None,
        description="The user access token for user-scoped operations like federated search",
    )
    token_type: Optional[str] = Field(
        default=None, description="Token type (usually 'bearer')"
    )
    scope: Optional[str] = Field(default=None, description="Granted scopes")
    expires_at: Optional[datetime] = Field(
        default=None, description="When the token expires"
    )
    refresh_token: Optional[str] = Field(
        default=None, description="Refresh token if applicable"
    )

    # Additional fields that might be useful
    team: Optional[Dict[str, Any]] = Field(
        default=None, description="Team/workspace information"
    )
    user: Optional[Dict[str, Any]] = Field(default=None, description="User information")
    raw_response: Optional[Dict[str, Any]] = Field(
        default=None, description="Raw response for debugging"
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
