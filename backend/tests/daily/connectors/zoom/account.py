"""The Zoom test account, kept in the state these tests expect.

ZOOM_TEST_HOST_EMAIL names the one host who owns every recording below. Each
recording was set once to the Link access named here in the Zoom web portal
and left there. The account's sign-in rules are "Signed-in users in my
account" and a domain rule named "testing access with specified domains" that
grants the host's own domain. Change a recording or add one, and update the
table.
"""

from datetime import timedelta
from enum import Enum
from typing import NamedTuple

from onyx.access.models import ExternalAccess
from onyx.access.utils import build_domain_group_id, build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.zoom.recordings.models import ZoomSessionType

# Every recording is younger than this.
RECORDINGS_WITHIN = timedelta(days=400)


class Grant(Enum):
    OWNER_ONLY = "the owner alone"
    DOMAIN = "the owner and everyone in the owner's domain"
    PUBLIC = "everyone"


class Recording(NamedTuple):
    topic: str
    session_type: ZoomSessionType
    occurrences: int
    link_access: str
    grant: Grant


RECORDINGS = (
    Recording(
        topic="test non recurrence Zoom Meeting",
        session_type=ZoomSessionType.MEETING,
        occurrences=1,
        link_access="Private to me",
        grant=Grant.OWNER_ONLY,
    ),
    Recording(
        topic="testing webinar series",
        session_type=ZoomSessionType.WEBINAR,
        occurrences=1,
        link_access="Only people with access",
        grant=Grant.OWNER_ONLY,
    ),
    Recording(
        topic="test channel meeting",
        session_type=ZoomSessionType.MEETING,
        occurrences=1,
        link_access='Signed-in users, rule "testing access with specified domains"',
        grant=Grant.DOMAIN,
    ),
    Recording(
        topic="test meeting series",
        session_type=ZoomSessionType.MEETING,
        occurrences=2,
        link_access="Signed-in users in my account",
        grant=Grant.PUBLIC,
    ),
    Recording(
        topic="testing webinar",
        session_type=ZoomSessionType.WEBINAR,
        occurrences=1,
        link_access="Anyone with the link",
        grant=Grant.PUBLIC,
    ),
)


def domain_of(email: str) -> str:
    return email.rpartition("@")[2]


def expected_access(grant: Grant, owner: str) -> ExternalAccess:
    """What indexing attaches: the owner is always named, and a public
    recording is public as well."""
    groups = (
        {
            build_ext_group_name_for_onyx(
                build_domain_group_id(domain_of(owner)), DocumentSource.ZOOM
            )
        }
        if grant is Grant.DOMAIN
        else set()
    )
    return ExternalAccess(
        external_user_emails={owner},
        external_user_group_ids=groups,
        is_public=grant is Grant.PUBLIC,
    )
