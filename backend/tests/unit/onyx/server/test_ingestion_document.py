import json

from onyx.access.models import ExternalAccess
from onyx.connectors.models import DocumentBase
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
