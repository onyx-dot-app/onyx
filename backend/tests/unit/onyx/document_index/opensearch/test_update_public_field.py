"""`update()` has to write the `public` field alongside the ACL.

Whether a chunk is public lives only in `PUBLIC_FIELD_NAME`:
`generate_opensearch_filtered_access_control_list` deliberately drops
`PUBLIC_DOC_PAT` from `access_control_list` because the schema stores it
separately. The search filter is `should: [term public:true, terms acl:<user
acl>]`, so the two are halves of one access state and have to move together.

Reported in #14981: `update()` wrote only the ACL half, so an access change that
came with no re-indexing never reached the index. A document going PUBLIC ->
PRIVATE kept `public: true` and stayed searchable by everyone, while Postgres
reported it private.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.access.models import DocumentAccess
from onyx.configs.constants import PUBLIC_DOC_PAT
from onyx.document_index.interfaces_new import MetadataUpdateRequest, TenantState
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.schema import (
    ACCESS_CONTROL_LIST_FIELD_NAME,
    PUBLIC_FIELD_NAME,
)
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA


def _make_index() -> tuple[OpenSearchDocumentIndex, MagicMock]:
    idx = OpenSearchDocumentIndex.__new__(OpenSearchDocumentIndex)
    client = MagicMock()
    idx._client = client
    idx._tenant_state = TenantState(
        tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False
    )
    idx._index_name = "test-index"
    return idx, client


def _access(is_public: bool) -> DocumentAccess:
    return DocumentAccess.build(
        user_emails=["someone@example.com"],
        user_groups=[],
        external_user_emails=[],
        external_user_group_ids=[],
        is_public=is_public,
    )


def _written_properties(client: MagicMock) -> dict[str, Any]:
    assert client.bulk_update_documents.call_count == 1
    return client.bulk_update_documents.call_args.kwargs["properties_to_update"]


def _update(idx: OpenSearchDocumentIndex, access: DocumentAccess) -> None:
    idx.update(
        [
            MetadataUpdateRequest(
                document_ids=["doc-1"],
                doc_id_to_chunk_cnt={"doc-1": 1},
                access=access,
            )
        ]
    )


@pytest.mark.parametrize("is_public", [True, False])
def test_update_writes_the_public_field(is_public: bool) -> None:
    idx, client = _make_index()

    _update(idx, _access(is_public=is_public))

    properties = _written_properties(client)
    assert PUBLIC_FIELD_NAME in properties, (
        "update() wrote the ACL without the public flag, so an access change "
        "that does not re-index the content never reaches the index"
    )
    assert properties[PUBLIC_FIELD_NAME] is is_public


def test_public_to_private_does_not_leave_the_chunk_searchable() -> None:
    # The leak in #14981: the filter matches `public: true` on its own, so a
    # stale true keeps the chunk readable by every user regardless of the ACL.
    idx, client = _make_index()

    _update(idx, _access(is_public=False))

    assert _written_properties(client)[PUBLIC_FIELD_NAME] is False


def test_public_stays_out_of_the_access_control_list() -> None:
    # The two halves must not both carry it, or the ACL filter would grant
    # access on a value the schema keeps in its own field.
    idx, client = _make_index()

    _update(idx, _access(is_public=True))

    properties = _written_properties(client)
    assert PUBLIC_DOC_PAT not in properties[ACCESS_CONTROL_LIST_FIELD_NAME]


def test_requests_without_access_do_not_touch_public() -> None:
    # A boost-only sync must not assert anything about access.
    idx, client = _make_index()

    idx.update(
        [
            MetadataUpdateRequest(
                document_ids=["doc-1"], doc_id_to_chunk_cnt={"doc-1": 1}, boost=1
            )
        ]
    )

    assert PUBLIC_FIELD_NAME not in _written_properties(client)
