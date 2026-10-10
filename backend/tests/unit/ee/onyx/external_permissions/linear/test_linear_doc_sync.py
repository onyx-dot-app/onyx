"""The Linear doc sync feeds the connector's permission-aware walk to the
shared sync, which turns it into access rows and hides what the walk no
longer lists, on the DB credential provider shared with indexing."""

from unittest.mock import MagicMock, patch

from ee.onyx.configs.app_configs import LINEAR_PERMISSION_DOC_SYNC_FREQUENCY
from ee.onyx.external_permissions.linear.doc_sync import linear_doc_sync
from ee.onyx.external_permissions.sync_params import get_source_perm_sync_config
from onyx.access.models import DocExternalAccess, ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import SlimDocument

CONNECTOR = "ee.onyx.external_permissions.linear.connector"

TEAM = ExternalAccess(
    external_user_emails=set(), external_user_group_ids={"team-1"}, is_public=False
)


def _cc_pair() -> MagicMock:
    cc_pair = MagicMock()
    cc_pair.id = 7
    cc_pair.connector.source = DocumentSource.LINEAR
    cc_pair.connector.connector_specific_config = {"team_keys": ["ENG"]}
    cc_pair.connector.indexing_start = None
    cc_pair.credential.id = 3
    return cc_pair


def test_the_walk_becomes_access_rows_and_unlisted_issues_go_private() -> None:
    connector = MagicMock()
    connector.retrieve_all_slim_docs_perm_sync.return_value = iter(
        [[SlimDocument(id="issue-1", external_access=TEAM)]]
    )
    provider = MagicMock()

    with (
        patch(f"{CONNECTOR}.LinearConnector", return_value=connector) as factory,
        patch(f"{CONNECTOR}.build_db_credentials_provider", return_value=provider),
    ):
        rows = list(
            linear_doc_sync(_cc_pair(), MagicMock(), lambda: ["issue-1", "gone"], None)
        )

    factory.assert_called_once_with(team_keys=["ENG"])
    connector.set_credentials_provider.assert_called_once_with(provider)
    assert rows == [
        DocExternalAccess(doc_id="issue-1", external_access=TEAM),
        DocExternalAccess(doc_id="gone", external_access=ExternalAccess.empty()),
    ]


def test_linear_is_registered_for_doc_sync_without_waiting_for_an_index() -> None:
    config = get_source_perm_sync_config(DocumentSource.LINEAR)
    assert config is not None and config.doc_sync_config is not None
    assert (
        config.doc_sync_config.doc_sync_frequency
        == LINEAR_PERMISSION_DOC_SYNC_FREQUENCY
    )
    # Indexing never carries access here, so the sync must not wait for it.
    assert config.doc_sync_config.initial_index_should_sync is False
