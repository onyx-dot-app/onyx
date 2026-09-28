"""This runs the same way for every discovery mechanism and session type.
Anything that differs between meetings and webinars belongs on the
SessionTypeHandler, not in a branch here.
"""

from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    TextSection,
)
from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.recordings.access import (
    ZoomAccessListUnavailable,
    zoom_access_resolver,
)
from onyx.connectors.zoom.recordings.models import (
    OccurrenceWork,
    ZoomSessionType,
    fails_the_whole_run,
    has_no_transcript,
)
from onyx.connectors.zoom.recordings.session_types import get_session_type_handler
from onyx.file_processing.webvtt import parse_vtt_transcript
from onyx.utils.logger import setup_logger

logger = setup_logger()


_DOCUMENT_ID_PREFIX = "ZOOM"


def _document_id_prefix(session_type: ZoomSessionType) -> str:
    return f"{_DOCUMENT_ID_PREFIX}_{session_type.value.upper()}_"


# The session type is baked into the id because a targeted reindex is handed
# document ids and nothing else, and it has to know which endpoints to call
# to rebuild the document. Changing this scheme later orphans everything
# already indexed, so it carries the type from the start.
def zoom_document_id(session_type: ZoomSessionType, occurrence_uuid: str) -> str:
    return f"{_document_id_prefix(session_type)}{occurrence_uuid}"


def parse_zoom_document_id(document_id: str) -> tuple[ZoomSessionType, str] | None:
    """None means another connector wrote the id, and the caller then fails that
    one target rather than the batch it arrived in.

    A Zoom occurrence uuid is base64 and can carry an underscore of its own, so
    the prefix is matched whole instead of splitting on underscores.
    """
    for session_type in ZoomSessionType:
        prefix = _document_id_prefix(session_type)
        if document_id.startswith(prefix) and len(document_id) > len(prefix):
            return session_type, document_id[len(prefix) :]
    return None


def process_occurrence(
    client: ZoomClient, work: OccurrenceWork, *, include_access: bool
) -> Document | ConnectorFailure | None:
    """One occurrence is at most one transcript, so this answers with the
    document, the failure that replaces it, or nothing when the occurrence has
    no transcript to index."""
    handler = get_session_type_handler(work.session_type)
    occurrence_uuid = work.occurrence_uuid

    try:
        transcript = client.get_transcript(occurrence_uuid)
    except Exception as e:
        if fails_the_whole_run(e):
            raise
        if has_no_transcript(e):
            logger.info(
                "Zoom has no transcript for session %s occurrence %s; skipping",
                work.session_id,
                occurrence_uuid,
            )
            return None
        logger.exception(
            "Failed to fetch Zoom transcript for session %s occurrence %s",
            work.session_id,
            occurrence_uuid,
        )
        return ConnectorFailure(
            failed_document=DocumentFailure(
                document_id=zoom_document_id(work.session_type, occurrence_uuid)
            ),
            failure_message=(
                f"Zoom {work.session_type.value} {work.session_id} occurrence "
                f"{occurrence_uuid} was not indexed because its transcript "
                f"could not be fetched: {e}"
            ),
            exception=e,
        )

    if transcript is None:
        logger.info(
            "Zoom recorded session %s occurrence %s but never transcribed it; skipping",
            work.session_id,
            occurrence_uuid,
        )
        return None

    download_url = transcript.download_url
    if not transcript.is_downloadable or not download_url:
        if not transcript.is_ready:
            logger.info(
                "Zoom transcript for session %s occurrence %s isn't ready yet; "
                "will pick it up on a future sync",
                work.session_id,
                occurrence_uuid,
            )
        else:
            logger.warning(
                "Zoom transcript for session %s occurrence %s has no download URL; "
                "skipping",
                work.session_id,
                occurrence_uuid,
            )
        return None

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
        return ConnectorFailure(
            failed_document=DocumentFailure(
                document_id=zoom_document_id(work.session_type, occurrence_uuid)
            ),
            failure_message=(
                f"Zoom {work.session_type.value} {work.session_id} occurrence "
                f"{occurrence_uuid} was not indexed because its transcript "
                f"could not be downloaded: {e}"
            ),
            exception=e,
        )

    transcript_text = parse_vtt_transcript(vtt_content)
    if not transcript_text:
        logger.warning(
            "Zoom transcript for session %s occurrence %s was empty after "
            "parsing; skipping",
            work.session_id,
            occurrence_uuid,
        )
        return None

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
    occurrence_time = time_str_to_utc(started_at) if started_at else None

    # Resolved last so a session with nothing to index never pays for the extra
    # calls. Failing the document beats indexing it with an access list we know
    # is wrong, and a targeted reindex can come back for it later.
    try:
        external_access = (
            zoom_access_resolver(client, work, handler) if include_access else None
        )
    except ZoomAccessListUnavailable as e:
        # This one already reads as a whole sentence, so don't bury it behind
        # a prefix the way the generic case below has to.
        logger.warning("%s", e)
        return ConnectorFailure(
            failed_document=DocumentFailure(
                document_id=zoom_document_id(work.session_type, occurrence_uuid)
            ),
            failure_message=str(e),
            exception=e,
        )
    except Exception as e:
        if fails_the_whole_run(e):
            raise
        logger.exception(
            "Failed to build the Zoom access list for session %s occurrence %s",
            work.session_id,
            occurrence_uuid,
        )
        return ConnectorFailure(
            failed_document=DocumentFailure(
                document_id=zoom_document_id(work.session_type, occurrence_uuid)
            ),
            failure_message=(
                f"Zoom {work.session_type.value} {work.session_id} occurrence "
                f"{occurrence_uuid} was not indexed because its access list "
                f"could not be built: {e}"
            ),
            exception=e,
        )

    return Document(
        id=zoom_document_id(work.session_type, occurrence_uuid),
        sections=[TextSection(text=transcript_text)],
        source=DocumentSource.ZOOM,
        semantic_identifier=topic,
        doc_created_at=occurrence_time,
        doc_updated_at=occurrence_time,
        metadata={"session_type": work.session_type.value},
        external_access=external_access,
    )
