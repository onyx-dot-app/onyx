"""A slim walk that misses a whole entity must not make its documents private."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

from ee.onyx.external_permissions.utils import generic_doc_sync
from onyx.access.models import DocExternalAccess, ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import (
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnectorWithPermSync,
    SlimInventoryGaps,
)
from onyx.connectors.models import InventoryGap, SlimDocument
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface

READER = ExternalAccess(
    external_user_emails={"ada@example.com"},
    external_user_group_ids=set(),
    is_public=False,
)


class _Walk(SlimConnectorWithPermSync, SlimInventoryGaps):
    """Lists one document, and misses one entity when ``gaps`` says so."""

    def __init__(self, gaps: list[str]) -> None:
        self.gaps = gaps

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:  # noqa: ARG002
        return None

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,  # noqa: ARG002
    ) -> GenerateSlimDocumentOutput:
        yield [SlimDocument(id="listed", external_access=READER)]

    def inventory_gaps(self) -> list[InventoryGap]:
        return [
            InventoryGap(entity_id=entity_id, document_id_prefix="gapped:")
            for entity_id in self.gaps
        ]


def _sync(gaps: list[str]) -> Iterator[Any]:
    cc_pair = MagicMock(spec=ConnectorCredentialPair)
    cc_pair.id = 1
    cc_pair.connector.indexing_start = None
    return generic_doc_sync(
        cc_pair=cc_pair,
        fetch_all_existing_docs_ids_fn=lambda: ["listed", "gapped:1", "unseen"],
        callback=None,
        doc_source=DocumentSource.TEAMS,
        slim_connector=_Walk(gaps),
        label="doc_sync",
    )


def test_a_gap_leaves_only_the_documents_it_covers_alone() -> None:
    access = list(_sync(["entity-1"]))

    emptied = [
        item.doc_id
        for item in access
        if isinstance(item, DocExternalAccess)
        and not item.external_access.external_user_emails
    ]
    assert emptied == ["unseen"]


def test_without_a_gap_every_missing_document_loses_its_access() -> None:
    access = list(_sync([]))

    emptied = sorted(
        item.doc_id
        for item in access
        if isinstance(item, DocExternalAccess)
        and not item.external_access.external_user_emails
    )
    assert emptied == ["gapped:1", "unseen"]
