"""Verifies the Zoom access list survives the trip into Postgres.

The unit tests prove the connector builds the right set of emails. This proves
the value that reaches the database is the same one, on the columns the search
filter reads: `external_user_emails`, `external_user_group_ids` and `is_public`.
A connector can build a perfect access list and still be wrong here, because the
upsert only writes the permission columns when a document in the batch carries
them.

Zoom itself is mocked; Postgres is real.
"""

from collections.abc import Generator
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.models import Document, IndexAttemptMetadata
from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.connector import ZoomConnector, ZoomConnectorCheckpoint
from onyx.connectors.zoom.models import (
    ZoomInvitee,
    ZoomParticipant,
    ZoomRegistrant,
    ZoomSessionOccurrence,
    ZoomTranscript,
)
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_pipeline import _upsert_documents_in_db
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    get_doc_row,
    make_cc_pair,
)

_ZOOM_CREDS = {
    "zoom_account_id": "test-account",
    "zoom_client_id": "test-client-id",
    "zoom_client_secret": "test-client-secret",
}

_SAMPLE_VTT = """WEBVTT

1
00:00:00.000 --> 00:00:02.500
Jane Doe: Hello everyone.
"""


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session, source=DocumentSource.ZOOM)
    try:
        yield pair
    finally:
        cleanup_cc_pair(db_session, pair)


def _zoom_documents(meeting_id: str) -> list[Document]:
    """Runs the real connector over a mocked Zoom account and returns what it
    would hand the indexing pipeline."""
    connector = ZoomConnector(meeting_ids=[meeting_id])
    connector.load_credentials(_ZOOM_CREDS)

    client = MagicMock(spec=ZoomClient)
    client.list_past_meeting_occurrences.return_value = [
        ZoomSessionOccurrence(
            uuid=f"uuid-{meeting_id}", start_time="2026-01-15T10:00:00Z"
        )
    ]
    client.get_meeting_transcript.return_value = ZoomTranscript(
        download_url="https://zoom.us/rec/download/t.vtt", meeting_topic="Weekly Sync"
    )
    client.download_transcript_vtt.return_value = _SAMPLE_VTT
    client.list_past_meeting_participants.return_value = [
        ZoomParticipant(user_email="attended@example.com"),
        # Zoom blanks the email of anyone outside the host's account.
        ZoomParticipant(user_email=""),
    ]
    client.list_meeting_registrants.return_value = [
        ZoomRegistrant(email="approved@example.com", status="approved"),
        ZoomRegistrant(email="cancelled@example.com", status="denied"),
    ]
    client.list_meeting_invitees.return_value = [
        ZoomInvitee(email="invited@example.com")
    ]
    connector.client = client

    documents: list[Document] = []
    checkpoint = connector.build_dummy_checkpoint()
    while checkpoint.has_more:
        generator = CheckpointOutputWrapper[ZoomConnectorCheckpoint]()(
            connector.load_from_checkpoint_with_perm_sync(0, 2_000_000_000, checkpoint)
        )
        for document, _hierarchy, _failure, next_checkpoint in generator:
            if document is not None:
                documents.append(document)
            if next_checkpoint is not None:
                checkpoint = next_checkpoint
    return documents


class TestZoomAccessListReachesPostgres:
    def test_the_access_list_is_persisted(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
    ) -> None:
        meeting_id = uuid4().hex[:8]
        documents = _zoom_documents(meeting_id)
        assert len(documents) == 1

        _upsert_documents_in_db(
            documents=documents,
            index_attempt_metadata=IndexAttemptMetadata(
                connector_id=cc_pair.connector_id,
                credential_id=cc_pair.credential_id,
                attempt_id=None,
                request_id="zoom-access-test",
            ),
            db_session=db_session,
        )
        db_session.commit()

        row = get_doc_row(db_session, documents[0].id)

        assert row is not None
        assert set(row.external_user_emails or []) == {
            "attended@example.com",
            "approved@example.com",
            "invited@example.com",
        }
        # Zoom cannot grant a session to a Group, so this stays empty on purpose.
        assert list(row.external_user_group_ids or []) == []
        assert row.is_public is False
