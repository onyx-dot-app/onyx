from abc import ABC
from abc import abstractmethod
from datetime import datetime
from typing import Any
from typing import Dict
from typing import Optional

from pydantic import BaseModel
from pydantic import Field

from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import SearchQuery


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

    success: bool = Field(..., description="Whether the OAuth flow was successful")
    access_token: Optional[str] = Field(
        default=None, description="The access token received"
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
    error: Optional[str] = Field(default=None, description="Error code if failed")
    error_description: Optional[str] = Field(
        default=None, description="Human-readable error description"
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


class FederatedConnectorBase(ABC):
    """Base interface that all federated connectors must implement."""

    @abstractmethod
    def validate(self, entities: Dict[str, Any]) -> bool:
        """
        Validate that the provided entities match the expected structure.

        Args:
            entities: Dictionary of entities to validate

        Returns:
            True if entities are valid, False otherwise
        """

    @abstractmethod
    def entities(self) -> Dict[str, EntityField]:
        """
        Return the specification of what entities are available for this connector.

        Returns:
            Dictionary where keys are entity names and values are EntityField objects
            describing the expected structure and constraints.
        """

    @abstractmethod
    def credentials_schema(self) -> Dict[str, CredentialField]:
        """
        Return the specification of what credentials are required for this connector.

        Returns:
            Dictionary where keys are credential field names and values are CredentialField objects
            describing the expected structure, validation rules, and security properties.
        """

    @abstractmethod
    def validate_credentials(self, credentials: Dict[str, Any]) -> bool:
        """
        Validate that the provided credentials match the expected structure and constraints.

        Args:
            credentials: Dictionary of credentials to validate

        Returns:
            True if credentials are valid, False otherwise
        """

    @abstractmethod
    def authorize(self) -> str:
        """
        Generate the OAuth authorization URL.

        Returns:
            The URL where users should be redirected to authorize the application
        """

    @abstractmethod
    def callback(self, callback_data: Dict[str, Any]) -> OAuthResult:
        """
        Handle the OAuth callback and exchange the authorization code for tokens.

        Args:
            callback_data: The data received from the OAuth callback (query params, etc.)

        Returns:
            Standardized OAuthResult containing tokens and metadata
        """

    @abstractmethod
    def search(
        self,
        query: SearchQuery,
        entities: BaseModel,  # some pydantic model, defined on a per-connector basis
        access_token: str,
        limit: int = 10,
    ) -> list[InferenceChunk]:
        """
        Perform a federated search using the provided query and entities.

        Args:
            query: The search query
            entities: The entities to search within (validated by validate())
            access_token: The OAuth access token
            limit: Maximum number of results to return

        Returns:
            Search results in a standardized format
        """
