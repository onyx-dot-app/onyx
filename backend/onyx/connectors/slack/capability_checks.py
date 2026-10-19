"""Capability checks for the Slack connector.

Each check probes one permission assumption the connector makes at indexing or
doc-permission-sync time by composing the same gateway operations production
code calls (``limit=1`` where possible). Checks need no connector instance: the
runner constructs the registered ``SlackSourceOperations`` gateway from the
credential and hands it to every check via the context, so checks run
config-less at credential-creation time (except the config-reading checks,
which are skipped until a config exists).

Slack registers no EXTERNAL_GROUP_SYNC checks: group sync is unregistered for
Slack by design (``sync_params.py``), so that capability stays NOT_APPLICABLE.

Scope-to-capability mapping (see also the OAuth scope list in
``ee/onyx/server/oauth/slack.py``):

- ``channels:read``    -> INDEXING (public channel listing and metadata),
  DOC_PERMISSION_SYNC (channel enumeration for ACLs)
- ``groups:read``      -> INDEXING (private channels), DOC_PERMISSION_SYNC
  (private member ACLs); both silently fall back to public-only without it
- ``channels:history`` / ``groups:history`` -> INDEXING (message and thread
  reads)
- ``channels:join``    -> INDEXING (self-join public channels)
- ``team:read``        -> INDEXING and DOC_PERMISSION_SYNC on Enterprise Grid
  (workspace enumeration)
- ``users:read``       -> INDEXING (author names; degrades to raw ids),
  DOC_PERMISSION_SYNC (member-to-profile resolution)
- ``users:read.email`` -> DOC_PERMISSION_SYNC (member-to-email resolution)
"""

from collections.abc import Iterator
from http.client import IncompleteRead
from itertools import islice
from typing import Any, NoReturn
from urllib.error import URLError

from pydantic import BaseModel

from onyx.connectors.capability_checks.findings import bounded_options
from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    MAX_FINDING_OPTIONS,
    CapabilityCheck,
    CapabilityCheckContext,
    CheckAdvisory,
    CheckFindingKey,
    CheckNotApplicableError,
    CheckOutput,
    CredentialCapability,
    OptionsFinding,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    CredentialInvalidError,
    InconclusiveValidationError,
    InsufficientPermissionsError,
    NothingToCheckError,
    RateLimitedValidationError,
    UnexpectedValidationError,
    UnreachableValidationError,
)
from onyx.connectors.slack.config import SlackConnectorConfig
from onyx.connectors.slack.connector import (
    channel_keys,
    get_channels,
    get_channels_across_teams,
    list_grid_team_ids,
    normalize_channel_entries,
    validate_channel_regexes,
)
from onyx.connectors.slack.source_operations import (
    SlackApiError,
    SlackAuthTestResponse,
    SlackChannelVariant,
    SlackSourceOperations,
    SlackTeamsPage,
    slack_api_error_detail,
)
from onyx.connectors.source_operations import SourceOperations

_SLACK_DOCS_LINK = (
    "https://docs.onyx.app/admins/connectors/official/slack/slack_indexed"
)

_ADD_SCOPE_REMEDIATION = (
    "Add the `{scope}` bot scope under OAuth & Permissions in the Slack app "
    "settings and reinstall the app to the workspace."
)

# Page size when sampling users for email visibility. Workspaces commonly have
# many bot/deactivated users, so sample enough to nearly always include a human
# member.
_EMAIL_PROBE_PAGE_SIZE = 100

# Hang guard for the full-workspace channel enumeration, the one multi-page
# probe: triple the 600s ``CAPABILITY_CHECK_TIMEOUT_SECONDS`` default, since the
# gateway's redis-coordinated client also serves any concurrently running
# indexing job's rate-limit backoff.
_CHANNEL_ENUMERATION_TIMEOUT_SECONDS = 1800.0

# Bound on the search for one channel of a type. Slack applies ``limit`` before
# it filters by type, so a page can be empty and still have a cursor; the
# search follows the cursor across this many pages, about 200 channels in all.
# Two requests stay well inside the check timeout.
_CHANNEL_SCAN_PAGE_SIZE = 100
_CHANNEL_SCAN_PAGE_LIMIT = 2
_CHANNEL_SCAN_BOUND = _CHANNEL_SCAN_PAGE_SIZE * _CHANNEL_SCAN_PAGE_LIMIT

# Pages of ``auth.teams.list`` read to count a Grid org's workspaces.
_TEAM_COUNT_PAGE_LIMIT = 5

_NOT_ON_GRID_MESSAGE = "The workspace is not on Enterprise Grid."

# The config field that holds the channel names to index.
_CHANNELS_FIELD = "channels"
_BOT_TOKEN_KEY = "slack_bot_token"
_BOT_TOKEN_PREFIX = "xoxb-"

_AUTH_CHECK_ID = "slack_token_auth"
_GRID_LISTING_CHECK_ID = "slack_grid_workspace_listing"
_PUBLIC_LISTING_CHECK_ID = "slack_public_channel_listing"
_PRIVATE_LISTING_CHECK_ID = "slack_private_channel_listing"
_PERM_SYNC_PRIVATE_LISTING_CHECK_ID = "slack_perm_sync_private_channel_listing"
# check_id to the checks it runs after, in run order.
_DEPENDS_ON: dict[str, tuple[str, ...]] = {
    _GRID_LISTING_CHECK_ID: (_AUTH_CHECK_ID,),
    _PUBLIC_LISTING_CHECK_ID: (_AUTH_CHECK_ID,),
    "slack_readable_channel_listing": (_AUTH_CHECK_ID,),
    "slack_perm_sync_channel_listing": (_AUTH_CHECK_ID,),
    "slack_message_history_read": (_PUBLIC_LISTING_CHECK_ID,),
    "slack_channel_join_scope": (_AUTH_CHECK_ID,),
    "slack_configured_channels_visible": (_PUBLIC_LISTING_CHECK_ID,),
    _PRIVATE_LISTING_CHECK_ID: (_AUTH_CHECK_ID,),
    _PERM_SYNC_PRIVATE_LISTING_CHECK_ID: (_AUTH_CHECK_ID,),
    "slack_private_message_history_read": (_PRIVATE_LISTING_CHECK_ID,),
    "slack_private_channel_member_listing": (_PERM_SYNC_PRIVATE_LISTING_CHECK_ID,),
    "slack_user_profile_read": (_AUTH_CHECK_ID,),
    "slack_user_email_visibility": (_AUTH_CHECK_ID,),
    "slack_grid_public_channel_scoping": (_GRID_LISTING_CHECK_ID,),
}
# Checks that share one design row: a probe's variants per capability and the
# public listing's discovery step.
_ROW_IDS: dict[str, str] = {
    "slack_readable_channel_listing": _PUBLIC_LISTING_CHECK_ID,
    "slack_perm_sync_channel_listing": _PUBLIC_LISTING_CHECK_ID,
    _PERM_SYNC_PRIVATE_LISTING_CHECK_ID: _PRIVATE_LISTING_CHECK_ID,
}


