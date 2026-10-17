"""The HubSpot doc sync hands the connector's permission walk to the shared
sync, which turns it into access rows and hides what the walk no longer lists."""

from unittest.mock import MagicMock, patch

from ee.onyx.configs.app_configs import HUBSPOT_PERMISSION_DOC_SYNC_FREQUENCY
from ee.onyx.external_permissions.hubspot.doc_sync import hubspot_doc_sync
from ee.onyx.external_permissions.sync_params import get_source_perm_sync_config
from onyx.access.models import DocExternalAccess, ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import SlimDocument

MODULE = "ee.onyx.external_permissions.hubspot.doc_sync"

VIEWERS = ExternalAccess(
    external_user_emails={"rep@example.com"},
    external_user_group_ids=set(),
    is_public=False,
)


def _cc_pair() -> MagicMock:
    cc_pair = MagicMock()
    cc_pair.id = 7
    cc_pair.connector.source = DocumentSource.HUBSPOT
    cc_pair.connector.connector_specific_config = {"object_types": ["deals"]}
    cc_pair.connector.indexing_start = None
    cc_pair.credential.credential_json.get_value.return_value = {
        "hubspot_access_token": "token"
    }
    return cc_pair


def test_the_walk_becomes_access_rows_and_unlisted_documents_go_private() -> None:
    connector = MagicMock()
    connector.retrieve_all_slim_docs_perm_sync.return_value = iter(
        [
            [
                SlimDocument(id="hubspot_deal_1", external_access=VIEWERS),
                SlimDocument(
                    id="hubspot_deal_2", external_access=ExternalAccess.empty()
                ),
            ]
        ]
    )

    with patch(f"{MODULE}.HubSpotConnector", return_value=connector) as factory:
        rows = list(
            hubspot_doc_sync(
                _cc_pair(),
                MagicMock(),
                lambda: ["hubspot_deal_1", "hubspot_deal_2", "hubspot_deal_gone"],
                None,
            )
        )

    assert factory.call_args.kwargs["object_types"] == ["deals"]
    connector.load_credentials.assert_called_once_with(
        {"hubspot_access_token": "token"}
    )
    assert rows == [
        DocExternalAccess(doc_id="hubspot_deal_1", external_access=VIEWERS),
        DocExternalAccess(
            doc_id="hubspot_deal_2", external_access=ExternalAccess.empty()
        ),
        DocExternalAccess(
            doc_id="hubspot_deal_gone", external_access=ExternalAccess.empty()
        ),
    ]


def test_hubspot_is_registered_with_a_doc_sync_and_no_group_sync() -> None:
    config = get_source_perm_sync_config(DocumentSource.HUBSPOT)
    assert config is not None and config.doc_sync_config is not None
    assert config.group_sync_config is None
    # Indexing is not checkpointed, so the first sync must wait for the doc sync.
    assert config.doc_sync_config.initial_index_should_sync is False
    assert (
        config.doc_sync_config.doc_sync_frequency
        == HUBSPOT_PERMISSION_DOC_SYNC_FREQUENCY
    )
    cc_pair, fetch_docs, fetch_ids = MagicMock(), MagicMock(), MagicMock()

    # The registry holds a lazy wrapper, so call it to see its target.
    with patch(f"{MODULE}.hubspot_doc_sync") as doc_sync:
        config.doc_sync_config.doc_sync_func(cc_pair, fetch_docs, fetch_ids, None)

    doc_sync.assert_called_once_with(cc_pair, fetch_docs, fetch_ids, None)
