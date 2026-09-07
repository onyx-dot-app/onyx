"""This runs the same way for every discovery mechanism and session type.
Anything that differs between meetings and webinars belongs on the
SessionTypeHandler, not in a branch here.
"""

from collections.abc import Generator

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    TextSection,
)
from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.recordings.access import zoom_access_resolver
from onyx.connectors.zoom.recordings.models import (
    OccurrenceWork,
    ZoomSessionType,
    fails_the_whole_run,
    parse_zoom_datetime,
)
from onyx.connectors.zoom.recordings.session_types import get_session_type_handler
from onyx.connectors.zoom.recordings.vtt import parse_vtt_transcript
from onyx.utils.logger import setup_logger

logger = setup_logger()


_DOCUMENT_ID_PREFIX = "ZOOM"


# The session type is baked into the id because a targeted reindex is handed
# document ids and nothing else, and it has to know which endpoints to call
# to rebuild the document. Changing this scheme later orphans everything
# already indexed, so it carries the type from the start.
def zoom_document_id(session_type: ZoomSessionType, occurrence_uuid: str) -> str:
    return f"{_DOCUMENT_ID_PREFIX}_{session_type.value.upper()}_{occurrence_uuid}"


def parse_zoom_document_id(document_id: str) -> tuple[ZoomSessionType, str] | None:
    """A Zoom occurrence uuid is base64 and can contain an underscore of its
    own, so splitting any further hands back a truncated uuid that resolves to
    nothing.
    """
    parts = document_id.split("_", 2)
    if len(parts) != 3 or parts[0] != _DOCUMENT_ID_PREFIX or not parts[2]:
        return None
    try:
        session_type = ZoomSessionType(parts[1].lower())
    except ValueError:
        return None
    return session_type, parts[2]


def process_occurrence(
    client: ZoomClient, work: OccurrenceWork, *, include_access: bool
) -> Generator[Document | ConnectorFailure, None, None]:
    handler = get_session_type_handler(work.session_type)
    occurrence_uuid = work.occurrence_uuid

    try:
        transcript = client.get_meeting_transcript(occurrence_uuid)
    except Exception as e:
        if fails_the_whole_run(e):
            raise
        logger.exception(
            "Failed to fetch Zoom transcript for session %s occurrence %s",
            work.session_id,
            occurrence_uuid,
        )
        yield ConnectorFailure(
            failed_document=DocumentFailure(
                document_id=zoom_document_id(work.session_type, occurrence_uuid)
            ),
            failure_message=f"Failed to fetch transcript for Zoom session {work.session_id} occurrence {occurrence_uuid}: {e}",
            exception=e,
        )
        return

    if transcript is None:
        logger.info(
            "Zoom session %s occurrence %s was never cloud-recorded; skipping",
            work.session_id,
            occurrence_uuid,
        )
        return

    download_url = transcript.download_url
    if not transcript.is_downloadable or not download_url:
        if transcript.download_restriction_reason == "NOT_READY":
            logger.info(
                "Zoom transcript for session %s occurrence %s isn't ready yet; "
                "will pick it up on a future sync",
                work.session_id,
                occurrence_uuid,
            )
        else:
            logger.warning(
                "Zoom transcript for session %s occurrence %s can't be downloaded "
                "(restriction=%s, can_download=%s, has_url=%s); skipping",
                work.session_id,
                occurrence_uuid,
                transcript.download_restriction_reason,
                transcript.can_download,
                bool(download_url),
            )
        return

    try:
        vtt_content = client.download_transcript_vtt(download_url)
    except Exception as e:
        if fails_the_whole_run(e):
            raise
        logger.exception(
            "Failed to download Zoom transcript for session %s occurrence %s",
            work.session_id,
            occurrence_uuid,
        )
        yield ConnectorFailure(
            failed_document=DocumentFailure(
                document_id=zoom_document_id(work.session_type, occurrence_uuid)
            ),
            failure_message=f"Failed to download transcript for Zoom session {work.session_id} occurrence {occurrence_uuid}: {e}",
            exception=e,
        )
        return

    transcript_text = parse_vtt_transcript(vtt_content)
    if not transcript_text:
        logger.warning(
            "Zoom transcript for session %s occurrence %s was empty after "
            "parsing; skipping",
            work.session_id,
            occurrence_uuid,
        )
        return

    # Zoom caps the details endpoint below at one year, so a title taken from
    # here is the only one an older meeting gets.
    topic = work.topic or transcript.meeting_topic
    started_at = work.start_time
    if not topic or not started_at:
        try:
            details = handler.get_occurrence_details(client, occurrence_uuid)
            topic = topic or details.topic
            started_at = started_at or details.start_time
        except Exception:
            # The transcript is already downloaded, so a missing title or
            # timestamp isn't worth throwing away an indexable document.
            logger.warning(
                "Couldn't fetch Zoom details for session %s occurrence %s; "
                "indexing with what discovery already gave us",
                work.session_id,
                occurrence_uuid,
            )
    topic = topic or f"Zoom {work.session_type.value.capitalize()} {work.session_id}"
    occurrence_time = parse_zoom_datetime(started_at)

    # Resolved last so a session with nothing to index never pays for the extra
    # calls. Failing the document beats indexing it with an access list we know
    # is wrong, and a targeted reindex can come back for it later.
    try:
        external_access = (
            zoom_access_resolver(client, work, handler) if include_access else None
        )
    except Exception as e:
        if fails_the_whole_run(e):
            raise
        logger.exception(
            "Failed to build the Zoom access list for session %s occurrence %s",
            work.session_id,
            occurrence_uuid,
        )
        yield ConnectorFailure(
            failed_document=DocumentFailure(
                document_id=zoom_document_id(work.session_type, occurrence_uuid)
            ),
            failure_message=f"Failed to build the access list for Zoom session {work.session_id} occurrence {occurrence_uuid}: {e}",
            exception=e,
        )
        return

    yield Document(
        id=zoom_document_id(work.session_type, occurrence_uuid),
        sections=[TextSection(text=transcript_text)],
        source=DocumentSource.ZOOM,
        semantic_identifier=topic,
        doc_created_at=occurrence_time,
        doc_updated_at=occurrence_time,
        metadata={"session_type": work.session_type.value},
        external_access=external_access,
    )
