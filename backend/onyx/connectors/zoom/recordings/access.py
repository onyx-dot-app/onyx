"""Builds a document access list from the people Zoom recorded on a Session.

Zoom has no sharing API, so access is inferred from who attended, who registered
and who was invited. Zoom returns an empty email for anyone outside the host's
account, and those people are dropped because nobody can be granted access
without an address. Zoom also deletes this data after a retention window and
then answers with an error instead of an empty list, so that error means "no
data" here and never becomes a document failure. Returning None leaves the
document on document-set and group access.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, NamedTuple

import requests

from onyx.access.models import ExternalAccess
from onyx.connectors.zoom.client import ZoomClient, ZoomNotEntitledError
from onyx.connectors.zoom.models import (
    APPROVED_REGISTRANT_STATUS,
    ZOOM_MEETING_TOO_OLD_CODE,
    ZOOM_NOT_ENTITLED_CODE,
    ZOOM_NOT_FOUND_CODE,
    ZoomRegistrant,
)
from onyx.connectors.zoom.recordings.models import OccurrenceWork
from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    from onyx.connectors.zoom.recordings.session_types import SessionTypeHandler

logger = setup_logger()


class ZoomAccessListUnavailable(Exception):
    """Nobody could be named as having access to a session. Indexing it anyway
    would put it on connector-level access, which is broader than the session,
    so the document is failed instead."""


_PERMANENT_ERROR_CODES = frozenset(
    {ZOOM_MEETING_TOO_OLD_CODE, ZOOM_NOT_FOUND_CODE, ZOOM_NOT_ENTITLED_CODE}
)


def _zoom_error_code(error: requests.HTTPError) -> str | None:
    response = error.response
    if response is None:
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict) or body.get("code") is None:
        return None
    return str(body["code"])


def is_plan_denial(error: Exception) -> bool:
    """Zoom refuses on plan or licence grounds two different ways: a typed error
    on the webinar endpoints, and a code on the rest."""
    if isinstance(error, ZoomNotEntitledError):
        return True
    return (
        isinstance(error, requests.HTTPError)
        and _zoom_error_code(error) == ZOOM_NOT_ENTITLED_CODE
    )


def permanently_unavailable(error: Exception) -> bool:
    """A missing scope is deliberately left out of this set. It arrives as a
    plain InsufficientPermissionsError and fails the whole run so an admin fixes
    it, instead of quietly emptying every document's access list.
    """
    if is_plan_denial(error):
        return True
    if not isinstance(error, requests.HTTPError):
        return False
    response = error.response
    if response is None:
        return False
    if response.status_code == 404:
        return True
    return (
        response.status_code == 400
        and _zoom_error_code(error) in _PERMANENT_ERROR_CODES
    )


def approved_registrant_emails(registrants: list[ZoomRegistrant]) -> list[str]:
    """The caller already asks Zoom for approved registrants only. This checks
    again so access never depends on Zoom honouring a query parameter."""
    return [
        registrant.email
        for registrant in registrants
        if registrant.status == APPROVED_REGISTRANT_STATUS
    ]


def _usable_emails(description: str, emails: list[str]) -> set[str]:
    usable = [email.strip() for email in emails if email.strip()]
    dropped = len(emails) - len(usable)
    if dropped:
        logger.info(
            "Dropped %s of %s people from %s: Zoom returned no email for them, "
            "which it does for anyone outside the host's account",
            dropped,
            len(emails),
            description,
        )
    return {email.lower() for email in usable}


AccessSource = tuple[str, Callable[[], list[str]]]


class AccessList(NamedTuple):
    emails: set[str]
    # Why each source could not be read, so a session that ends up with nobody
    # can name which ones failed and why.
    unavailable: list[str]


def union_source_emails(sources: list[AccessSource]) -> AccessList:
    """A source Zoom has forgotten contributes nothing; any other failure is
    raised for the caller to turn into a document failure."""
    emails: set[str] = set()
    unavailable: list[str] = []
    for description, fetch in sources:
        try:
            emails |= _usable_emails(description, fetch())
        except Exception as e:
            if not permanently_unavailable(e):
                raise
            reason = (
                "the account's plan does not cover it"
                if is_plan_denial(e)
                else "Zoom has deleted it or it is past its retention window"
            )
            logger.warning("Couldn't read %s: %s (%s)", description, reason, e)
            unavailable.append(f"{description} ({reason})")
    return AccessList(emails=emails, unavailable=unavailable)


def zoom_access_resolver(
    client: ZoomClient,
    work: OccurrenceWork,
    handler: "SessionTypeHandler",
) -> ExternalAccess:
    access_list = handler.fetch_access_list(client, work)
    if not access_list.emails:
        raise ZoomAccessListUnavailable(
            f"Zoom {work.session_type.value} {work.session_id} occurrence "
            f"{work.occurrence_uuid} was not indexed because permission sync is "
            "on and nobody could be named as having access to it: "
            + (
                "; ".join(access_list.unavailable)
                if access_list.unavailable
                else "Zoom gave an email address for nobody who was there, which "
                "it does for everybody outside the host's account"
            )
        )

    access = ExternalAccess(
        external_user_emails=access_list.emails,
        # Zoom cannot grant a Session to a Group, so this stays empty. A Group
        # only provisions licences, and filling it in would give everyone in it
        # access to meetings they never attended.
        external_user_group_ids=set(),
        is_public=False,
    )
    # Keep the list rather than enforce the limit, which Onyx documents as
    # advisory. Dropping it hands the document to connector-level access,
    # failing it can never succeed on a retry, and truncating silently picks
    # who loses access.
    if access.num_entries > ExternalAccess.MAX_NUM_ENTRIES:
        logger.warning(
            "Zoom access list for %s occurrence %s has %s entries, over the "
            "%s Onyx expects",
            work.session_id,
            work.occurrence_uuid,
            access.num_entries,
            ExternalAccess.MAX_NUM_ENTRIES,
        )
    return access
