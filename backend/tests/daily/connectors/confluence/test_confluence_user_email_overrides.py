import types
from unittest.mock import patch

from onyx.connectors.confluence.onyx_confluence import ConfluenceUser
from onyx.connectors.confluence.onyx_confluence import OnyxConfluence
from onyx.connectors.interfaces import CredentialsProviderInterface


class MockCredentialsProvider(CredentialsProviderInterface):
    def get_tenant_id(self) -> str:
        return "test_tenant"

    def get_provider_key(self) -> str:
        return "test_provider"

    def is_dynamic(self) -> bool:
        return False

    def get_credentials(self) -> dict[str, str]:
        return {"confluence_access_token": "test_token"}

    def set_credentials(self, credentials: dict[str, str]) -> None:
        pass

    def __enter__(self) -> "MockCredentialsProvider":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        pass


def test_paginated_cql_user_retrieval_with_overrides() -> None:
    """
    Tests that paginated_cql_user_retrieval yields users from the overrides
    when provided and is_cloud is False.
    """
    mock_provider = MockCredentialsProvider()
    overrides = [
        {
            "user_id": "override_user_1",
            "username": "override1",
            "display_name": "Override User One",
            "email": "override1@example.com",
            "type": "override",
        },
        {
            "user_id": "override_user_2",
            "username": "override2",
            "display_name": "Override User Two",
            "email": "override2@example.com",
            "type": "override",
        },
    ]
    expected_users = [ConfluenceUser(**user_data) for user_data in overrides]

    confluence_client = OnyxConfluence(
        is_cloud=False,  # Overrides are primarily for Server/DC
        url="http://dummy-confluence.com",
        credentials_provider=mock_provider,
        confluence_user_profiles_override=overrides,
    )

    retrieved_users = list(confluence_client.paginated_cql_user_retrieval())

    assert len(retrieved_users) == len(expected_users)
    # Sort lists by user_id for order-independent comparison
    retrieved_users.sort(key=lambda u: u.user_id)
    expected_users.sort(key=lambda u: u.user_id)
    assert retrieved_users == expected_users


def test_paginated_cql_user_retrieval_no_overrides_server() -> None:
    """
    Tests that paginated_cql_user_retrieval attempts to call the actual
    API pagination when no overrides are provided for Server/DC.
    """
    mock_provider = MockCredentialsProvider()
    confluence_client = OnyxConfluence(
        is_cloud=False,
        url="http://dummy-confluence.com",
        credentials_provider=mock_provider,
        confluence_user_profiles_override=None,
    )

    # Mock the internal pagination method to check if it's called
    with patch.object(confluence_client, "_paginate_url") as mock_paginate:
        mock_paginate.return_value = iter([])  # Return an empty iterator

        list(confluence_client.paginated_cql_user_retrieval())

        mock_paginate.assert_called_once_with("rest/api/user/list", None)


def test_paginated_cql_user_retrieval_no_overrides_cloud() -> None:
    """
    Tests that paginated_cql_user_retrieval attempts to call the actual
    API pagination when no overrides are provided for Cloud.
    """
    mock_provider = MockCredentialsProvider()
    confluence_client = OnyxConfluence(
        is_cloud=True,
        url="http://dummy-confluence.com",  # URL doesn't matter much here due to mocking
        credentials_provider=mock_provider,
        confluence_user_profiles_override=None,
    )

    # Mock the internal pagination method to check if it's called
    with patch.object(confluence_client, "_paginate_url") as mock_paginate:
        mock_paginate.return_value = iter([])  # Return an empty iterator

        list(confluence_client.paginated_cql_user_retrieval())

        # Check that the cloud-specific user search URL is called
        mock_paginate.assert_called_once_with(
            "rest/api/search/user?cql=type=user",
            None,
            force_offset_pagination=True,
        )
