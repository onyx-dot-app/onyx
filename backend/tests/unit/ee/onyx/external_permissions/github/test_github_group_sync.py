from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from ee.onyx.external_permissions.github.group_sync import github_group_sync
from onyx.db.models import ConnectorCredentialPair


def _cc_pair() -> ConnectorCredentialPair:
    credential_json = MagicMock()
    credential_json.get_value.return_value = {}
    return cast(
        ConnectorCredentialPair,
        SimpleNamespace(
            connector=SimpleNamespace(connector_specific_config={}),
            credential=SimpleNamespace(credential_json=credential_json),
        ),
    )


def test_github_repo_group_sync_failure_is_fatal() -> None:
    connector = MagicMock()
    connector.github_client = object()
    connector.repositories = None
    connector.get_all_repos.return_value = [SimpleNamespace(id=123, name="repo")]

    with (
        patch(
            "ee.onyx.external_permissions.github.group_sync.GithubConnector",
            return_value=connector,
        ),
        patch(
            "ee.onyx.external_permissions.github.group_sync.get_external_user_group",
            side_effect=RuntimeError("repo failed"),
        ),
        pytest.raises(RuntimeError, match="repo failed"),
    ):
        list(
            github_group_sync(
                "tenant",
                _cc_pair(),
                lambda failure: pytest.fail(
                    f"Unexpected group sync failure callback: {failure}"
                ),
            )
        )
