"""Helper for managing Personal Access Tokens in integration tests."""

from uuid import UUID

import httpx

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import Permission
from onyx.db.pat import create_pat
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestPAT
from tests.integration.common_utils.test_models import DATestUser


class PATManager:
    """Manager for creating and managing Personal Access Tokens in tests."""

    @staticmethod
    def create_response(
        name: str,
        expiration_days: int | None,
        user_performing_action: DATestUser,
        scopes: list[Permission] | None = None,
    ) -> httpx.Response:
        """Call the create-token API and return the raw response (no status check)."""
        body: dict[str, object] = {"name": name, "expiration_days": expiration_days}
        if scopes is not None:
            body["scopes"] = [scope.value for scope in scopes]
        return client.post(
            f"{API_SERVER_URL}/user/pats",
            json=body,
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
            timeout=60,
        )

    @staticmethod
    def create(
        name: str,
        expiration_days: int | None,
        user_performing_action: DATestUser,
        scopes: list[Permission] | None = None,
    ) -> DATestPAT:
        """Create a Personal Access Token for a user via the API.

        scopes=None mints an unrestricted token (full user access); a list scopes
        it to those permissions. Returns the DATestPAT including the raw token.
        """
        response = PATManager.create_response(
            name, expiration_days, user_performing_action, scopes
        )
        response.raise_for_status()
        return DATestPAT(**response.json())

    @staticmethod
    def selectable_scopes(user_performing_action: DATestUser) -> list[dict[str, str]]:
        """Fetch the scopes a user may assign when minting a token."""
        response = client.get(
            f"{API_SERVER_URL}/user/pats/scopes",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def create_scoped(
        name: str,
        expiration_days: int | None,
        user_performing_action: DATestUser,
        scopes: list[Permission] | None,
    ) -> str:
        """Mint a PAT with explicit scopes and return the raw token."""
        with get_session_with_current_tenant() as db_session:
            _, raw_token = create_pat(
                db_session=db_session,
                user_id=UUID(user_performing_action.id),
                name=name,
                expiration_days=expiration_days,
                scopes=scopes,
            )
            db_session.commit()
        return raw_token

    @staticmethod
    def scoped_auth_headers(
        name: str,
        expiration_days: int | None,
        user_performing_action: DATestUser,
        scopes: list[Permission] | None,
    ) -> dict[str, str]:
        """Mint a scoped PAT and return its bearer auth headers."""
        raw_token = PATManager.create_scoped(
            name=name,
            expiration_days=expiration_days,
            user_performing_action=user_performing_action,
            scopes=scopes,
        )
        return PATManager.get_auth_headers(raw_token)

    @staticmethod
    def list(user_performing_action: DATestUser) -> list[DATestPAT]:
        """List all PATs for a user.

        Args:
            user_performing_action: User listing their tokens

        Returns:
            List of DATestPAT (without raw tokens)
        """
        response = client.get(
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
        response = client.delete(
            f"{API_SERVER_URL}/user/pats/{token_id}",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
            timeout=60,
        )
        response.raise_for_status()

    @staticmethod
    def authenticate(token: str) -> httpx.Response:
        """Authenticate using a PAT token and get user info.

        Args:
            token: The raw PAT token

        Returns:
            Response from /me endpoint
        """
        return client.get(
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
