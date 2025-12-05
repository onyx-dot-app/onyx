"""Helper for managing Personal Access Tokens in integration tests."""

import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.test_models import DATestPAT
from tests.integration.common_utils.test_models import DATestUser


class PATManager:
    """Manager for creating and managing Personal Access Tokens in tests."""

    @staticmethod
    def create(
        name: str,
        expiration_days: int | None,
        user_performing_action: DATestUser,
    ) -> DATestPAT:
        """Create a Personal Access Token for a user.

        Args:
            name: Name of the token
            expiration_days: Number of days until expiration (None for never)
            user_performing_action: User creating the token

        Returns:
            DATestPAT with PAT data including the raw token
        """
        response = requests.post(
            f"{API_SERVER_URL}/user/pats",
            json={"name": name, "expiration_days": expiration_days},
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
            timeout=60,
        )
        response.raise_for_status()
        return DATestPAT(**response.json())

    @staticmethod
    def list(user_performing_action: DATestUser) -> list[DATestPAT]:
        """List all PATs for a user.

        Args:
            user_performing_action: User listing their tokens

        Returns:
            List of DATestPAT (without raw tokens)
        """
        response = requests.get(
            f"{API_SERVER_URL}/user/pats",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
            timeout=60,
        )
        response.raise_for_status()
        return [DATestPAT(**pat_data) for pat_data in response.json()]

    @staticmethod
    def revoke(token_id: int, user_performing_action: DATestUser) -> None:
        """Revoke a Personal Access Token.

        Args:
            token_id: ID of the token to revoke
            user_performing_action: User revoking the token
        """
        response = requests.delete(
            f"{API_SERVER_URL}/user/pats/{token_id}",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
            timeout=60,
        )
        response.raise_for_status()

    @staticmethod
    def authenticate(token: str) -> requests.Response:
        """Authenticate using a PAT token and get user info.

        Args:
            token: The raw PAT token

        Returns:
            Response from /me endpoint
        """
        return requests.get(
            f"{API_SERVER_URL}/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        )

    @staticmethod
    def get_auth_headers(token: str) -> dict[str, str]:
        """Get authorization headers for a PAT token.

        Args:
            token: The raw PAT token

        Returns:
            Headers dict with Authorization bearer token
        """
        return {"Authorization": f"Bearer {token}"}
