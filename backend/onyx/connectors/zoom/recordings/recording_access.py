"""Who may read a transcript: whoever Zoom lets watch its cloud recording.

The owner always may; beyond that the recording's Link access decides, read
from its share settings and, for a domain rule, the account's sign-in rule
catalogue. Nothing here touches a meeting or webinar endpoint: who attended or
was invited is not who may watch. Zoom cannot say who is in "People with
access", so that share, like any the connector does not recognise, grants
nobody but the owner. An owner's address and the account's rule catalogue are
the same for every recording in a run, so the caller memoises both, and the
catalogue is only asked for when a recording names a rule.
"""

from collections.abc import Callable, Sequence
from typing import NamedTuple

from pydantic import ValidationError

from onyx.access.models import ExternalAccess
from onyx.access.utils import build_domain_group_id, build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.models import (
    APPROVED_REGISTRANT_STATUS,
    ZoomRecordingAuthenticationRule,
    ZoomRecordingEntry,
    ZoomRecordingRegistrant,
    ZoomRecordingSettings,
    ZoomShareRecording,
)
from onyx.connectors.zoom.recordings.models import user_does_not_exist
from onyx.utils.logger import setup_logger

logger = setup_logger()

AccessResolver = Callable[[ZoomRecordingEntry], ExternalAccess]

# Zoom's `authentication_option` for "Only people with access". It never appears
# in the rule catalogue, and it arrives with `share_recording` still "publicly",
# so it is checked before that field is read.
ONLY_PEOPLE_WITH_ACCESS_OPTION = "specialEmail"

# The rule types Zoom documents; only the last carries domains.
ZOOM_ACCOUNT_RULE_TYPE = "internally"
ZOOM_ANY_ZOOM_USER_RULE_TYPE = "enforce_login"
ZOOM_DOMAIN_RULE_TYPE = "enforce_login_with_domains"


class RuleGrant(NamedTuple):
    """What a share grants beyond the owner."""

    public: bool
    domains: frozenset[str]


_OWNER_ONLY = RuleGrant(public=False, domains=frozenset())
_EVERYONE = RuleGrant(public=True, domains=frozenset())


def load_rule_grants(
    client: ZoomClient, user_id: str | None = None
) -> dict[str, RuleGrant]:
    """The catalogue is account-wide, so it is asked for through any user the
    account still lists rather than a recording's owner, who may have left; a
    caller that has listed the account passes one it saw. An account with no
    users has no recordings to ask about either."""
    if user_id is None:
        page = client.list_users()
        user_id = next((u.id for u in page.users if u.id), None)
    if user_id is None:
        return {}
    catalogue = client.get_recording_authentication_rules(user_id)
    return {rule.id: _grant_of(rule) for rule in catalogue.authentication_options}


def _grant_of(rule: ZoomRecordingAuthenticationRule) -> RuleGrant:
    if rule.type in (ZOOM_ACCOUNT_RULE_TYPE, ZOOM_ANY_ZOOM_USER_RULE_TYPE):
        return _EVERYONE
    if rule.type == ZOOM_DOMAIN_RULE_TYPE:
        domains = frozenset(
            d.strip().lower() for d in rule.domains.split(",") if d.strip()
        )
        if not domains:
            logger.warning(
                "Zoom sign-in rule %s is a domain rule that lists no domains, so "
                "a recording shared under it is readable by its owner alone",
                rule.id,
            )
        return RuleGrant(public=False, domains=domains)
    logger.warning(
        "Zoom sign-in rule %s is of a type this connector does not know, %r, so a "
        "recording shared under it is readable by its owner alone",
        rule.id,
        rule.type,
    )
    return _OWNER_ONLY


class ZoomAccessListUnavailable(Exception):
    """Nobody could be named to read a recording. It must stay something
    `fails_the_whole_run` does not recognise, or one such recording would end
    the whole attempt."""


def approved_registrant_emails(
    registrants: Sequence[ZoomRecordingRegistrant],
) -> list[str]:
    """The caller already asks Zoom for approved registrants only. This checks
    again so access never depends on Zoom honouring a query parameter."""
    return [
        registrant.email
        for registrant in registrants
        if registrant.status == APPROVED_REGISTRANT_STATUS
    ]