class _RowText(BaseModel):
    """The row text of one outcome of a probe."""

    summary: str
    description: str


def _need(scope: str) -> str:
    """The line that says what the bot token needs."""
    return f"Add the `{scope}` bot scope, then reinstall the app."


def _counted(count: int | str, noun: str, plural: str) -> str:
    """``count`` with its noun: "1 channel", "3 channels", "1000+ channels"."""
    return f"{count} {noun if str(count) == '1' else plural}"


def _channel_name(channel: dict[str, Any]) -> str:
    return str(channel.get("name") or channel["id"])


def _caveat_output(summary: str, caveat: str) -> CheckOutput:
    """A passing result that says what the check did not verify."""
    return CheckOutput(summary=summary, advisories=[CheckAdvisory(message=caveat)])


def _slack_client(context: CapabilityCheckContext) -> SlackSourceOperations:
    gateway: SourceOperations | None = context.source_operations
    if not isinstance(gateway, SlackSourceOperations):
        raise TypeError(
            "Bug: The runner constructs the registered gateway for migrated sources."
        )
    return gateway


class _Rejection(BaseModel):
    message: str
    row: _RowText


_TOKEN_REJECTED_ROW = _RowText(
    summary="Slack rejected the bot token",
    description=(
        "Slack does not accept this token.\nIn Slack, open the app's OAuth & "
        "Permissions page and copy the Bot User OAuth Token."
    ),
)
# Slack's error for a token it does not accept, to the row it shows.
_REJECTIONS: dict[str, _Rejection] = {
    "invalid_auth": _Rejection(
        message="Invalid or expired Slack bot token (invalid_auth).",
        row=_TOKEN_REJECTED_ROW,
    ),
    "not_authed": _Rejection(
        message="Invalid or expired Slack bot token (not_authed).",
        row=_TOKEN_REJECTED_ROW,
    ),
    "account_inactive": _Rejection(
        message="Slack workspace or bot user is deactivated (account_inactive).",
        row=_RowText(
            summary="Workspace or bot user is deactivated",
            description=(
                "Slack deactivated the workspace or the bot user.\nInstall the "
                "Slack app to an active workspace."
            ),
        ),
    ),
    "token_revoked": _Rejection(
        message="Slack bot token has been revoked (token_revoked).",
        row=_RowText(
            summary="Bot token was revoked",
            description=(
                "Someone revoked the token or uninstalled the app.\nReinstall the "
                "Slack app to the workspace."
            ),
        ),
    ),
    "token_expired": _Rejection(
        message="Slack bot token has expired (token_expired).",
        row=_RowText(
            summary="Bot token expired",
            description=(
                "The token expired.\nReinstall the Slack app and copy the new Bot "
                "User OAuth Token."
            ),
        ),
    ),
}


def _error_slug(e: SlackApiError) -> str:
    return str(e.response.get("error", "")) if e.response is not None else ""


def _raise_for_slack_api_error(
    e: SlackApiError, *, denied: str, denied_row: _RowText | None = None
) -> NoReturn:
    """Maps a Slack API error onto the validation-exception family.
    ``denied`` explains a ``missing_scope`` for this probe; ``denied_row`` is
    what the check's row shows for it. The request and response go to the
    error's details."""
    cause: Exception = slack_api_error_detail(e) or e
    error = _error_slug(e)
    if error == "missing_scope":
        needed = e.response.get("needed", "")
        message = denied
        if needed:
            message += f" (Slack reported the missing scope as `{needed}`.)"
        raise InsufficientPermissionsError(
            message,
            summary=denied_row.summary if denied_row else None,
            description=denied_row.description if denied_row else None,
        ) from cause
    if rejection := _REJECTIONS.get(error):
        raise CredentialExpiredError(
            rejection.message,
            summary=rejection.row.summary,
            description=rejection.row.description,
        ) from cause
    if error == "ratelimited":
        raise RateLimitedValidationError(
            "Slack rate limited the check; re-run the checks in a minute.",
            summary="Rate limited by Slack",
            description=(
                "Slack kept refusing requests after several retries.\nWait a "
                "minute, then re-run."
            ),
        ) from cause
    raise UnexpectedValidationError(
        f"Unexpected Slack error `{error}`.",
        summary="Unexpected response from Slack",
        description=(
            "Slack answered with an error that this check does not know.\nRe-run "
            "the checks."
        ),
    ) from cause


def _auth_test(slack_client: SlackSourceOperations) -> SlackAuthTestResponse:
    try:
        return slack_client.check_auth()
    except SlackApiError as e:
        _raise_for_slack_api_error(e, denied="Slack bot token failed `auth.test`.")


_GRID_DENIED = (
    "On Enterprise Grid, listing users requires enumerating workspaces "
    "first (`auth.teams.list`), which needs the `team:read` scope."
)
_GRID_DENIED_ROW = _RowText(
    summary="Bot cannot list Grid workspaces",
    description=(
        "On Enterprise Grid, users are listed per workspace, and the bot cannot "
        f"list workspaces.\n{_need('team:read')}"
    ),
)


def _no_grid_workspaces_error() -> InconclusiveValidationError:
    return InconclusiveValidationError(
        "`auth.teams.list` returned no workspaces for this Enterprise Grid org.",
        summary="Grid org returned no workspaces",
        description=(
            "Slack listed no workspace for the org.\nCheck that the app is "
            "installed to a workspace in the org."
        ),
    )


class _GridTeam(BaseModel):
    id: str
    name: str | None


