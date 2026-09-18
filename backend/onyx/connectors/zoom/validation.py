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
from typing import TypeVar

import requests

from onyx.connectors.exceptions import (
    ConnectorValidationError,
    UnexpectedValidationError,
    ValidationError,
)
from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.recordings.access import session_is_gone
from onyx.connectors.zoom.recordings.discovery import session_ids

_T = TypeVar("_T")


def _configured(values: list[str] | None) -> list[str]:
    return [value.strip() for value in values or [] if value and value.strip()]


# Zoom caps a recordings listing at 30 days per request.
_SAMPLE_WINDOW_DAYS = 30


def _probe(description: str, call: Callable[[], _T]) -> _T | None:
    """None means Zoom has no such thing: one configured id that is deleted or
    past retention. Discovery reports that per session; raising it here would
    pause the whole connector on every crawl.

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


def _probe_transcript_scope(client: ZoomClient, uuid: str) -> None:
    """Every path reads transcripts through this endpoint. A 404 only means the
    sample session was never cloud-recorded, which says nothing about scopes."""
    _probe(f"the recording files of {uuid}", lambda: client.get_transcript(uuid))


def probe_zoom(
    client: ZoomClient,
    *,
    meeting_ids: list[str] | None,
    webinar_ids: list[str] | None,
    host_emails: list[str] | None,
    group_id: str | None,
) -> None:
    meeting_ids = session_ids(meeting_ids)
    webinar_ids = session_ids(webinar_ids)
    host_emails = _configured(host_emails)
    group_id = group_id.strip() if group_id and group_id.strip() else None

    _probe("the OAuth token request", client.check_credentials)

    occurrence_uuid: str | None = None
    if meeting_ids:
        first_meeting = meeting_ids[0]
        occurrences = _probe(
            f"meeting {first_meeting}",
            lambda: client.list_past_meeting_occurrences(first_meeting),
        )
        occurrence_uuid = next((o.uuid for o in occurrences or []), None)
    if webinar_ids:
        # Runs even when a meeting already gave a sample, because this call is
        # also what finds a missing Webinar add-on.
        first_webinar = webinar_ids[0]
        occurrences = _probe(
            f"webinar {first_webinar}",
            lambda: client.list_past_webinar_occurrences(first_webinar),
        )
        occurrence_uuid = occurrence_uuid or next(
            (o.uuid for o in occurrences or []), None
        )

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

    recording_uuid: str | None = None
    if sample_user:
        user_id = sample_user
        today = datetime.now(timezone.utc).date()
        # The widest window one call allows. A single day is usually empty, and
        # an empty sample leaves the transcript scope unprobed.
        recordings = _probe(
            f"the recordings of user {user_id}",
            lambda: client.list_user_recordings(
                user_id, today - timedelta(days=_SAMPLE_WINDOW_DAYS), today
            ),
        )
        recording_uuid = next(
            (r.uuid for r in (recordings.recordings if recordings else [])), None
        )

    # A recording listing only returns sessions that have one, so its uuid
    # reaches the transcript endpoint. An occurrence may have no recording at
    # all, and then a 404 hides whether the scope is granted.
    sample_uuid = recording_uuid or occurrence_uuid
    if sample_uuid:
        _probe_transcript_scope(client, sample_uuid)
