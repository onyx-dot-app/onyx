"""The Linear doc sync feeds the connector's permission-aware walk to the
shared sync, which turns it into access rows and hides what the walk no
longer lists, and stores a credential refreshed on load."""

from unittest.mock import MagicMock, patch

from ee.onyx.configs.app_configs import LINEAR_PERMISSION_DOC_SYNC_FREQUENCY
from ee.onyx.external_permissions.linear.doc_sync import linear_doc_sync
from ee.onyx.external_permissions.sync_params import get_source_perm_sync_config
from onyx.access.models import DocExternalAccess, ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import SlimDocument

MODULE = "ee.onyx.external_permissions.linear.connector"
UTILS = "ee.onyx.external_permissions.utils"

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


def _credential() -> MagicMock:
    credential = MagicMock()
    credential.credential_json.get_value.return_value = {
        "linear_api_key": "lin_api_test"
    }
    return credential


def _session() -> MagicMock:
    session = MagicMock()
    session.__enter__.return_value = session
    return session


def test_the_walk_becomes_access_rows_and_unlisted_issues_go_private() -> None:
    connector = MagicMock()
    connector.load_credentials.return_value = None
    connector.retrieve_all_slim_docs_perm_sync.return_value = iter(
        [[SlimDocument(id="issue-1", external_access=TEAM)]]
    )

    with (
        patch(f"{MODULE}.LinearConnector", return_value=connector) as factory,
        patch(f"{UTILS}.get_session_with_current_tenant", return_value=_session()),
        patch(f"{UTILS}.fetch_credential_by_id_for_update", return_value=_credential()),
        patch(f"{UTILS}.backend_update_credential_json") as store,
    ):
        rows = list(
            linear_doc_sync(_cc_pair(), MagicMock(), lambda: ["issue-1", "gone"], None)
        )

    store.assert_not_called()

    factory.assert_called_once_with(team_keys=["ENG"])
    connector.load_credentials.assert_called_once_with(
        {"linear_api_key": "lin_api_test"}
    )
    assert rows == [
        DocExternalAccess(doc_id="issue-1", external_access=TEAM),
        DocExternalAccess(doc_id="gone", external_access=ExternalAccess.empty()),
    ]


def test_a_refreshed_credential_is_stored_for_the_next_run() -> None:
    connector = MagicMock()
    connector.load_credentials.return_value = {"access_token": "fresh"}
    connector.retrieve_all_slim_docs_perm_sync.return_value = iter([])
    credential = _credential()
    session = _session()

    with (
        patch(f"{MODULE}.LinearConnector", return_value=connector),
        patch(f"{UTILS}.get_session_with_current_tenant", return_value=session),
        patch(
            f"{UTILS}.fetch_credential_by_id_for_update", return_value=credential
        ) as fetch,
        patch(f"{UTILS}.backend_update_credential_json") as store,
    ):
        list(linear_doc_sync(_cc_pair(), MagicMock(), list, None))

    # The row stays locked from the read through the refresh write.
    fetch.assert_called_once_with(3, session)
    connector.load_credentials.assert_called_once_with(
        {"linear_api_key": "lin_api_test"}
    )
    store.assert_called_once_with(
        credential, DocumentSource.LINEAR, {"access_token": "fresh"}, session
    )


def test_linear_is_registered_for_doc_sync_after_the_first_index() -> None:
    config = get_source_perm_sync_config(DocumentSource.LINEAR)
    assert config is not None and config.doc_sync_config is not None
    assert (
        config.doc_sync_config.doc_sync_frequency
        == LINEAR_PERMISSION_DOC_SYNC_FREQUENCY
    )
    # Indexing never carries access here, so the sync must not wait for it.
    assert config.doc_sync_config.initial_index_should_sync is False