def _first_grid_team(slack_client: SlackSourceOperations) -> _GridTeam | None:
    """The first workspace of an Enterprise Grid org, None off-Grid.

    On Grid org installs ``users.list`` requires a ``team_id``, so user-facing
    checks call this to mirror the production call shape.
    """
    if not _auth_test(slack_client).enterprise_id:
        return None
    try:
        teams_page: SlackTeamsPage = next(slack_client.list_teams(limit=1))
    except SlackApiError as e:
        _raise_for_slack_api_error(e, denied=_GRID_DENIED, denied_row=_GRID_DENIED_ROW)
    if not teams_page.teams:
        raise _no_grid_workspaces_error()
    team = teams_page.teams[0]
    return _GridTeam(id=str(team["id"]), name=team.get("name"))


def _find_channel(
    slack_client: SlackSourceOperations,
    variant: SlackChannelVariant,
    exclude_archived: bool | None,
) -> dict[str, Any] | None:
    """Returns the first channel of the variant that the bot sees, None when
    the bounded search finds none. Raises ``SlackApiError`` for the caller to
    map."""
    pages = slack_client.list_channels(
        variant=variant,
        channel_types=[f"{variant.value}_channel"],
        exclude_archived=exclude_archived,
        limit=_CHANNEL_SCAN_PAGE_SIZE,
    )
    for page in islice(pages, _CHANNEL_SCAN_PAGE_LIMIT):
        if page.channels:
            return page.channels[0]
    return None


_PUBLIC_LISTING_DENIED = (
    "The bot token cannot list public channels (`conversations.list`), which "
    "indexing requires to enumerate what to index."
)
_PUBLIC_LISTING_DENIED_ROW = _RowText(
    summary="Bot cannot list public channels",
    description=(
        "Indexing cannot find any channel to index without listing public "
        f"channels.\n{_need('channels:read')}"
    ),
)
_PRIVATE_LISTING_DENIED_ROW = _RowText(
    summary="Bot cannot list private channels",
    description=(f"Private messages would stay out of search.\n{_need('groups:read')}"),
)


def _first_private_channel(
    slack_client: SlackSourceOperations, nothing_to_test: str
) -> dict[str, Any]:
    """One private channel the bot is in. None found is nothing to test: the
    bot sees a private channel only once someone invites it.
    ``nothing_to_test`` says what the check would test."""
    try:
        channel = _find_channel(
            slack_client, SlackChannelVariant.PRIVATE, exclude_archived=True
        )
    except SlackApiError as e:
        _raise_for_slack_api_error(
            e,
            denied="The bot token cannot list private channels.",
            denied_row=_PRIVATE_LISTING_DENIED_ROW,
        )
    if channel is None:
        raise NothingToCheckError(
            "The check found no private channel for the bot in the first "
            f"{_CHANNEL_SCAN_BOUND} channels that Slack scanned.",
            summary="Bot is in no private channel",
            description=f"{nothing_to_test}\n{_INVITE_LINE}",
        )
    return channel


_INVITE_LINE = "In the channel, type `/invite @<bot>`."


def _no_private_channel_output() -> CheckOutput:
    return _caveat_output(
        "Bot is in no private channel",
        "Private channel listing works, but the bot is in no private channel "
        f"among the {_CHANNEL_SCAN_BOUND} scanned. The bot sees a private channel "
        "only after someone invites it.",
    )


class _HistoryRows(BaseModel):
    history_denied: str
    history_denied_row: _RowText
    replies_denied: str
    replies_denied_row: _RowText


def _probe_channel_history(
    slack_client: SlackSourceOperations,
    variant: SlackChannelVariant,
    channel: dict[str, Any],
    rows: _HistoryRows,
) -> CheckOutput:
    """Reads one message page, then one thread, from the channel.

    ``not_in_channel`` passes with a caveat: Slack checks scope before
    membership, and indexing self-joins public channels. An empty channel
    passes with a caveat: the history read worked, but no thread was read.
    """
    name = _channel_name(channel)
    try:
        history_page = next(
            slack_client.fetch_channel_history(
                variant=variant, channel_id=channel["id"], limit=1
            )
        )
    except SlackApiError as e:
        if _error_slug(e) == "not_in_channel":
            return _caveat_output(
                f"Scope accepted; bot not in #{name}",
                "Slack accepted the history scope, but the bot is not in the "
                "channel, so no message or thread was read.",
            )
        _raise_for_slack_api_error(
            e, denied=rows.history_denied, denied_row=rows.history_denied_row
        )
    messages = history_page.messages
    thread_ts = messages[0].get("ts") if messages else None
    if not thread_ts:
        return _caveat_output(
            f"Read #{name}; it has no messages",
            "Message reads work, but the channel is empty, so thread reads were "
            "not tested.",
        )
    try:
        next(
            slack_client.fetch_thread_replies(
                variant=variant, channel_id=channel["id"], thread_ts=thread_ts
            )
        )
    except SlackApiError as e:
        _raise_for_slack_api_error(
            e, denied=rows.replies_denied, denied_row=rows.replies_denied_row
        )
    return CheckOutput(summary=f"Read a thread in #{name}")


class _SlackCheck(CapabilityCheck[SlackConnectorConfig]):
    def __init__(
        self,
        *,
        check_id: str,
        display_name: str,
        remediation: str,
        capability: CredentialCapability = CredentialCapability.INDEXING,
        required: bool = True,
        requires_connector_config: bool = False,
        timeout_seconds: float | None = None,
        validates_binding: bool = False,
        discovery: bool = False,
        fails_when_unreachable: bool = False,
    ) -> None:
        super().__init__(
            capability=capability,
            check_id=check_id,
            display_name=display_name,
            row_id=_ROW_IDS.get(check_id),
            depends_on=_DEPENDS_ON.get(check_id, ()),
            required=required,
            requires_connector_instance=False,
            requires_connector_config=requires_connector_config,
            timeout_seconds=timeout_seconds,
            remediation=remediation,
            docs_link=_SLACK_DOCS_LINK,
            validates_binding=validates_binding,
            discovery=discovery,
            fails_when_unreachable=fails_when_unreachable,
        )


