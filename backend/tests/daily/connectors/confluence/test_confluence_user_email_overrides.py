import types
from unittest.mock import patch

import pytest

from onyx.connectors.confluence import source_operations
from onyx.connectors.confluence.models import ConfluenceUser
from onyx.connectors.confluence.source_operations import (
    ConfluenceSourceOperations,
    ConfluenceUserListVariant,
    _OnyxConfluence,
)
from onyx.connectors.interfaces import CredentialsProviderInterface


class MockCredentialsProvider(CredentialsProviderInterface):
    def get_tenant_id(self) -> str:
        return "test_tenant"

    def get_provider_key(self) -> str:
        return "test_provider"

    def is_dynamic(self) -> bool:
        return False

    def get_credentials(self) -> dict[str, str]:
        return {
            "confluence_username": "test_user",
            "confluence_access_token": "test_token",
        }

    def set_credentials(  # ty: ignore[invalid-method-override]
        self, credentials: dict[str, str]
    ) -> None:
        pass

    def __enter__(self) -> "MockCredentialsProvider":
        return self

    def __exit__(  # ty: ignore[invalid-method-override]
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        pass


def _gateway(is_cloud: bool) -> ConfluenceSourceOperations:
    return ConfluenceSourceOperations(
        credentials_provider=MockCredentialsProvider(),
        connector_specific_config={
            "wiki_base": "http://dummy-confluence.com",
            "is_cloud": is_cloud,
        },
    )


def test_list_users_with_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Tests that list_users yields users from the overrides when
    CONFLUENCE_CONNECTOR_USER_PROFILES_OVERRIDE is set and is_cloud is False.
    """
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
    monkeypatch.setattr(
        source_operations, "CONFLUENCE_CONNECTOR_USER_PROFILES_OVERRIDE", overrides
    )

    # Overrides are primarily for Server/DC
    with patch.object(_OnyxConfluence, "_paginate_url") as mock_paginate:
        retrieved_users = list(
            _gateway(is_cloud=False).list_users(variant=ConfluenceUserListVariant.DC)
        )
        mock_paginate.assert_not_called()

    assert len(retrieved_users) == len(expected_users)
    # Sort lists by user_id for order-independent comparison
    retrieved_users.sort(key=lambda u: u.user_id)
    expected_users.sort(key=lambda u: u.user_id)
    assert retrieved_users == expected_users


def test_list_users_no_overrides_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Tests that list_users calls the DC user list when no overrides are set.
    """
    monkeypatch.setattr(
        source_operations, "CONFLUENCE_CONNECTOR_USER_PROFILES_OVERRIDE", None
    )

    # Mock the internal pagination method to check if it's called
    with patch.object(_OnyxConfluence, "_paginate_url") as mock_paginate:
        mock_paginate.return_value = iter([])  # Return an empty iterator

        list(_gateway(is_cloud=False).list_users(variant=ConfluenceUserListVariant.DC))

        mock_paginate.assert_called_once_with("rest/api/user/list", None)


def test_list_users_no_overrides_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Tests that list_users calls the Cloud user search when no overrides are set.
    """
    monkeypatch.setattr(
        source_operations, "CONFLUENCE_CONNECTOR_USER_PROFILES_OVERRIDE", None
    )

    # Mock the internal pagination method to check if it's called
    with patch.object(_OnyxConfluence, "_paginate_url") as mock_paginate:
        mock_paginate.return_value = iter([])  # Return an empty iterator

        list(
            _gateway(is_cloud=True).list_users(variant=ConfluenceUserListVariant.CLOUD)
        )

        # Check that the cloud-specific user search URL is called
        mock_paginate.assert_called_once_with(
            "rest/api/search/user?cql=type=user",
            None,
            force_offset_pagination=True,
        )
