"""The Outlook doc sync hands the connector's permission-aware slim walk to
the shared sync, which turns it into access rows and hides what vanished."""

from unittest.mock import MagicMock, patch

from ee.onyx.external_permissions.outlook.doc_sync import outlook_doc_sync
from onyx.access.models import (
    DocExternalAccess,
    ExternalAccess,
    NodeExternalAccess,
)
from onyx.connectors.models import HierarchyNode, SlimDocument
from onyx.db.enums import HierarchyNodeType

MODULE = "ee.onyx.external_permissions.outlook.doc_sync"

OWNER = ExternalAccess(
    external_user_emails={"alice@contoso.com"},
    external_user_group_ids=set(),
    is_public=False,
)


def _cc_pair() -> MagicMock:
    cc_pair = MagicMock()
    cc_pair.id = 7
    cc_pair.connector.connector_specific_config = {
        "mailboxes": ["alice@contoso.com"],
        "include_calendar": True,
    }
    cc_pair.connector.indexing_start = None
    cc_pair.credential.credential_json.get_value.return_value = {
        "outlook_client_id": "x"
    }
    return cc_pair


def test_doc_sync_yields_the_walk_and_hides_what_it_no_longer_lists() -> None:
    connector = MagicMock()
    connector.retrieve_all_slim_docs_perm_sync.return_value = iter(
        [
            [
                HierarchyNode(
                    raw_node_id="outlook-mailbox:user-1",
                    raw_parent_id=None,
                    display_name="Alice",
                    node_type=HierarchyNodeType.MAILBOX,
                    external_access=OWNER,
                ),
                SlimDocument(id="outlook:user-1:conv-1", external_access=OWNER),
            ]
        ]
    )

    with patch(f"{MODULE}.OutlookConnector", return_value=connector) as factory:
        rows = list(
            outlook_doc_sync(
                _cc_pair(),
                MagicMock(),
                lambda: ["outlook:user-1:conv-1", "outlook:user-1:conv-gone"],
                None,
            )
        )

    factory.assert_called_once_with(
        mailboxes=["alice@contoso.com"], include_calendar=True
    )
    connector.load_credentials.assert_called_once_with({"outlook_client_id": "x"})
    assert rows[0] == NodeExternalAccess(
        external_access=OWNER, raw_node_id="outlook-mailbox:user-1", source="outlook"
    )
    assert rows[1] == DocExternalAccess(
        doc_id="outlook:user-1:conv-1", external_access=OWNER
    )
    # A document the walk no longer lists loses every reader.
    assert rows[2] == DocExternalAccess(
        doc_id="outlook:user-1:conv-gone", external_access=ExternalAccess.empty()
    )
    assert len(rows) == 3
