"""The Zoom doc sync hands the connector's permission-aware walk to the shared
sync, which turns it into access rows and hides what the walk no longer lists."""

from unittest.mock import MagicMock, patch

from ee.onyx.configs.app_configs import ZOOM_PERMISSION_DOC_SYNC_FREQUENCY
from ee.onyx.external_permissions.sync_params import (
    get_source_perm_sync_config,
    mock_doc_sync,
)
from ee.onyx.external_permissions.zoom.doc_sync import zoom_doc_sync
from onyx.access.models import DocExternalAccess, ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import SlimDocument

MODULE = "ee.onyx.external_permissions.zoom.doc_sync"

OWNER = ExternalAccess(
    external_user_emails={"owner@example.com"},
    external_user_group_ids=set(),
    is_public=False,
)


def _cc_pair() -> MagicMock:
    cc_pair = MagicMock()
    cc_pair.id = 7
    cc_pair.connector.connector_specific_config = {"host_emails": ["owner@example.com"]}
    cc_pair.connector.indexing_start = None
    cc_pair.credential.credential_json.get_value.return_value = {
        "zoom_account_id": "acct"
    }
    return cc_pair


def test_the_walk_becomes_access_rows_and_unlisted_documents_go_private() -> None:
    connector = MagicMock()
    connector.retrieve_all_slim_docs_perm_sync.return_value = iter(
        [
            [
                SlimDocument(id="ZOOM_MEETING_uuid-1", external_access=OWNER),
                SlimDocument(
                    id="ZOOM_MEETING_uuid-2", external_access=ExternalAccess.empty()
                ),
            ]
        ]
    )

    with patch(f"{MODULE}.ZoomConnector", return_value=connector) as factory:
        rows = list(
            zoom_doc_sync(
                _cc_pair(),
                MagicMock(),
                lambda: [
                    "ZOOM_MEETING_uuid-1",
                    "ZOOM_MEETING_uuid-2",
                    "ZOOM_MEETING_gone",
                ],
                None,
            )
        )

    factory.assert_called_once_with(host_emails=["owner@example.com"])
    connector.load_credentials.assert_called_once_with({"zoom_account_id": "acct"})
    assert rows == [
        DocExternalAccess(doc_id="ZOOM_MEETING_uuid-1", external_access=OWNER),
        DocExternalAccess(
            doc_id="ZOOM_MEETING_uuid-2", external_access=ExternalAccess.empty()
        ),
        DocExternalAccess(
            doc_id="ZOOM_MEETING_gone", external_access=ExternalAccess.empty()
        ),
    ]


def test_zoom_is_registered_with_a_real_doc_sync() -> None:
    config = get_source_perm_sync_config(DocumentSource.ZOOM)
    assert config is not None and config.doc_sync_config is not None
    assert config.doc_sync_config.doc_sync_func is not mock_doc_sync
    assert (
        config.doc_sync_config.doc_sync_frequency == ZOOM_PERMISSION_DOC_SYNC_FREQUENCY
    )
