from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from ee.onyx.external_permissions.jira.doc_sync import jira_doc_sync
from onyx.connectors.jira.connector import JiraConnector
from onyx.db.models import ConnectorCredentialPair


@pytest.fixture
def mock_jira_cc_pair(
    jira_base_url: str,
    project_key: str,
    user_email: str,
    mock_jira_api_token: str,
) -> MagicMock:
    mock_cc_pair = MagicMock(spec=ConnectorCredentialPair)
    mock_cc_pair.connector = MagicMock()
    mock_cc_pair.credential.credential_json = {
        "jira_user_email": user_email,
        "jira_api_token": mock_jira_api_token,
    }
    mock_cc_pair.connector.connector_specific_config = {
        "jira_base_url": jira_base_url,
        "project_key": project_key,
    }

    return mock_cc_pair


@pytest.fixture
def mock_fetch_all_existing_docs_fn() -> MagicMock:
    return MagicMock(return_value=[])


def test_jira_permission_sync(
    jira_connector: JiraConnector,
    mock_jira_cc_pair: MagicMock,
    mock_fetch_all_existing_docs_fn: MagicMock,
) -> None:
    with patch("onyx.connectors.jira.connector.build_jira_client") as mock_build_client:
        mock_build_client.return_value = jira_connector._jira_client

        for doc in jira_doc_sync(
            cc_pair=mock_jira_cc_pair,
            fetch_all_existing_docs_fn=mock_fetch_all_existing_docs_fn,
        ):
            print(doc)
