from abc import ABC
from abc import abstractmethod
from typing import Any
from typing import Dict

from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import SearchQuery
from onyx.federated_connectors.models import CredentialField
from onyx.federated_connectors.models import EntityField
from onyx.federated_connectors.models import OAuthResult
from onyx.onyxbot.slack.models import SlackContext


class FederatedConnector(ABC):
    """Base interface that all federated connectors must implement."""

    @abstractmethod
    def __init__(self, credentials: dict[str, Any]):
        """
        Initialize the connector with credentials + validate their structure.

        Args:
            credentials: Dictionary of credentials to initialize the connector with
        """
        self.credentials = credentials

    @abstractmethod
    def validate_entities(self, entities: Dict[str, Any]) -> bool:
        """
        Validate that the provided entities match the expected structure.

        Args:
            entities: Dictionary of entities to validate

        Returns:
            True if entities are valid, False otherwise
        """

    @classmethod
    @abstractmethod
    def entities_schema(cls) -> Dict[str, EntityField]:
        """
        Return the specification of what entities are available for this connector.

        Returns:
            Dictionary where keys are entity names and values are EntityField objects
            describing the expected structure and constraints.
        """

    @classmethod
    @abstractmethod
    def credentials_schema(cls) -> Dict[str, CredentialField]:
        """
        Return the specification of what credentials are required for this connector.

        Returns:
            Dictionary where keys are credential field names and values are CredentialField objects
            describing the expected structure, validation rules, and security properties.
        """

    @abstractmethod
    def authorize(self, redirect_uri: str) -> str:
        """
        Generate the OAuth authorization URL.

        Returns:
            The URL where users should be redirected to authorize the application
        """

    @abstractmethod
    def callback(self, callback_data: Dict[str, Any], redirect_uri: str) -> OAuthResult:
        """
        Handle the OAuth callback and exchange the authorization code for tokens.

        Args:
            callback_data: The data received from the OAuth callback (query params, etc.)
            redirect_uri: The OAuth redirect URI used in the authorization request

        Returns:
            Standardized OAuthResult containing tokens and metadata
        """

    @abstractmethod
    def search(
        self,
        query: SearchQuery,
        entities: dict[str, Any],
        access_token: str,
        limit: int | None = None,
        # Slack-specific parameters
        slack_event_context: SlackContext | None = None,
        bot_token: str | None = None,
    ) -> list[InferenceChunk]:
        """
        Perform a federated search using the provided query and entities.

        Args:
            query: The search query
            entities: The entities to search within (validated by validate())
            access_token: The OAuth access token
            limit: Maximum number of results to return
            slack_event_context: Slack-specific context (only used by Slack bot)
            bot_token: Slack bot token (only used by Slack bot)

        Returns:
            Search results in a standardized format
        """