class _TokenAuthCheck(_SlackCheck):
    """Rejects non-bot token shapes, then probes ``auth.test``."""

    def __init__(self) -> None:
        super().__init__(
            check_id=_AUTH_CHECK_ID,
            display_name="Sign in to Slack",
            remediation=(
                "Create a bot token (`xoxb-...`) for the Slack app and paste "
                "it into the credential."
            ),
            validates_binding=True,
            fails_when_unreachable=True,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        token = context.credential_json.get(_BOT_TOKEN_KEY)
        if not token or not isinstance(token, str):
            raise CredentialInvalidError(
                "Slack credential is missing the `slack_bot_token` field.",
                summary="Account has no bot token",
                description=(
                    "The account has no Slack bot token.\nPaste the Bot User OAuth "
                    "Token into the Slack Bot Token field of the account."
                ),
            )
        if not token.startswith(_BOT_TOKEN_PREFIX):
            raise CredentialInvalidError(
                "The Slack credential does not look like a bot token (expected "
                "an `xoxb-` prefix). User and app-level tokens cannot join and "
                "read channels the way indexing requires.",
                summary="Token is not a bot token",
                description=(
                    "The token does not start with xoxb-.\nCopy the Bot User OAuth "
                    "Token from the app's OAuth & Permissions page."
                ),
            )
        try:
            auth = _auth_test(_slack_client(context))
        except (URLError, ConnectionError, IncompleteRead) as e:
            raise UnreachableValidationError(
                f"Onyx cannot connect to Slack: {e}",
                summary="Cannot reach Slack",
                description=(
                    "The connection to Slack failed.\nCheck that the server can "
                    "reach slack.com."
                ),
            ) from e
        if auth.user and auth.team:
            return CheckOutput(summary=f"Signed in as @{auth.user} in {auth.team}")
        return CheckOutput(summary="Signed in to Slack")


class _ChannelPatternsCheck(_SlackCheck):
    """Verifies the channel include and exclude regexes compile. Indexing
    cannot filter channels with a malformed regex."""

    config_class = SlackConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            check_id="slack_channel_patterns",
            display_name="Compile channel patterns",
            remediation="Fix the channel regex in the connector settings.",
            requires_connector_config=True,
        )

    def applies(self, form_state: FormState[SlackConnectorConfig]) -> bool:
        return bool(_patterns(form_state.config))

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        patterns = _patterns(self.config(context))
        for pattern in patterns:
            try:
                validate_channel_regexes([pattern.pattern], pattern.label)
            except ConnectorValidationError as e:
                raise ConnectorValidationError(
                    e.message,
                    summary=pattern.line,
                    description=(
                        "Indexing cannot filter channels with a pattern that does "
                        "not compile."
                    ),
                ) from e
        if len(patterns) == 1:
            return CheckOutput(summary="1 pattern is valid")
        return CheckOutput(summary=f"All {len(patterns)} patterns are valid")


class _ChannelPattern(BaseModel):
    pattern: str
    # How the message and the row name the pattern's field.
    label: str
    line: str


def _patterns(config: SlackConnectorConfig) -> list[_ChannelPattern]:
    """The regex-mode patterns: the channels, then the excluded channels."""
    patterns: list[_ChannelPattern] = []
    if config.channel_regex_enabled:
        patterns += [
            _ChannelPattern(
                pattern=pattern,
                label="channel",
                line=f"Invalid channel pattern: {pattern}",
            )
            for pattern in config.channels or []
        ]
    if config.exclude_channel_regex_enabled:
        patterns += [
            _ChannelPattern(
                pattern=pattern,
                label="excluded channel",
                line=f"Invalid exclude pattern: {pattern}",
            )
            for pattern in config.exclude_channels or []
        ]
    return patterns


class _GridWorkspaceListingCheck(_SlackCheck):
    """Counts the Grid org's workspaces. Does not apply off Grid."""

    def __init__(self) -> None:
        super().__init__(
            check_id=_GRID_LISTING_CHECK_ID,
            display_name="List Grid workspaces",
            remediation=_ADD_SCOPE_REMEDIATION.format(scope="team:read"),
            validates_binding=True,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        slack_client = _slack_client(context)
        if not _auth_test(slack_client).enterprise_id:
            raise CheckNotApplicableError(_NOT_ON_GRID_MESSAGE)
        count = 0
        more = False
        try:
            for page in islice(slack_client.list_teams(), _TEAM_COUNT_PAGE_LIMIT):
                count += len(page.teams)
                more = bool(page.response_metadata.next_cursor)
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                denied=(
                    "Slack Enterprise Grid org detected, but the bot token cannot "
                    "list workspaces (`auth.teams.list`). Channel enumeration is "
                    "per-workspace on Grid, so indexing coverage would be "
                    "incomplete."
                ),
                denied_row=_RowText(
                    summary="Bot cannot list Grid workspaces",
                    description=(
                        "Indexing would miss channels in other workspaces.\n"
                        + _need("team:read")
                    ),
                ),
            )
        if count == 0:
            raise _no_grid_workspaces_error()
        shown = f"{count}+" if more else count
        return CheckOutput(
            summary=f"{_counted(shown, 'workspace', 'workspaces')} in the org"
        )


class _PublicChannelListingCheck(_SlackCheck):
    """Lists one public channel, then reads its metadata.

    The ``conversations.info`` probe mirrors checkpoint resume, which
    re-resolves channels by id.
    """

    def __init__(self) -> None:
        super().__init__(
            check_id=_PUBLIC_LISTING_CHECK_ID,
            display_name="List public channels",
            remediation=_ADD_SCOPE_REMEDIATION.format(scope="channels:read"),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        slack_client = _slack_client(context)
        try:
            channel = _find_channel(
                slack_client, SlackChannelVariant.PUBLIC, exclude_archived=None
            )
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e, denied=_PUBLIC_LISTING_DENIED, denied_row=_PUBLIC_LISTING_DENIED_ROW
            )
        if channel is None:
            return _caveat_output(
                f"No public channel in first {_CHANNEL_SCAN_BOUND} scanned",
                "Channel listing works, but the check found no public channel, so "
                "it did not test the details read that indexing uses when it "
                "resumes.",
            )
        try:
            slack_client.fetch_channel_info(channel_id=channel["id"])
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                denied=(
                    "The bot token cannot read channel metadata "
                    "(`conversations.info`), which indexing uses to resolve "
                    "channels when resuming from a checkpoint."
                ),
                denied_row=_RowText(
                    summary="Bot cannot read channel details",
                    description=(
                        f"Resumed indexing runs would fail.\n{_need('channels:read')}"
                    ),
                ),
            )
        return CheckOutput(
            summary=f"Found #{_channel_name(channel)} and read its details"
        )


