from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from urllib.parse import urlencode

import requests
from pydantic import ValidationError
from typing_extensions import override

from onyx.context.search.federated.slack_search import slack_retrieval
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import SearchQuery
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.federated_connectors.interfaces import FederatedConnector
from onyx.federated_connectors.models import CredentialField
from onyx.federated_connectors.models import EntityField
from onyx.federated_connectors.models import OAuthResult
from onyx.federated_connectors.slack.models import SlackCredentials
from onyx.federated_connectors.slack.models import SlackEntities
from onyx.onyxbot.slack.models import SlackContext
from onyx.utils.logger import setup_logger

logger = setup_logger()


SCOPES = [
    "search:read",
    "channels:history",
    "groups:history",
    "im:history",
    "mpim:history",
    "users.profile:read",
]


class SlackFederatedConnector(FederatedConnector):
    def __init__(self, credentials: dict[str, Any]):
        self.slack_credentials = SlackCredentials(**credentials)

    @override
    def validate_entities(self, entities: dict[str, Any]) -> bool:
        """Check the entities and verify that they match the expected structure/all values are valid.

        For Slack federated search, we expect:
        - channels: list[str] (list of channel names or IDs)
        - include_dm: bool (whether to include direct messages)
        """
        try:
            # Use Pydantic model for validation
            SlackEntities(**entities)
            return True
        except ValidationError as e:
            logger.warning(f"Validation error for Slack entities: {e}")
            return False
        except Exception as e:
            logger.error(f"Error validating Slack entities: {e}")
            return False

    @classmethod
    @override
    def entities_schema(cls) -> dict[str, EntityField]:
        """Return the specifications of what entities are available for this federated search type.

        Returns a specification that tells the caller:
        - channels is valid and should be a list[str]
        - include_dm is valid and should be a boolean
        """
        return {
            "channels": EntityField(
                type="list[str]",
                description="List of Slack channel names or IDs to search in",
                required=False,
                example=["general", "random", "C1234567890"],
            ),
            "include_dm": EntityField(
                type="bool",
                description="Whether to include direct messages in the search",
                required=False,
                default=False,
                example=True,
            ),
        }

    @classmethod
    @override
    def credentials_schema(cls) -> dict[str, CredentialField]:
        """Return the specification of what credentials are required for Slack connector."""
        return {
            "client_id": CredentialField(
                type="str",
                description="Slack app client ID from your Slack app configuration",
                required=True,
                example="1234567890.1234567890123",
                secret=False,
            ),
            "client_secret": CredentialField(
                type="str",
                description="Slack app client secret from your Slack app configuration",
                required=True,
                example="1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p",
                secret=True,
            ),
        }

    @override
    def authorize(self, redirect_uri: str) -> str:
        """Get back the OAuth URL for Slack authorization.

        Returns the URL where users should be redirected to authorize the application.
        Note: State parameter will be added by the API layer.
        """
        # Build OAuth URL with proper parameters (no state - handled by API layer)
        params = {
            "client_id": self.slack_credentials.client_id,
            "user_scope": " ".join(SCOPES),
            "redirect_uri": redirect_uri,
        }

        # Build query string
        oauth_url = f"https://slack.com/oauth/v2/authorize?{urlencode(params)}"

        logger.info("Generated Slack OAuth authorization URL")
        return oauth_url

    @override
    def callback(self, callback_data: dict[str, Any], redirect_uri: str) -> OAuthResult:
        """Handle the response from the OAuth flow and return it in a standard format.

        Args:
            callback_data: The data received from the OAuth callback (state already validated by API layer)

        Returns:
            Standardized OAuthResult
        """
        # Extract authorization code from callback
        auth_code = callback_data.get("code")
        error = callback_data.get("error")

        if error:
            raise RuntimeError(f"OAuth error received: {error}")

        if not auth_code:
            raise ValueError("No authorization code received")

        # Exchange authorization code for access token
        token_response = self._exchange_code_for_token(auth_code, redirect_uri)

        if not token_response.get("ok"):
            raise RuntimeError(
                f"Failed to exchange authorization code for token: {token_response.get('error')}"
            )

        # Build team info
        team_info = None
        if "team" in token_response:
            team_info = {
                "id": token_response["team"]["id"],
                "name": token_response["team"]["name"],
            }

        # Build user info and extract OAuth tokens
        if "authed_user" not in token_response:
            raise RuntimeError("Missing authed_user in OAuth response from Slack")

        authed_user = token_response["authed_user"]
        user_info = {
            "id": authed_user["id"],
            "scope": authed_user.get("scope"),
            "token_type": authed_user.get("token_type"),
        }

        # Extract OAuth tokens - bot token from root, user token from authed_user
        user_token = authed_user.get("access_token")  # User token
        refresh_token = authed_user.get("refresh_token")
        token_type = authed_user.get("token_type", "bearer")
        scope = authed_user.get("scope")

        # Calculate expires_at from expires_in if present
        expires_at = None
        if "expires_in" in authed_user:
            expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=authed_user["expires_in"]
            )

        return OAuthResult(
            access_token=user_token,  # Bot token for bot operations
            token_type=token_type,
            scope=scope,
            expires_at=expires_at,
            refresh_token=refresh_token,
            team=team_info,
            user=user_info,
            raw_response=token_response,
        )

    def _exchange_code_for_token(self, code: str, redirect_uri: str) -> dict[str, Any]:
        """Exchange authorization code for access token.

        Args:
            code: Authorization code from OAuth callback

        Returns:
            Token response from Slack API
        """
        response = requests.post(
            "https://slack.com/api/oauth.v2.access",
            data={
                "client_id": self.slack_credentials.client_id,
                "client_secret": self.slack_credentials.client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        response.raise_for_status()
        return response.json()

    @override
    def search(
        self,
        query: SearchQuery,
        entities: dict[str, Any],
        access_token: str,
        limit: int | None = None,
        slack_event_context: SlackContext | None = None,
        bot_token: str | None = None,
    ) -> list[InferenceChunk]:
        """Perform a federated search on Slack.

        Args:
            query: The search query
            entities: The entities to search within (validated by validate())
            access_token: The OAuth access token
            limit: Maximum number of results to return
            slack_event_context: Optional Slack context for slack bot
            bot_token: Optional bot token for slack bot

        Returns:
            Search results in SlackSearchResponse format
        """
        logger.info(f"Slack federated search called with entities: {entities}")

        with get_session_with_current_tenant() as db_session:
            return slack_retrieval(
                query,
                access_token,
                db_session,
                limit,
                slack_event_context=slack_event_context,
                bot_token=bot_token,
            )