def usable_emails(description: str, emails: list[str]) -> set[str]:
    usable = [email.strip() for email in emails if email.strip()]
    dropped = len(emails) - len(usable)
    if dropped:
        logger.info(
            "Dropped %s of %s people from %s: Zoom returned no email for them",
            dropped,
            len(emails),
            description,
        )
    return {email.lower() for email in usable}


def look_up_owner_email(client: ZoomClient, user_id: str) -> str | None:
    """None when Zoom has no such user any more. A blank address, which Zoom
    keeps until an invitation is accepted, counts the same."""
    try:
        user = client.get_user(user_id)
    except Exception as e:
        if user_does_not_exist(e):
            return None
        raise
    return next(iter(usable_emails(f"the owner {user_id}", [user.email])), None)


def resolve_recording_access(
    client: ZoomClient,
    recording: ZoomRecordingEntry,
    *,
    treat_link_access_as_public: bool,
    rule_grant: Callable[[str], RuleGrant | None],
    owner_email: str | None,
) -> ExternalAccess:
    """Raises ZoomAccessListUnavailable rather than answering with an empty
    list, which would read as nobody having access."""
    try:
        settings = client.get_recording_settings(recording.uuid)
        grant = _link_access(
            settings, recording.uuid, treat_link_access_as_public, rule_grant
        )
    except ValidationError as e:
        logger.warning(
            "Zoom answered with share settings this connector does not recognise "
            "for recording %s, so only its owner may read it: %s",
            recording.uuid,
            e,
        )
        settings, grant = None, _OWNER_ONLY

    emails: set[str] = {owner_email} if owner_email is not None else set()
    # A private recording's registration page is unreachable, and an owner
    # who went private wants everyone out.
    if (
        settings is not None
        and settings.on_demand
        and settings.share_recording is not ZoomShareRecording.NONE
    ):
        registrants = client.list_recording_registrants(
            recording.uuid, status=APPROVED_REGISTRANT_STATUS
        )
        emails |= usable_emails(
            f"the registered viewers of {recording.uuid}",
            approved_registrant_emails(registrants),
        )
    # Prefixed with the source here because this is the indexing path; the
    # group sync's membership rows get the same prefix on the way in.
    groups = {
        build_ext_group_name_for_onyx(build_domain_group_id(d), DocumentSource.ZOOM)
        for d in grant.domains
    }

    if not emails and not groups and not grant.public:
        raise ZoomAccessListUnavailable(
            f"Zoom recording {recording.uuid} was not indexed because its owner "
            f"{recording.host_id} is not among the account's users and its share "
            "settings grant nobody else, so nobody could be named to read it"
        )
    access = ExternalAccess(
        external_user_emails=emails,
        external_user_group_ids=groups,
        is_public=grant.public,
    )
    # Kept rather than truncated: the limit is advisory, and truncating would
    # silently pick which registered viewers lose access.
    if access.num_entries > ExternalAccess.MAX_NUM_ENTRIES:
        logger.warning(
            "Zoom recording %s grants %s people, over the %s Onyx expects",
            recording.uuid,
            access.num_entries,
            ExternalAccess.MAX_NUM_ENTRIES,
        )
    return access


def _link_access(
    settings: ZoomRecordingSettings,
    uuid: str,
    treat_link_access_as_public: bool,
    rule_grant: Callable[[str], RuleGrant | None],
) -> RuleGrant:
    if (
        settings.authentication_option == ONLY_PEOPLE_WITH_ACCESS_OPTION
        or settings.share_recording is ZoomShareRecording.NONE
        or not treat_link_access_as_public
    ):
        return _OWNER_ONLY
    if not settings.authentication_option:
        if settings.recording_authentication:
            logger.warning(
                "Recording %s requires sign-in but names no rule, so only its "
                "owner may read it",
                uuid,
            )
            return _OWNER_ONLY
        return _EVERYONE

    grant = rule_grant(settings.authentication_option)
    if grant is None:
        logger.warning(
            "Recording %s is shared under sign-in rule %s, which is not in the "
            "account's catalogue, so only its owner may read it",
            uuid,
            settings.authentication_option,
        )
        return _OWNER_ONLY
    return grant