class _PrivateChannelListingCheck(_SlackCheck):
    """Searches for one private channel.

    Not required: indexing does not fail without ``groups:read``, it silently
    falls back to public channels only.
    """

    def __init__(self) -> None:
        super().__init__(
            check_id=_PRIVATE_LISTING_CHECK_ID,
            display_name="List private channels",
            required=False,
            remediation=_ADD_SCOPE_REMEDIATION.format(scope="groups:read"),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        try:
            private_channel = _find_channel(
                _slack_client(context),
                SlackChannelVariant.PRIVATE,
                exclude_archived=None,
            )
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                denied=(
                    "The bot token cannot list private channels. Indexing does "
                    "NOT fail on this: it silently falls back to public channels "
                    "only, so private channels would be skipped without any error."
                ),
                denied_row=_PRIVATE_LISTING_DENIED_ROW,
            )
        if private_channel is None:
            return _no_private_channel_output()
        return CheckOutput(
            summary=f"Found private channel #{_channel_name(private_channel)}"
        )


def _public_channel_to_sample(slack_client: SlackSourceOperations) -> dict[str, Any]:
    """A public channel to read, preferring one the bot is in, from the
    bounded search."""
    try:
        pages = slack_client.list_channels(
            variant=SlackChannelVariant.PUBLIC,
            channel_types=["public_channel"],
            exclude_archived=True,
            limit=_CHANNEL_SCAN_PAGE_SIZE,
        )
        channels: list[dict[str, Any]] = []
        for page in islice(pages, _CHANNEL_SCAN_PAGE_LIMIT):
            channels += page.channels
            if any(channel.get("is_member") for channel in page.channels):
                break
    except SlackApiError as e:
        _raise_for_slack_api_error(
            e, denied=_PUBLIC_LISTING_DENIED, denied_row=_PUBLIC_LISTING_DENIED_ROW
        )
    if not channels:
        raise InconclusiveValidationError(
            "No public channels are visible to the bot in the first "
            f"{_CHANNEL_SCAN_BOUND} channels that Slack scanned, so "
            "message-history access could not be probed.",
            summary="No public channel found to test",
            description=(
                f"Slack listed no public channel in the first {_CHANNEL_SCAN_BOUND} "
                "scanned.\nRe-run the checks."
            ),
        )
    # On a non-member channel the probe still proves the scope:
    # ``not_in_channel`` sorts after ``missing_scope``.
    return next(
        (channel for channel in channels if channel.get("is_member")), channels[0]
    )


