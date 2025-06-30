import secrets
from typing import Any
from urllib.parse import urlencode

import requests
from pydantic import ValidationError
from typing_extensions import override

from onyx.configs.app_configs import WEB_DOMAIN
from onyx.context.search.federated.slack_search import slack_retrieval
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import SearchQuery
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.federated_connectors.interfaces import FederatedConnectorBase
from onyx.federated_connectors.models import CredentialField
from onyx.federated_connectors.models import EntityField
from onyx.federated_connectors.models import OAuthResult
from onyx.federated_connectors.slack.models import SlackCredentials
from onyx.federated_connectors.slack.models import SlackEntities
from onyx.federated_connectors.slack.models import SlackOAuthConfig
from onyx.utils.logger import setup_logger

logger = setup_logger()


class SlackFederatedConnector(FederatedConnectorBase):
    """Federated connector implementation for Slack."""

    @override
    def validate(self, entities: dict[str, Any]) -> bool:
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

    @override
    def entities(self) -> dict[str, EntityField]:
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

    @override
    def credentials_schema(self) -> dict[str, CredentialField]:
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
            "redirect_uri": CredentialField(
                type="str",
                description="OAuth redirect URI (optional - will use default if not provided)",
                required=False,
                example="https://your-domain.com/api/federated/slack/callback",
                secret=False,
            ),
        }

    @override
    def validate_credentials(self, credentials: dict[str, Any]) -> bool:
        """Validate that the provided credentials match the expected structure."""
        try:
            # Use Pydantic model for validation
            SlackCredentials(**credentials)
            return True
        except ValidationError as e:
            logger.warning(f"Validation error for Slack credentials: {e}")
            return False
        except Exception as e:
            logger.error(f"Error validating Slack credentials: {e}")
            return False

    def __init__(self, credentials: dict[str, Any]):
        """Initialize with credentials.

        Args:
            credentials: Credentials from the federated connector. If not provided, will use defaults or env vars.
        """
        self.oauth_config = SlackOAuthConfig(
            client_id=credentials.get("client_id", ""),
            client_secret=credentials.get("client_secret", ""),
            redirect_uri=credentials.get("redirect_uri")
            or self._get_default_redirect_uri(),
        )

    def _get_default_redirect_uri(self) -> str:
        """Get default redirect URI."""
        return f"{WEB_DOMAIN}/api/federated/slack/callback"

    @override
    def authorize(self) -> str:
        """Get back the OAuth URL for Slack authorization.

        Returns the URL where users should be redirected to authorize the application.
        """
        # Generate a secure state parameter (in production, store this for verification)
        state = secrets.token_urlsafe(32)

        # Build OAuth URL with proper parameters
        params = {
            "client_id": self.oauth_config.client_id,
            "user_scope": " ".join(["search:read"]),
            "redirect_uri": self.oauth_config.redirect_uri,
            "state": state,
        }

        # Build query string
        oauth_url = f"https://slack.com/oauth/v2/authorize?{urlencode(params)}"

        logger.info("Generated Slack OAuth authorization URL")
        return oauth_url

    @override
    def callback(self, callback_data: dict[str, Any]) -> OAuthResult:
        """Handle the response from the OAuth flow and return it in a standard format.

        Args:
            callback_data: The data received from the OAuth callback

        Returns:
            Standardized OAuthResult
        """
        try:
            # Extract authorization code from callback
            auth_code = callback_data.get("code")
            callback_data.get("state")
            error = callback_data.get("error")

            if error:
                logger.error(f"OAuth error received: {error}")
                return OAuthResult(
                    success=False,
                    error=error,
                    error_description=callback_data.get(
                        "error_description", "OAuth authorization failed"
                    ),
                )

            if not auth_code:
                logger.error("No authorization code received")
                return OAuthResult(
                    success=False,
                    error="missing_code",
                    error_description="Authorization code not received",
                )

            # Exchange authorization code for access token
            token_response = self._exchange_code_for_token(auth_code)

            if not token_response.get("ok"):
                return OAuthResult(
                    success=False,
                    error=token_response.get("error", "token_exchange_failed"),
                    error_description="Failed to exchange authorization code for token",
                )

            # Build team info
            team_info = None
            if "team" in token_response:
                team_info = {
                    "id": token_response["team"]["id"],
                    "name": token_response["team"]["name"],
                }

            # Build user info
            user_info = None
            if "authed_user" in token_response:
                user_info = {
                    "id": token_response["authed_user"]["id"],
                    "scope": token_response["authed_user"].get("scope"),
                    "token_type": token_response["authed_user"].get("token_type"),
                }

            # Slack tokens don't expire by default
            return OAuthResult(
                success=True,
                access_token=token_response.get("access_token"),
                token_type=token_response.get("token_type", "bearer"),
                scope=token_response.get("scope"),
                expires_at=None,  # Slack tokens don't expire
                refresh_token=None,  # Slack doesn't use refresh tokens
                team=team_info,
                user=user_info,
                raw_response=token_response,
            )

        except Exception as e:
            logger.error(f"Error processing Slack OAuth callback: {e}")
            return OAuthResult(
                success=False,
                error="processing_error",
                error_description=f"Error processing OAuth callback: {str(e)}",
            )

    def _exchange_code_for_token(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for access token.

        Args:
            code: Authorization code from OAuth callback

        Returns:
            Token response from Slack API
        """
        try:
            response = requests.post(
                "https://slack.com/api/oauth.v2.access",
                data={
                    "client_id": self.oauth_config.client_id,
                    "client_secret": self.oauth_config.client_secret,
                    "code": code,
                    "redirect_uri": self.oauth_config.redirect_uri,
                },
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error exchanging code for token: {e}")
            return {"ok": False, "error": str(e)}

    @override
    def search(
        self,
        query: SearchQuery,
        entities: SlackEntities,  # type: ignore
        access_token: str,
        limit: int = 10,
    ) -> list[InferenceChunk]:
        """Perform a federated search on Slack.

        Args:
            query: The search query
            entities: The entities to search within (validated by validate())
            access_token: The OAuth access token
            limit: Maximum number of results to return

        Returns:
            Search results in SlackSearchResponse format
        """
        with get_session_with_current_tenant() as db_session:
            return slack_retrieval(query, db_session)
