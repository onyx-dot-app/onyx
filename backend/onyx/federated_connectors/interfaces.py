from abc import ABC
from abc import abstractmethod
from typing import Any
from typing import Dict

from pydantic import BaseModel

from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import SearchQuery
from onyx.federated_connectors.models import CredentialField
from onyx.federated_connectors.models import EntityField
from onyx.federated_connectors.models import OAuthResult


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