class _MessageHistoryReadCheck(_SlackCheck):
    """Reads one message page and one thread from a public channel."""

    def __init__(self) -> None:
        super().__init__(
            check_id="slack_message_history_read",
            display_name="Sample public messages",
            remediation=_ADD_SCOPE_REMEDIATION.format(scope="channels:history"),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        slack_client = _slack_client(context)
        return _probe_channel_history(
            slack_client,
            SlackChannelVariant.PUBLIC,
            _public_channel_to_sample(slack_client),
            _HistoryRows(
                history_denied=(
                    "The bot token cannot read channel messages "
                    "(`conversations.history`), which is the core indexing "
                    "operation. Grant `channels:history` (and `groups:history` if "
                    "private channels should be indexed)."
                ),
                history_denied_row=_RowText(
                    summary="Bot cannot read channel messages",
                    description=(
                        "Reading messages is the core of indexing.\n"
                        + _need("channels:history")
                    ),
                ),
                replies_denied=(
                    "The bot token cannot read thread replies "
                    "(`conversations.replies`), which indexing needs to capture "
                    "threads. Grant `channels:history` (and `groups:history` if "
                    "private channels should be indexed)."
                ),
                replies_denied_row=_RowText(
                    summary="Bot cannot read thread replies",
                    description=(
                        "Indexing would miss every reply in a thread.\n"
                        + _need("channels:history")
                    ),
                ),
            ),
        )


class _PrivateMessageHistoryReadCheck(_SlackCheck):
    """Reads one message page and one thread from a private channel.

    A token with ``channels:history`` but not ``groups:history`` passes the
    public probe while every private channel the bot is in fails mid-indexing.
    It runs after the private listing, which reports a listing failure.
    """

    def __init__(self) -> None:
        super().__init__(
            check_id="slack_private_message_history_read",
            display_name="Sample private messages",
            remediation=_ADD_SCOPE_REMEDIATION.format(scope="groups:history"),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        slack_client = _slack_client(context)
        return _probe_channel_history(
            slack_client,
            SlackChannelVariant.PRIVATE,
            _first_private_channel(
                slack_client,
                "Invite the bot to a private channel to index its messages.",
            ),
            _HistoryRows(
                history_denied=(
                    "The bot token cannot read private-channel messages "
                    "(`conversations.history`). Private channels ARE visible to "
                    "the bot, so indexing will attempt them and fail. Grant "
                    "`groups:history`."
                ),
                history_denied_row=_RowText(
                    summary="Bot cannot read private messages",
                    description=(
                        "Indexing would try these channels and fail.\n"
                        + _need("groups:history")
                    ),
                ),
                replies_denied=(
                    "The bot token cannot read private-channel thread replies "
                    "(`conversations.replies`), which indexing needs to capture "
                    "threads. Grant `groups:history`."
                ),
                replies_denied_row=_RowText(
                    summary="Bot cannot read private replies",
                    description=(
                        "Indexing would miss every reply in a thread.\n"
                        + _need("groups:history")
                    ),
                ),
            ),
        )


class _ChannelJoinScopeCheck(_SlackCheck):
    """Verifies the ``channels:join`` scope via the ``X-OAuth-Scopes`` header.

    Header-based instead of a functional probe: actually calling
    ``conversations.join`` would join a channel in the customer's workspace as a
    side effect (the operation carries a matching ``untested`` annotation). Not
    required: a bot manually invited to every configured channel indexes fine
    without the scope.
    """

    def __init__(self) -> None:
        super().__init__(
            check_id="slack_channel_join_scope",
            display_name="Join public channels",
            required=False,
            remediation=(
                _ADD_SCOPE_REMEDIATION.format(scope="channels:join")
                + " Alternatively, manually invite the bot (`/invite @<bot>`) "
                "to every channel that should be indexed. Do not dismiss this "
                "warning unless the bot is already a member of every such "
                "channel."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        granted_scopes = _auth_test(_slack_client(context)).granted_scopes
        if granted_scopes is None:
            raise InconclusiveValidationError(
                "Slack did not return the `X-OAuth-Scopes` header, so the "
                "`channels:join` scope could not be verified.",
                summary="Slack did not report the token's scopes",
                description="Slack sent no scope list.\nRe-run the checks.",
            )
        if "channels:join" not in granted_scopes:
            raise InsufficientPermissionsError(
                "The bot token lacks the `channels:join` scope, so Onyx cannot "
                "automatically join public channels. This is a warning, but it "
                "usually still requires action: every public channel the bot "
                "has not been invited to WILL fail to index. Either add the "
                "`channels:join` scope and reinstall the app, or manually "
                "invite the bot (`/invite @<bot>`) to every channel that "
                "should be indexed.",
                summary="Token lacks the channels:join scope",
                description=(
                    "Indexing fails on every public channel that the bot was not "
                    f"invited to.\n{_need('channels:join')}"
                ),
            )
        return CheckOutput(summary="Has the channels:join scope")


class _UserProfileReadCheck(_SlackCheck):
    """Lists one user, then reads one profile.

    Not required: indexing still works without ``users:read``, but message
    authors appear as raw Slack ids instead of names.
    """

    def __init__(self) -> None:
        super().__init__(
            check_id="slack_user_profile_read",
            display_name="Read user profiles",
            required=False,
            remediation=_ADD_SCOPE_REMEDIATION.format(scope="users:read"),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        slack_client = _slack_client(context)
        team = _first_grid_team(slack_client)
        try:
            users_page = next(
                slack_client.list_users(limit=1, team_id=team.id if team else None)
            )
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                denied=(
                    "The bot token cannot read user profiles (`users.list`). "
                    "Indexing still works, but message authors appear as raw Slack "
                    "ids instead of names."
                ),
                denied_row=_RowText(
                    summary="Bot cannot read user profiles",
                    description=(
                        "Indexing still works, but message authors show as Slack "
                        f"IDs instead of names.\n{_need('users:read')}"
                    ),
                ),
            )
        members = users_page.members
        if not members:
            raise InconclusiveValidationError(
                "Slack returned no user, so the check did not read a user "
                "profile (`users.info`).",
                summary="No users found to test",
                description="Slack returned no user.",
            )
        try:
            slack_client.fetch_user_info(members[0]["id"])
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                denied=(
                    "The bot token cannot read a single user profile "
                    "(`users.info`), which indexing uses to resolve message "
                    "authors. Authors would appear as raw Slack ids instead of "
                    "names."
                ),
                denied_row=_RowText(
                    summary="Bot cannot read a user profile",
                    description=(
                        "Message authors would show as Slack IDs.\n"
                        + _need("users:read")
                    ),
                ),
            )
        return CheckOutput(summary="User names readable")


class _ConfiguredChannelsVisibleCheck(_SlackCheck):
    """Verifies every configured channel id or name is visible to the bot.
    Composes the same enumeration the connector runs (``get_channels`` /
    ``get_channels_across_teams``). Some not visible is INCOMPLETE, since
    indexing skips them and indexes the rest; none visible FAILS."""

    config_class = SlackConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            check_id="slack_configured_channels_visible",
            display_name="Find selected channels",
            requires_connector_config=True,
            timeout_seconds=_CHANNEL_ENUMERATION_TIMEOUT_SECONDS,
            remediation=(
                "Fix the channel name, or invite the bot to the private "
                "channel (`/invite @<bot>` in Slack) and grant `groups:read`."
            ),
        )

    def applies(self, form_state: FormState[SlackConnectorConfig]) -> bool:
        # No channel filter indexes whatever is visible; patterns are compiled
        # by ``slack_channel_patterns``, not matched here.
        config = form_state.config
        return bool(config.channels) and not config.channel_regex_enabled

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        configured = sorted(
            set(normalize_channel_entries(self.config(context).channels or []))
        )
        slack_client = _slack_client(context)
        team_ids: list[str] | None = None
        if _auth_test(slack_client).enterprise_id:
            try:
                team_ids = list_grid_team_ids(slack_client)
            except SlackApiError as e:
                _raise_for_slack_api_error(
                    e,
                    denied=(
                        "On Enterprise Grid, listing channels requires enumerating "
                        "workspaces first (`auth.teams.list`), which needs the "
                        "`team:read` scope."
                    ),
                    denied_row=_RowText(
                        summary="Bot cannot list Grid workspaces",
                        description=(
                            "On Enterprise Grid, channels are listed per workspace, "
                            f"and the bot cannot list workspaces.\n{_need('team:read')}"
                        ),
                    ),
                )
        try:
            all_channels = (
                get_channels_across_teams(slack_client=slack_client, team_ids=team_ids)
                if team_ids is not None
                else get_channels(slack_client=slack_client)
            )
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                denied=(
                    "The bot token cannot enumerate channels "
                    "(`conversations.list`), so the configured channels could not "
                    "be verified."
                ),
                denied_row=_RowText(
                    summary="Bot cannot list channels",
                    description=(
                        "The check cannot list the workspace's channels.\n"
                        + _need("channels:read")
                    ),
                ),
            )
        visible_channels = channel_keys(all_channels)
        missing = [entry for entry in configured if entry not in visible_channels]
        if not missing:
            return CheckOutput(
                summary=f"All {_counted(len(configured), 'selected channel', 'selected channels')} found"
            )
        message = (
            f"Configured channels are not visible to the bot: {missing}. Each may "
            "be a typo, an archived channel, or a private channel the bot has not "
            "been invited to (private channels also require the `groups:read` "
            "scope to be listed)."
        )
        names = ", ".join(missing)
        if len(missing) == len(configured):
            raise ConnectorValidationError(
                message,
                summary="No selected channel found",
                description=(
                    "None of the selected channels is visible to the bot.\n"
                    f"Not visible: {names}."
                ),
            )
        return CheckOutput(
            summary=(
                f"{_counted(len(missing), 'selected channel', 'selected channels')} "
                "not visible"
            ),
            description=(
                f"Indexing skips channels the bot cannot see: {names}.\nFor a "
                "private channel, invite the bot and add the `groups:read` bot "
                "scope."
            ),
            partial=True,
        )


class _ListedChannel(BaseModel):
    channel: dict[str, Any]
    # The Grid workspace the channel was listed in, which tells two
    # same-named channels apart. None off Grid.
    workspace: str | None


def _grid_workspaces(slack_client: SlackSourceOperations) -> dict[str, str | None]:
    """Grid team id to workspace name via ``auth.teams.list``."""
    return {
        team["id"]: team.get("name")
        for page in slack_client.list_teams()
        for team in page.teams
        if team.get("id")
    }


def _iter_public_channels(
    slack_client: SlackSourceOperations,
) -> Iterator[_ListedChannel]:
    """Every unarchived public channel, read page by page. On Enterprise Grid,
    lists each workspace in turn, as the connector does. A channel shared into
    several workspaces is listed once, by id."""
    workspaces: dict[str | None, str | None] = (
        {**_grid_workspaces(slack_client)}
        if _auth_test(slack_client).enterprise_id
        else {None: None}
    )
    seen_ids: set[str] = set()
    for team_id, workspace in workspaces.items():
        for page in slack_client.list_channels(
            variant=SlackChannelVariant.PUBLIC,
            channel_types=["public_channel"],
            exclude_archived=True,
            team_id=team_id,
        ):
            for channel in page.channels:
                if channel["id"] in seen_ids:
                    continue
                seen_ids.add(channel["id"])
                yield _ListedChannel(channel=channel, workspace=workspace)


class _ReadableChannelListingCheck(_SlackCheck):
    """Lists the public channels the bot can index, as options for the channels
    field: the discovery step of the public listing's row."""

    def __init__(self) -> None:
        super().__init__(
            check_id="slack_readable_channel_listing",
            display_name="List public channels",
            remediation=_ADD_SCOPE_REMEDIATION.format(scope="channels:read"),
            discovery=True,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        try:
            # The id survives a rename. The label is the name the admin reads.
            finding: OptionsFinding = bounded_options(
                _iter_public_channels(_slack_client(context)),
                key=CheckFindingKey.READABLE_CHANNELS,
                field_name=_CHANNELS_FIELD,
                value=lambda listed: listed.channel["id"],
                label=lambda listed: listed.channel["name"],
                detail=lambda listed: listed.workspace,
            )
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                denied="The bot token cannot list public channels (`conversations.list`).",
                denied_row=_PUBLIC_LISTING_DENIED_ROW,
            )
        if finding.truncated:
            return CheckOutput(
                summary=f"{MAX_FINDING_OPTIONS}+ public channels found",
                findings=[finding],
                advisories=[
                    CheckAdvisory(
                        message=(
                            f"The list shows the first {MAX_FINDING_OPTIONS} "
                            "public channels only. Type the name of a channel that "
                            "the list does not show."
                        )
                    )
                ],
            )
        return CheckOutput(
            summary=(
                f"{_counted(len(finding.options), 'public channel', 'public channels')} "
                "found"
            ),
            findings=[finding],
        )


class _PermSyncChannelListingCheck(_SlackCheck):
    """Lists public channels under the permission-sync capability.

    Doc sync enumerates every channel to build per-channel access lists and
    fails outright when it cannot; this is the same ``channels:read`` scope the
    INDEXING listing check probes, verified under the capability whose verdict
    depends on it.
    """

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="slack_perm_sync_channel_listing",
            display_name="List public channels",
            remediation=_ADD_SCOPE_REMEDIATION.format(scope="channels:read"),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        try:
            channel = _find_channel(
                _slack_client(context),
                SlackChannelVariant.PUBLIC,
                exclude_archived=None,
            )
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                denied=(
                    "The bot token cannot list channels (`conversations.list`), "
                    "which permission sync requires to enumerate channels and "
                    "build per-channel access lists."
                ),
                denied_row=_RowText(
                    summary="Bot cannot list public channels",
                    description=(
                        "Permission sync cannot build channel access without "
                        f"listing channels.\n{_need('channels:read')}"
                    ),
                ),
            )
        if channel is None:
            return _caveat_output(
                f"No public channel in first {_CHANNEL_SCAN_BOUND} scanned",
                "Channel listing works, but the check found no public channel to list.",
            )
        return CheckOutput(summary=f"Found #{_channel_name(channel)}")


