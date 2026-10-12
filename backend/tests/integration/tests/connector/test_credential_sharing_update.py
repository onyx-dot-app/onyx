"""A saved credential's name and sharing change without touching its values,
owner or check-result key."""

import os
from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser


def _listed_credential(credential_id: int, user: DATestUser) -> dict[str, Any]:
    response = client.get(
        f"{API_SERVER_URL}/manage/admin/similar-credentials/"
        f"{DocumentSource.SLACK.value}",
        headers=user.headers,
    )
    response.raise_for_status()
    return next(
        credential
        for credential in response.json()
        if credential["id"] == credential_id
    )


def test_rename_keeps_values_owner_and_time_updated(admin_user: DATestUser) -> None:
    # Precondition.
    credential = CredentialManager.create(
        user_performing_action=admin_user,
        source=DocumentSource.SLACK,
        credential_json={"slack_bot_token": "fake-bot-token"},
    )
    before = _listed_credential(credential.id, admin_user)

    # Under test.
    CredentialManager.update_sharing(
        credential.id, admin_user, admin_public=False, name="Renamed"
    )

    # Postcondition.
    after = _listed_credential(credential.id, admin_user)
    assert after["name"] == "Renamed"
    assert after["admin_public"] is False
    assert after["credential_json"] == before["credential_json"]
    assert after["user_id"] == before["user_id"]
    assert after["time_updated"] == before["time_updated"]


@pytest.mark.skipif(
    os.environ.get("RUN_EE_TESTS", "").lower() != "true",
    reason="User group tests are enterprise only",
)
def test_groups_are_replaced_and_listed(admin_user: DATestUser) -> None:
    # Precondition.
    first = UserGroupManager.create(user_performing_action=admin_user)
    second = UserGroupManager.create(user_performing_action=admin_user)
    credential = CredentialManager.create(
        user_performing_action=admin_user,
        source=DocumentSource.SLACK,
        credential_json={"slack_bot_token": "fake-bot-token"},
        groups=[first.id],
    )
    assert _listed_credential(credential.id, admin_user)["groups"] == [first.id]

    # Under test.
    updated = CredentialManager.update_sharing(
        credential.id, admin_user, admin_public=True, groups=[second.id]
    )

    # Postcondition.
    assert updated.groups == [second.id]
    assert _listed_credential(credential.id, admin_user)["groups"] == [second.id]
