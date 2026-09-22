"""Who may read a transcript: whoever Zoom lets watch its cloud recording.

The owner always may. Beyond that the recording's Link access decides, read
from its share settings and, for a domain rule, from the account's sign-in
rule catalogue. Nothing here touches a meeting or webinar endpoint: who
attended or was invited is not who may watch, and the connector never grants
on it. Zoom cannot say who is in "People with access", so that share, and any
other the connector does not recognise, grants nobody but the owner.
"""

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
    ZoomRecordingSettings,
    ZoomShareRecording,
)
from onyx.connectors.zoom.recordings.access import (
    ZoomAccessListUnavailable,
    approved_registrant_emails,
    usable_emails,
)
from onyx.connectors.zoom.recordings.models import user_does_not_exist
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Zoom's `authentication_option` for "Only people with access". It never appears
# in the rule catalogue, and it arrives with `share_recording` still "publicly",
# so it is checked before that field is read.
ONLY_PEOPLE_WITH_ACCESS_OPTION = "specialEmail"

# The three rule types Zoom documents. The first two admit anyone once they
# sign in and count as public under the checkbox; only the last carries domains.
ZOOM_ACCOUNT_RULE_TYPE = "internally"
ZOOM_ANY_ZOOM_USER_RULE_TYPE = "enforce_login"
ZOOM_DOMAIN_RULE_TYPE = "enforce_login_with_domains"


class _Grant(NamedTuple):
    """What a share grants beyond the owner."""

    public: bool
    domains: frozenset[str]


_OWNER_ONLY = _Grant(public=False, domains=frozenset())


class ZoomAccessContext:
    """What every access decision in a run shares: the checkbox, the account's
    sign-in rules, and the owners already looked up. Zoom is asked for each
    only once per run."""

    def __init__(self, client: ZoomClient, treat_link_access_as_public: bool) -> None:
        self.client = client
        self.treat_link_access_as_public = treat_link_access_as_public
        self._owner_emails: dict[str, str | None] = {}
        self._rules: dict[str, _Grant] | None = None

    def owner_email(self, user_id: str) -> str | None:
        """None when Zoom has no such user any more. A blank address, which Zoom
        keeps until an invitation is accepted, counts the same."""
        if user_id not in self._owner_emails:
            self._owner_emails[user_id] = self._look_up_owner(user_id)
        return self._owner_emails[user_id]

    def rule_grant(self, rule_id: str) -> _Grant | None:
        if self._rules is None:
            self._rules = self._load_rules()
        return self._rules.get(rule_id)

    def _load_rules(self) -> dict[str, _Grant]:
        """The catalogue is account-wide, so any listed user's answer serves the
        run. Asked through the listing rather than a recording's owner, who may
        have left the account since. An account with no users has no
        recordings to ask about either."""
        page = self.client.list_users()
        user_id = next((u.id for u in page.users if u.id), None)
        if user_id is None:
            return {}
        catalogue = self.client.get_recording_authentication_rules(user_id)
        return {rule.id: _grant_of(rule) for rule in catalogue.authentication_options}

    def _look_up_owner(self, user_id: str) -> str | None:
        try:
            user = self.client.get_user(user_id)
        except Exception as e:
            if user_does_not_exist(e):
                return None
            raise
        emails = usable_emails(f"the owner {user_id}", [user.email])
        return next(iter(emails), None)


def _grant_of(rule: ZoomRecordingAuthenticationRule) -> _Grant:
    if rule.type in (ZOOM_ACCOUNT_RULE_TYPE, ZOOM_ANY_ZOOM_USER_RULE_TYPE):
        return _Grant(public=True, domains=frozenset())
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
        return _Grant(public=False, domains=domains)
    logger.warning(
        "Zoom sign-in rule %s is of a type this connector does not know, %r, so a "
        "recording shared under it is readable by its owner alone",
        rule.id,
        rule.type,
    )
    return _OWNER_ONLY


def resolve_recording_access(
    context: ZoomAccessContext, recording: ZoomRecordingEntry
) -> ExternalAccess:
    """Raises ZoomAccessListUnavailable rather than answering with an empty
    list, which would read as nobody having access."""
    client = context.client
    try:
        settings = client.get_recording_settings(recording.uuid)
        grant = _link_access(context, settings, recording)
    except ValidationError as e:
        logger.warning(
            "Zoom answered with share settings this connector does not recognise "
            "for recording %s, so only its owner may read it: %s",
            recording.uuid,
            e,
        )
        settings, grant = None, _OWNER_ONLY

    emails: set[str] = set()
    owner = context.owner_email(recording.host_id)
    if owner is not None:
        emails.add(owner)
    # Nobody can reach the registration page of a private recording, and an
    # owner who went private wants everyone out.
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
    context: ZoomAccessContext,
    settings: ZoomRecordingSettings,
    recording: ZoomRecordingEntry,
) -> _Grant:
    """The Link access table as code. "Only people with access" is checked
    before `share_recording`, which still says publicly for it."""
    if (
        settings.authentication_option == ONLY_PEOPLE_WITH_ACCESS_OPTION
        or settings.share_recording is ZoomShareRecording.NONE
        or not context.treat_link_access_as_public
    ):
        return _OWNER_ONLY
    if not settings.authentication_option:
        return _Grant(public=True, domains=frozenset())

    grant = context.rule_grant(settings.authentication_option)
    if grant is None:
        logger.warning(
            "Recording %s is shared under sign-in rule %s, which is not in the "
            "account's catalogue, so only its owner may read it",
            recording.uuid,
            settings.authentication_option,
        )
        return _OWNER_ONLY
    return grant