class _PermSyncPrivateChannelListingCheck(_SlackCheck):
    """Searches for one private channel under the permission-sync capability.

    Not required: doc sync has the same silent public-only fallback indexing has
    when private channels cannot be listed, so the capability degrades rather
    than breaks.
    """

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id=_PERM_SYNC_PRIVATE_LISTING_CHECK_ID,
            display_name="List private channels",
            required=False,
            remediation=_ADD_SCOPE_REMEDIATION.format(scope="groups:read"),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        try:
            private_channel = _find_channel(
                _slack_client(context),
                SlackChannelVariant.PRIVATE,
                exclude_archived=None,
            )
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                denied=(
                    "The bot token cannot list private channels. Permission sync "
                    "does NOT fail on this: it silently syncs public channels "
                    "only, so private-channel access lists are never created or "
                    "updated. Previously indexed private documents keep stale "
                    "access lists, so users removed from a private channel keep "
                    "access in Onyx."
                ),
                denied_row=_RowText(
                    summary="Bot cannot list private channels",
                    description=(
                        "Private channel access would not sync, and old access "
                        f"would stay.\n{_need('groups:read')}"
                    ),
                ),
            )
        if private_channel is None:
            return _no_private_channel_output()
        return CheckOutput(
            summary=f"Found private channel #{_channel_name(private_channel)}"
        )


