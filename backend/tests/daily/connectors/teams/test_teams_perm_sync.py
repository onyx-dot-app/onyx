"""Tests for Teams connector permission sync via load_from_checkpoint_with_perm_sync.

This tests the CheckpointedConnectorWithPermSync interface implementation.
"""

import os
import time
from collections.abc import Generator

import pytest

from onyx.connectors.models import Document
from onyx.connectors.teams.connector import TeamsConnector
from onyx.utils.variable_functionality import global_version
from tests.daily.connectors.utils import load_everything_from_checkpoint_connector


@pytest.fixture(autouse=True)
def set_ee_on() -> Generator[None, None, None]:
    """Need EE to be enabled for these tests to work since
    perm syncing is an EE-only feature."""
    global_version.set_ee()

    yield

    global_version._is_ee = False


@pytest.fixture
def teams_credentials() -> dict[str, str]:
    app_id = os.environ["TEAMS_APPLICATION_ID"]
    dir_id = os.environ["TEAMS_DIRECTORY_ID"]
    secret = os.environ["TEAMS_SECRET"]

    return {
        "teams_client_id": app_id,
        "teams_directory_id": dir_id,
        "teams_client_secret": secret,
    }


@pytest.fixture
def teams_connector(
    teams_credentials: dict[str, str],
) -> TeamsConnector:
    teams_connector = TeamsConnector(teams=["Onyx-Testing"])
    teams_connector.load_credentials(teams_credentials)
    return teams_connector


def test_load_from_checkpoint_with_perm_sync(
    teams_connector: TeamsConnector,
) -> None:
    """Test that load_from_checkpoint_with_perm_sync returns documents with external_access.

    This verifies the CheckpointedConnectorWithPermSync interface is properly implemented.
    """
    docs = load_everything_from_checkpoint_connector(
        connector=teams_connector,
        start=0.0,
        end=time.time(),
        include_permissions=True,  # Uses load_from_checkpoint_with_perm_sync
    )

    documents = [doc for doc in docs if isinstance(doc, Document)]

    # We should have at least some documents
    assert len(documents) > 0, "Expected to find at least one document"

    for doc in documents:
        assert (
            doc.external_access is not None
        ), f"Document {doc.id} should have external_access when using perm sync"

        # Verify external_access structure is valid
        if doc.external_access.is_public:
            # Public channels should have empty user emails
            assert (
                doc.external_access.external_user_emails == set()
            ), f"Public channel doc {doc.id} should have empty external_user_emails"
        else:
            # Private channels should have at least one user email
            assert (
                doc.external_access.external_user_emails
            ), f"Private channel doc {doc.id} should have external_user_emails"

        # Teams doesn't use group IDs
        assert (
            doc.external_access.external_user_group_ids == set()
        ), f"Document {doc.id} should have empty external_user_group_ids for Teams"
