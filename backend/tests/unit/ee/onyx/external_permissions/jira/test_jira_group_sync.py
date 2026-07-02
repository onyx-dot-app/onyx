from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from jira.exceptions import JIRAError

from ee.onyx.db.external_perm import ExternalGroupSyncFailure
from ee.onyx.external_permissions.jira.group_sync import jira_group_sync
from onyx.db.models import ConnectorCredentialPair


def _cc_pair() -> ConnectorCredentialPair:
    credential_json = MagicMock()
    credential_json.get_value.return_value = {"jira_api_token": "token"}
    return cast(
        ConnectorCredentialPair,
        SimpleNamespace(
            id=1,
            connector=SimpleNamespace(
                connector_specific_config={
                    "jira_base_url": "https://example.atlassian.net",
                    "scoped_token": False,
                }
            ),
            credential=SimpleNamespace(credential_json=credential_json),
        ),
    )


def test_jira_group_sync_yields_group_level_failure_for_member_fetch_error() -> None:
    jira_client = MagicMock()
    jira_client.groups.return_value = ["jira-users", "stale-group"]

    def get_json(path: str, params: dict[str, object]) -> dict[str, object]:
        assert path == "group/member"
        if params["groupname"] == "stale-group":
            raise JIRAError("group missing", status_code=404)
        return {
            "values": [
                {
                    "accountType": "atlassian",
                    "emailAddress": "user@example.com",
                }
            ],
            "isLast": True,
        }

    jira_client._get_json.side_effect = get_json

    failures: list[ExternalGroupSyncFailure] = []
    with patch(
        "ee.onyx.external_permissions.jira.group_sync.build_jira_client",
        return_value=jira_client,
    ):
        results = list(jira_group_sync("tenant", _cc_pair(), failures.append))

    assert len(results) == 1
    assert results[0].id == "jira-users"
    assert results[0].user_emails == ["user@example.com"]

    assert len(failures) == 1
    assert failures[0].external_group_id == "stale-group"
    assert failures[0].external_group_name == "stale-group"
    assert "GET /group/member could not find it" in failures[0].failure_message
    assert failures[0].full_exception_trace is not None


def test_jira_group_sync_keeps_group_listing_failure_fatal() -> None:
    jira_client = MagicMock()
    jira_client.groups.side_effect = RuntimeError("group listing failed")

    with patch(
        "ee.onyx.external_permissions.jira.group_sync.build_jira_client",
        return_value=jira_client,
    ):
        with pytest.raises(RuntimeError, match="group listing failed"):
            list(jira_group_sync("tenant", _cc_pair(), lambda _failure: None))
