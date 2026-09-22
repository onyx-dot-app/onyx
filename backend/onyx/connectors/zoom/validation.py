"""Live checks that run before a crawl starts, with an admin waiting on the
result the first time.

`validate_connector_settings` runs on every indexing attempt, and anything
raised from here other than UnexpectedValidationError pauses the connector, so
these probe only what should stop a crawl: the credentials, the scopes and the
add-ons. Whether one id or email is right is discovery's job, and it reports
every bad one as an indexing error.
"""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import NamedTuple, TypeVar

import requests

from onyx.connectors.exceptions import (
    ConnectorValidationError,
    UnexpectedValidationError,
    ValidationError,
)
from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.models import APPROVED_REGISTRANT_STATUS, ZoomRecordingEntry
from onyx.connectors.zoom.recordings.access import session_is_gone
from onyx.connectors.zoom.recordings.discovery import session_ids
from onyx.utils.logger import setup_logger

logger = setup_logger()

_T = TypeVar("_T")


def _configured(values: list[str] | None) -> list[str]:
    return [value.strip() for value in values or [] if value and value.strip()]


# Zoom caps a recordings listing at 30 days per request. A quiet host may have
# nothing in the latest window, so a few earlier ones are tried before giving up.
_SAMPLE_WINDOW_DAYS = 30
_SAMPLE_WINDOWS = 3
# An occurrence need not have been recorded, so several are tried in turn.
_SAMPLE_CANDIDATES = 5


def _probe(description: str, call: Callable[[], _T]) -> _T | None:
    """None means Zoom has no such thing: a configured meeting, webinar or
    Group that is deleted or past retention. Discovery reports each one as an
    indexing error and crawls the rest; raising it here would pause the whole
    connector on every crawl.

    A 503 or a dropped connection must not become ConnectorValidationError,
    because that would disable the connector over a Zoom outage.
    """
    try:
        return call()
    except ValidationError:
        raise
    except requests.HTTPError as e:
        if session_is_gone(e):
            return None
        status = e.response.status_code if e.response is not None else None
        if status == 400:
            raise ConnectorValidationError(f"Zoom refused {description}: {e}") from e
        raise UnexpectedValidationError(
            f"Zoom answered {status} while checking {description}: {e}"
        ) from e
    except requests.RequestException as e:
        raise UnexpectedValidationError(
            f"Could not reach Zoom while checking {description}: {e}"
        ) from e


class ProbeSample(NamedTuple):
    """What validation found to ask Zoom about: a recording Zoom answered for,
    and a user, its owner when there is one. Kept as ids rather than the whole
    entry with its download URLs and passcode."""

    recording_uuid: str | None
    user_id: str | None


def _probe_transcript_scope(
    client: ZoomClient, candidates: list[str]
) -> ZoomRecordingEntry | None:
    """Every path reads transcripts through this endpoint. A 404 only means that
    candidate was never cloud-recorded, which says nothing about scopes, so the
    next one is tried."""
    for uuid in candidates[:_SAMPLE_CANDIDATES]:
        entry = _probe(
            f"the recording files of {uuid}", partial(client.get_recording, uuid)
        )
        if entry is not None:
            return entry
    return None


def probe_recording_access_scopes(client: ZoomClient, sample: ProbeSample) -> None:
    """A refusal here is a missing scope and nothing else, because the recording
    is one Zoom already answered for, and registration being off comes back as
    an empty list. Zoom checks some endpoints for the resource before the
    scope, so the two recording-bound scopes wait until a recording exists;
    this runs again before every attempt, so one that appears later is probed
    before anything is indexed. The sign-in rules need only a user.
    """
    if sample.recording_uuid is None:
        logger.warning(
            "Zoom has no recording to sample yet, so the recording settings and "
            "registrant scopes stay unchecked until one appears"
        )
    else:
        uuid = sample.recording_uuid
        _probe(
            f"the share settings of {uuid}", lambda: client.get_recording_settings(uuid)
        )
        # One registrant is enough to see the scope; the list could run to pages.
        _probe(
            f"the registered viewers of {uuid}",
            lambda: client.list_recording_registrants(
                uuid, status=APPROVED_REGISTRANT_STATUS, limit=1
            ),
        )

    user_id = sample.user_id
    if user_id is None:
        page = _probe("the account's users", client.list_users)
        user_id = next((u.id for u in (page.users if page else []) if u.id), None)
    if user_id is not None:
        _probe(
            f"the sign-in rules of user {user_id}",
            lambda: client.get_recording_authentication_rules(user_id),
        )


def probe_zoom(
    client: ZoomClient,
    *,
    meeting_ids: list[str] | None,
    webinar_ids: list[str] | None,
    host_emails: list[str] | None,
    group_id: str | None,
) -> ProbeSample:
    """Returns what it sampled so a later probe can ask about the same things."""
    meeting_ids = session_ids(meeting_ids)
    webinar_ids = session_ids(webinar_ids)
    host_emails = _configured(host_emails)
    group_id = group_id.strip() if group_id and group_id.strip() else None

    _probe("the OAuth token request", client.check_credentials)

    occurrence_uuids: list[str] = []
    if meeting_ids:
        first_meeting = meeting_ids[0]
        occurrences = _probe(
            f"meeting {first_meeting}",
            lambda: client.list_past_meeting_occurrences(first_meeting),
        )
        occurrence_uuids += [o.uuid for o in occurrences or []]
    if webinar_ids:
        # Runs even when a meeting already gave a sample, because this call is
        # also what finds a missing Webinar add-on.
        first_webinar = webinar_ids[0]
        occurrences = _probe(
            f"webinar {first_webinar}",
            lambda: client.list_past_webinar_occurrences(first_webinar),
        )
        occurrence_uuids += [o.uuid for o in occurrences or []]

    sample_user: str | None = None
    if host_emails:
        page = _probe("the account's users", client.list_users)
        sample_user = next((u.id for u in (page.users if page else []) if u.id), None)
    if group_id:
        members = _probe(
            f"Zoom Group {group_id}", lambda: client.list_group_members(group_id)
        )
        sample_user = (
            next((u.id for u in (members.users if members else []) if u.id), None)
            or sample_user
        )

    recording_uuids: list[str] = []
    if sample_user:
        user_id = sample_user
        window_end = datetime.now(timezone.utc).date()
        for _ in range(_SAMPLE_WINDOWS):
            window_start = window_end - timedelta(days=_SAMPLE_WINDOW_DAYS)
            recordings = _probe(
                f"the recordings of user {user_id}",
                partial(client.list_user_recordings, user_id, window_start, window_end),
            )
            recording_uuids = [
                r.uuid for r in (recordings.recordings if recordings else [])
            ]
            if recording_uuids:
                break
            window_end = window_start

    # A recording listing only returns sessions that have one, so those go
    # first. An occurrence may have no recording at all.
    entry = _probe_transcript_scope(client, recording_uuids + occurrence_uuids)
    if entry is None:
        return ProbeSample(recording_uuid=None, user_id=sample_user)
    return ProbeSample(recording_uuid=entry.uuid, user_id=entry.host_id)
