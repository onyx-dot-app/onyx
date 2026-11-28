import json
from unittest.mock import patch

from onyx.access.models import ExternalAccess
from onyx.connectors.models import DocumentBase
from onyx.server.onyx_api import ingestion
from onyx.server.onyx_api.models import IngestionDocument


def test_ingestion_request_round_trips_external_access() -> None:
    request = IngestionDocument(
        document=DocumentBase(
            semantic_identifier="Shared document",
            sections=[],
            metadata={},
            external_access=ExternalAccess(
                external_user_emails=set(),
                external_user_group_ids={"group-1"},
                is_public=False,
            ),
        )
    )

    assert (
        IngestionDocument.model_validate(json.loads(request.model_dump_json()))
        == request
    )


def test_a_failed_chunk_count_does_not_fail_the_ingestion() -> None:
    """The document is already in the primary index when chunks are counted.
    A failed count is logged, so the handler still writes the secondary index."""
    with (
        patch.object(
            ingestion, "record_usage", side_effect=RuntimeError("database down")
        ),
        patch.object(ingestion, "get_session_with_current_tenant"),
        patch.object(ingestion, "logger") as log,
    ):
        ingestion._count_ingested_chunks("tenant_abc", 12)
    log.exception.assert_called_once()


def test_ingested_chunks_are_counted_for_the_tenant() -> None:
    with (
        patch.object(ingestion, "record_usage") as record,
        patch.object(ingestion, "get_session_with_current_tenant"),
    ):
        ingestion._count_ingested_chunks("tenant_abc", 12)
    assert record.call_args.kwargs["amount"] == 12
    assert record.call_args.kwargs["tenant_id"] == "tenant_abc"