class _UserEmailVisibilityCheck(_SlackCheck):
    """Samples users and requires at least one visible email address."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="slack_user_email_visibility",
            display_name="Read user emails",
            remediation=(
                _ADD_SCOPE_REMEDIATION.format(scope="users:read.email")
                + " Slack only returns email fields once the app is "
                "reinstalled."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        slack_client = _slack_client(context)
        team = _first_grid_team(slack_client)
        try:
            users_page = next(
                slack_client.list_users(
                    limit=_EMAIL_PROBE_PAGE_SIZE, team_id=team.id if team else None
                )
            )
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                denied=(
                    "The bot token cannot list users (`users.list`), which "
                    "permission sync requires to map Slack members to Onyx users "
                    "by email."
                ),
                denied_row=_RowText(
                    summary="Bot cannot list users",
                    description=(
                        "Permission sync cannot map Slack members to users.\n"
                        + _need("users:read")
                    ),
                ),
            )
        human_members = [
            member
            for member in users_page.members
            if not member.get("is_bot")
            and not member.get("deleted")
            and member.get("id") != "USLACKBOT"
        ]
        if not human_members:
            raise InconclusiveValidationError(
                "`users.list` returned no active human members to sample, so "
                "email visibility could not be verified.",
                summary=f"No active users in the first {_EMAIL_PROBE_PAGE_SIZE}",
                description=(
                    f"The first {_EMAIL_PROBE_PAGE_SIZE} users are all bots or "
                    "deactivated.\nRe-run the checks after people join the "
                    "workspace."
                ),
            )
        with_email = sum(
            1 for member in human_members if member.get("profile", {}).get("email")
        )
        if not with_email:
            raise InsufficientPermissionsError(
                "`users.list` succeeded but returned no email addresses, so "
                "permission sync cannot map Slack members to Onyx users. This "
                "is how a missing `users:read.email` scope manifests -- Slack "
                "omits the email field instead of raising a scope error.",
                summary="No user emails visible",
                description=(
                    "Permission sync maps Slack members to users by email.\n"
                    + _need("users:read.email")
                ),
            )
        return CheckOutput(
            summary=f"Emails visible for {with_email} of {len(human_members)} users"
        )


class _PrivateChannelMemberListingCheck(_SlackCheck):
    """Lists one private channel's members, then resolves one member.

    The ``users.info`` step mirrors doc sync's fallback for members missing from
    the workspace user list (external users). It runs after the private
    listing, which reports a listing failure.
    """

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="slack_private_channel_member_listing",
            display_name="List channel members",
            remediation=(
                _ADD_SCOPE_REMEDIATION.format(scope="groups:read")
                + " Member-to-user resolution also needs `users:read`."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        slack_client = _slack_client(context)
        channel = _first_private_channel(
            slack_client, "Invite the bot to a private channel to sync its members."
        )
        name = _channel_name(channel)
        try:
            members_page = next(
                slack_client.list_channel_members(channel_id=channel["id"])
            )
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                denied=(
                    "The bot token cannot list private-channel members "
                    "(`conversations.members`), which permission sync requires to "
                    "build per-channel member ACLs."
                ),
                denied_row=_RowText(
                    summary="Bot cannot list channel members",
                    description=(
                        "Permission sync cannot tell who is in a private channel.\n"
                        + _need("groups:read")
                    ),
                ),
            )
        members = members_page.members
        if not members:
            raise InconclusiveValidationError(
                "Slack returned no member for the private channel that the "
                "check selected, so the check did not read a member profile "
                "(`users.info`).",
                summary=f"No members found in #{name}",
                description="Slack returned no member for the channel.",
            )
        try:
            slack_client.fetch_user_info(members[0])
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                denied=(
                    "The bot token cannot resolve channel members to user "
                    "profiles (`users.info`), which permission sync uses for "
                    "members missing from the workspace user list."
                ),
                denied_row=_RowText(
                    summary="Bot cannot read member profiles",
                    description=(
                        "Permission sync cannot resolve members missing from the "
                        f"user list, such as external users.\n{_need('users:read')}"
                    ),
                ),
            )
        count = (
            f"{len(members)}+"
            if members_page.response_metadata.next_cursor
            else len(members)
        )
        return CheckOutput(
            summary=f"Listed {_counted(count, 'member', 'members')} of #{name}"
        )


class _GridPublicChannelScopingCheck(_SlackCheck):
    """Verifies per-workspace user listing on Enterprise Grid.

    Not required: without it, permission sync still runs but silently marks
    every public channel visible org-wide in Onyx.
    """

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="slack_grid_public_channel_scoping",
            display_name="List users per workspace",
            required=False,
            remediation=(
                _ADD_SCOPE_REMEDIATION.format(scope="users:read")
                + " Also grant `users:read.email` and `team:read` so "
                "per-workspace user lists can be built."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        slack_client = _slack_client(context)
        team = _first_grid_team(slack_client)
        if team is None:
            # Off-Grid, public channels are workspace-public by design.
            raise CheckNotApplicableError(_NOT_ON_GRID_MESSAGE)
        try:
            next(slack_client.list_users(limit=1, team_id=team.id))
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                denied=(
                    "On Enterprise Grid, per-workspace user listing (`users.list` "
                    "with `team_id`) scopes public channels to their workspaces. "
                    "Without it, permission sync silently marks every public "
                    "channel visible org-wide in Onyx (over-sharing)."
                ),
                denied_row=_RowText(
                    summary="Bot cannot list users per workspace",
                    description=(
                        "Permission sync then shows every public channel to the "
                        f"whole org, not only to its workspace.\n{_need('users:read')}"
                    ),
                ),
            )
        return CheckOutput(summary=f"Listed users in workspace {team.name or team.id}")


def build_slack_indexing_checks() -> list[CapabilityCheck]:
    """Returns the INDEXING capability checks for Slack, in the design's row
    order."""
    return [
        _TokenAuthCheck(),
        _ChannelPatternsCheck(),
        _GridWorkspaceListingCheck(),
        _PublicChannelListingCheck(),
        _MessageHistoryReadCheck(),
        _ChannelJoinScopeCheck(),
        _ConfiguredChannelsVisibleCheck(),
        _PrivateChannelListingCheck(),
        _PrivateMessageHistoryReadCheck(),
        _UserProfileReadCheck(),
        _ReadableChannelListingCheck(),
    ]


def build_slack_doc_permission_sync_checks() -> list[CapabilityCheck]:
    """Returns the DOC_PERMISSION_SYNC capability checks for Slack.

    Registered via the EE capability-check hook; defined here so the probe
    logic and remediation text live with the connector.
    """
    return [
        _PermSyncChannelListingCheck(),
        _PermSyncPrivateChannelListingCheck(),
        _PrivateChannelMemberListingCheck(),
        _UserEmailVisibilityCheck(),
        _GridPublicChannelScopingCheck(),
    ]
