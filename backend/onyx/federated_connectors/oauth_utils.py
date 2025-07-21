"""Generic OAuth utilities for federated connectors API layer."""

import base64
import json
import uuid
from typing import Any
from typing import cast
from typing import Dict
from typing import Optional

from onyx.configs.app_configs import WEB_DOMAIN
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Redis key prefix for OAuth state
OAUTH_STATE_PREFIX = "federated_oauth"
# Default TTL for OAuth state (5 minutes)
OAUTH_STATE_TTL = 300


class OAuthSession:
    """Represents an OAuth session stored in Redis."""

    def __init__(
        self,
        federated_connector_id: int,
        user_id: str,
        redirect_uri: Optional[str] = None,
        additional_data: Optional[Dict[str, Any]] = None,
    ):
        self.federated_connector_id = federated_connector_id
        self.user_id = user_id
        self.redirect_uri = redirect_uri
        self.additional_data = additional_data or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Redis storage."""
        return {
            "federated_connector_id": self.federated_connector_id,
            "user_id": self.user_id,
            "redirect_uri": self.redirect_uri,
            "additional_data": self.additional_data,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OAuthSession":
        """Create from dictionary retrieved from Redis."""
        return cls(
            federated_connector_id=data["federated_connector_id"],
            user_id=data["user_id"],
            redirect_uri=data.get("redirect_uri"),
            additional_data=data.get("additional_data", {}),
        )


def generate_oauth_state(
    federated_connector_id: int,
    user_id: str,
    redirect_uri: Optional[str] = None,
    additional_data: Optional[Dict[str, Any]] = None,
    ttl: int = OAUTH_STATE_TTL,
) -> str:
    """
    Generate a secure state parameter and store session data in Redis.

    Args:
        federated_connector_id: ID of the federated connector
        user_id: ID of the user initiating OAuth
        redirect_uri: Optional redirect URI after OAuth completion
        additional_data: Any additional data to store with the session
        ttl: Time-to-live in seconds for the Redis key

    Returns:
        Base64-encoded state parameter
    """
    # Generate a random UUID for the state
    state_uuid = uuid.uuid4()

    # Convert UUID to base64 for URL-safe state parameter
    state_bytes = state_uuid.bytes
    state_b64 = base64.urlsafe_b64encode(state_bytes).decode("utf-8").rstrip("=")

    # Create session object
    session = OAuthSession(
        federated_connector_id=federated_connector_id,
        user_id=user_id,
        redirect_uri=redirect_uri,
        additional_data=additional_data,
    )

    # Store in Redis with TTL
    redis_client = get_redis_client()
    redis_key = f"{OAUTH_STATE_PREFIX}:{state_uuid}"

    redis_client.set(
        redis_key,
        json.dumps(session.to_dict()),
        ex=ttl,
    )

    logger.info(
        f"Generated OAuth state for federated_connector_id={federated_connector_id}, "
        f"user_id={user_id}, state={state_b64}"
    )

    return state_b64


def verify_oauth_state(state: str) -> OAuthSession:
    """
    Verify OAuth state parameter and retrieve session data.

    Args:
        state: Base64-encoded state parameter from OAuth callback

    Returns:
        OAuthSession if state is valid, None otherwise
    """
    # Add padding if needed for base64 decoding
    padded_state = state + "=" * (-len(state) % 4)

    # Decode base64 to get UUID bytes
    state_bytes = base64.urlsafe_b64decode(padded_state)
    state_uuid = uuid.UUID(bytes=state_bytes)

    # Look up in Redis
    redis_client = get_redis_client()
    redis_key = f"{OAUTH_STATE_PREFIX}:{state_uuid}"

    session_data = cast(bytes, redis_client.get(redis_key))
    if not session_data:
        raise ValueError(f"OAuth state not found in Redis: {state}")

    # Delete the key after retrieval (one-time use)
    redis_client.delete(redis_key)

    # Parse and return session
    session_dict = json.loads(session_data)
    return OAuthSession.from_dict(session_dict)


def get_oauth_callback_uri() -> str:
    """
    Generate the OAuth callback URI for a federated connector.

    Returns:
        The callback URI
    """
    # Use the frontend callback page as the OAuth redirect URI
    # The frontend will then make an API call to process the callback
    return f"{WEB_DOMAIN}/federated/oauth/callback"


def add_state_to_oauth_url(base_oauth_url: str, state: str) -> str:
    """
    Add state parameter to an OAuth URL.

    Args:
        base_oauth_url: The base OAuth URL from the connector
        state: The state parameter to add

    Returns:
        The OAuth URL with state parameter added
    """
    # Check if URL already has query parameters
    separator = "&" if "?" in base_oauth_url else "?"
    return f"{base_oauth_url}{separator}state={state}"
