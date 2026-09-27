"""Capability checks for the Slack connector.

Each check probes one permission assumption the connector makes at indexing or
doc-permission-sync time by composing the same gateway operations production
code calls (``limit=1`` where possible). Checks need no connector instance: the
runner constructs the registered ``SlackSourceOperations`` gateway from the
credential and hands it to every check via the context, so checks run
config-less at credential-creation time (except the configured-channels check,
which declares its config requirement and is skipped until one exists).

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

from typing import Any, NoReturn

from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.slack.connector import (
    get_channels,
    get_channels_across_teams,
    list_grid_team_ids,
)
from onyx.connectors.slack.source_operations import (
    SlackApiError,
    SlackAuthTestResponse,
    SlackChannelVariant,
    SlackSourceOperations,
)

_SLACK_DOCS_LINK = (
    "https://docs.onyx.app/admins/connectors/official/slack/slack_indexed"
)

_ADD_SCOPE_REMEDIATION = (
    "Add the `{scope}` bot scope under OAuth & Permissions in the Slack app "
    "settings and reinstall the app to the workspace."
)

# Page size when scanning for a channel to probe message history against; a
# single page is plenty since any public channel works for the probe.
_HISTORY_PROBE_CHANNEL_PAGE_SIZE = 20

# Page size when sampling users for email visibility. Workspaces commonly have
# many bot/deactivated users, so sample enough to nearly always include a human
# member.
_EMAIL_PROBE_PAGE_SIZE = 100

# Hang guard for the full-workspace channel enumeration, the one multi-page
# probe: triple the 600s ``CAPABILITY_CHECK_TIMEOUT_SECONDS`` default, since the
# gateway's redis-coordinated client also serves any concurrently running
# indexing job's rate-limit backoff.
_CHANNEL_ENUMERATION_TIMEOUT_SECONDS = 1800.0


def _slack_client(context: CapabilityCheckContext) -> SlackSourceOperations:
    """Returns the gateway the runner constructed for this run.

    A registered gateway that was not constructed is a programmer error in the
    runner, not a check outcome.
    """
    assert isinstance(context.source_operations, SlackSourceOperations), (
        "Bug: The runner constructs the registered gateway for migrated sources."
    )
    return context.source_operations


def _raise_for_slack_api_error(
    e: SlackApiError, missing_scope_message: str
) -> NoReturn:
    """Maps a Slack API error onto the validation-exception family.

    ``missing_scope_message`` is the check-specific explanation used when the
    error is ``missing_scope``.
    """
    error = e.response.get("error", "") if e.response is not None else ""
    if error == "missing_scope":
        needed = e.response.get("needed", "")
        message = missing_scope_message
        if needed:
            message += f" (Slack reported the missing scope as `{needed}`.)"
        raise InsufficientPermissionsError(message) from e
    if error in ("invalid_auth", "not_authed"):
        raise CredentialExpiredError(
            f"Invalid or expired Slack bot token ({error})."
        ) from e
    if error == "account_inactive":
        raise CredentialExpiredError(
            f"Slack workspace or bot user is deactivated ({error})."
        ) from e
    if error == "token_revoked":
        raise CredentialExpiredError(
            f"Slack bot token has been revoked ({error})."
        ) from e
    if error == "token_expired":
        raise CredentialExpiredError(f"Slack bot token has expired ({error}).") from e
    if error == "ratelimited":
        raise UnexpectedValidationError(
            "Slack rate limited the check; re-run the checks in a minute."
        ) from e
    raise UnexpectedValidationError(f"Unexpected Slack error `{error}`.") from e


def _auth_test(slack_client: SlackSourceOperations) -> SlackAuthTestResponse:
    try:
        return slack_client.check_auth()
    except SlackApiError as e:
        _raise_for_slack_api_error(e, "Slack bot token failed `auth.test`.")


def _first_grid_team_id(slack_client: SlackSourceOperations) -> str | None:
    """Returns the first workspace id of an Enterprise Grid org, None off-Grid.

    On Grid org installs ``users.list`` requires a ``team_id``, so user-facing
    checks call this to mirror the production call shape.
    """
    if not _auth_test(slack_client).enterprise_id:
        return None
    try:
        teams_page = next(slack_client.list_teams(limit=1))
    except SlackApiError as e:
        _raise_for_slack_api_error(
            e,
            "On Enterprise Grid, listing users requires enumerating workspaces "
            "first (`auth.teams.list`), which needs the `team:read` scope.",
        )
    teams = teams_page.teams
    if not teams:
        raise UnexpectedValidationError(
            "`auth.teams.list` returned no workspaces for this Enterprise Grid org."
        )
    return str(teams[0]["id"])


def _first_private_channel(
    slack_client: SlackSourceOperations,
) -> dict[str, Any] | None:
    """Returns one private channel the bot is in, None when none are in scope.

    None covers an empty listing and a ``missing_scope`` failure alike: without
    ``groups:read`` no private channels are in scope, and the non-required
    private-listing checks own that finding. Any other listing error maps
    through ``_raise_for_slack_api_error``; a rate-limited listing must not turn
    into a pass of a required check.
    """
    try:
        listing = next(
            slack_client.list_channels(
                variant=SlackChannelVariant.PRIVATE,
                channel_types=["private_channel"],
                exclude_archived=True,
                limit=1,
            )
        )
    except SlackApiError as e:
        error = e.response.get("error", "") if e.response is not None else ""
        if error == "missing_scope":
            return None
        _raise_for_slack_api_error(e, "The bot token cannot list private channels.")
    channels = listing.channels
    return channels[0] if channels else None


def _probe_channel_history(
    slack_client: SlackSourceOperations,
    variant: SlackChannelVariant,
    channel_id: str,
    history_scope_message: str,
    replies_scope_message: str,
) -> None:
    """Reads one message page, then one thread, from the channel.

    ``not_in_channel`` passes: membership is not scope, and indexing self-joins
    public channels.
    """
    try:
        history_page = next(
            slack_client.fetch_channel_history(
                variant=variant, channel_id=channel_id, limit=1
            )
        )
    except SlackApiError as e:
        if e.response is not None and e.response.get("error") == "not_in_channel":
            return
        _raise_for_slack_api_error(e, history_scope_message)
    messages = history_page.messages
    if not messages:
        # An empty channel proves history access; there is no thread to read.
        return
    thread_ts = messages[0].get("ts")
    if not thread_ts:
        return
    try:
        next(
            slack_client.fetch_thread_replies(
                variant=variant, channel_id=channel_id, thread_ts=thread_ts
            )
        )
    except SlackApiError as e:
        _raise_for_slack_api_error(e, replies_scope_message)


class _TokenAuthCheck(CapabilityCheck):
    """Rejects non-bot token shapes, then probes ``auth.test``."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="slack_token_auth",
            display_name="Bot token is valid",
            requires_connector_instance=False,
            remediation=(
                "Create a bot token (`xoxb-...`) for the Slack app and paste "
                "it into the credential."
            ),
            docs_link=_SLACK_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        token = context.credential_json.get("slack_bot_token")
        if not token or not isinstance(token, str):
            raise CredentialInvalidError(
                "Slack credential is missing the `slack_bot_token` field."
            )
        if not token.startswith("xoxb-"):
            raise CredentialInvalidError(
                "The Slack credential does not look like a bot token (expected "
                "an `xoxb-` prefix). User and app-level tokens cannot join and "
                "read channels the way indexing requires."
            )
        _auth_test(_slack_client(context))


class _PublicChannelListingCheck(CapabilityCheck):
    """Lists one public channel, then reads its metadata.

    The ``conversations.info`` probe mirrors checkpoint resume, which
    re-resolves channels by id.
    """

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="slack_public_channel_listing",
            display_name="Public channels can be listed",
            requires_connector_instance=False,
            remediation=_ADD_SCOPE_REMEDIATION.format(scope="channels:read"),
            docs_link=_SLACK_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        slack_client = _slack_client(context)
        try:
            listing = next(
                slack_client.list_channels(
                    variant=SlackChannelVariant.PUBLIC,
                    channel_types=["public_channel"],
                    limit=1,
                )
            )
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                "The bot token cannot list public channels "
                "(`conversations.list`), which indexing requires to enumerate "
                "what to index.",
            )
        channels = listing.channels
        if not channels:
            # Listing itself is proven; an empty workspace leaves no channel
            # whose metadata could be read.
            return
        try:
            slack_client.fetch_channel_info(channel_id=channels[0]["id"])
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                "The bot token cannot read channel metadata "
                "(`conversations.info`), which indexing uses to resolve "
                "channels when resuming from a checkpoint.",
            )


class _PrivateChannelListingCheck(CapabilityCheck):
    """Lists one private channel.

    Not required: indexing does not fail without ``groups:read``, it silently
    falls back to public channels only.
    """

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="slack_private_channel_listing",
            display_name="Private channels can be listed",
            required=False,
            requires_connector_instance=False,
            remediation=_ADD_SCOPE_REMEDIATION.format(scope="groups:read"),
            docs_link=_SLACK_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        try:
            next(
                _slack_client(context).list_channels(
                    variant=SlackChannelVariant.PRIVATE,
                    channel_types=["private_channel"],
                    limit=1,
                )
            )
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                "The bot token cannot list private channels. Indexing does NOT "
                "fail on this: it silently falls back to public channels only, "
                "so private channels would be skipped without any error.",
            )


class _MessageHistoryReadCheck(CapabilityCheck):
    """Reads one message page and one thread from a public channel."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="slack_message_history_read",
            display_name="Channel messages can be read",
            requires_connector_instance=False,
            remediation=_ADD_SCOPE_REMEDIATION.format(scope="channels:history"),
            docs_link=_SLACK_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        slack_client = _slack_client(context)
        try:
            listing = next(
                slack_client.list_channels(
                    variant=SlackChannelVariant.PUBLIC,
                    channel_types=["public_channel"],
                    exclude_archived=True,
                    limit=_HISTORY_PROBE_CHANNEL_PAGE_SIZE,
                )
            )
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                "The bot token cannot list public channels "
                "(`conversations.list`), which indexing requires to enumerate "
                "what to index.",
            )
        channels = listing.channels
        if not channels:
            raise UnexpectedValidationError(
                "No public channels are visible to the bot, so message-history "
                "access could not be probed."
            )
        # Prefer a channel the bot is a member of; on a non-member channel the
        # probe still proves the scope because ``not_in_channel`` sorts after
        # ``missing_scope``.
        channel = next(
            (channel for channel in channels if channel.get("is_member")),
            channels[0],
        )
        _probe_channel_history(
            slack_client,
            SlackChannelVariant.PUBLIC,
            channel["id"],
            history_scope_message=(
                "The bot token cannot read channel messages "
                "(`conversations.history`), which is the core indexing "
                "operation. Grant `channels:history` (and `groups:history` if "
                "private channels should be indexed)."
            ),
            replies_scope_message=(
                "The bot token cannot read thread replies "
                "(`conversations.replies`), which indexing needs to capture "
                "threads. Grant `channels:history` (and `groups:history` if "
                "private channels should be indexed)."
            ),
        )


class _PrivateMessageHistoryReadCheck(CapabilityCheck):
    """Reads one message page and one thread from a private channel.

    A token with ``channels:history`` but not ``groups:history`` passes the
    public probe while every private channel the bot is in fails mid-indexing.
    Listing scope failures are deliberately not reported here: they belong to
    ``slack_private_channel_listing``, and without ``groups:read`` no private
    channels are in scope at all.
    """

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="slack_private_message_history_read",
            display_name="Private-channel messages can be read",
            requires_connector_instance=False,
            remediation=_ADD_SCOPE_REMEDIATION.format(scope="groups:history"),
            docs_link=_SLACK_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        slack_client = _slack_client(context)
        channel = _first_private_channel(slack_client)
        if channel is None:
            return
        _probe_channel_history(
            slack_client,
            SlackChannelVariant.PRIVATE,
            channel["id"],
            history_scope_message=(
                "The bot token cannot read private-channel messages "
                "(`conversations.history`). Private channels ARE visible to "
                "the bot, so indexing will attempt them and fail. Grant "
                "`groups:history`."
            ),
            replies_scope_message=(
                "The bot token cannot read private-channel thread replies "
                "(`conversations.replies`), which indexing needs to capture "
                "threads. Grant `groups:history`."
            ),
        )


class _ChannelJoinScopeCheck(CapabilityCheck):
    """Verifies the ``channels:join`` scope via the ``X-OAuth-Scopes`` header.

    Header-based instead of a functional probe: actually calling
    ``conversations.join`` would join a channel in the customer's workspace as a
    side effect (the operation carries a matching ``untested`` annotation). Not
    required: a bot manually invited to every configured channel indexes fine
    without the scope.
    """

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="slack_channel_join_scope",
            display_name="Bot can join public channels",
            required=False,
            requires_connector_instance=False,
            remediation=(
                _ADD_SCOPE_REMEDIATION.format(scope="channels:join")
                + " Alternatively, manually invite the bot (`/invite @<bot>`) "
                "to every channel that should be indexed. Do not dismiss this "
                "warning unless the bot is already a member of every such "
                "channel."
            ),
            docs_link=_SLACK_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        auth_response = _auth_test(_slack_client(context))
        granted_scopes = auth_response.granted_scopes
        if granted_scopes is None:
            raise UnexpectedValidationError(
                "Slack did not return the `X-OAuth-Scopes` header, so the "
                "`channels:join` scope could not be verified."
            )
        if "channels:join" not in granted_scopes:
            raise InsufficientPermissionsError(
                "The bot token lacks the `channels:join` scope, so Onyx cannot "
                "automatically join public channels. This is a warning, but it "
                "usually still requires action: every public channel the bot "
                "has not been invited to WILL fail to index. Either add the "
                "`channels:join` scope and reinstall the app, or manually "
                "invite the bot (`/invite @<bot>`) to every channel that "
                "should be indexed."
            )


class _GridWorkspaceListingCheck(CapabilityCheck):
    """Lists one Grid workspace when the org is an Enterprise Grid."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="slack_grid_workspace_listing",
            display_name="Enterprise Grid workspaces can be listed",
            requires_connector_instance=False,
            remediation=_ADD_SCOPE_REMEDIATION.format(scope="team:read"),
            docs_link=_SLACK_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        slack_client = _slack_client(context)
        if not _auth_test(slack_client).enterprise_id:
            return
        try:
            next(slack_client.list_teams(limit=1))
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                "Slack Enterprise Grid org detected, but the bot token cannot "
                "list workspaces (`auth.teams.list`). Channel enumeration is "
                "per-workspace on Grid, so indexing coverage would be "
                "incomplete.",
            )


class _UserProfileReadCheck(CapabilityCheck):
    """Lists one user, then reads one profile.

    Not required: indexing still works without ``users:read``, but message
    authors appear as raw Slack ids instead of names.
    """

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="slack_user_profile_read",
            display_name="User profiles can be read",
            required=False,
            requires_connector_instance=False,
            remediation=_ADD_SCOPE_REMEDIATION.format(scope="users:read"),
            docs_link=_SLACK_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        slack_client = _slack_client(context)
        team_id = _first_grid_team_id(slack_client)
        try:
            users_page = next(slack_client.list_users(limit=1, team_id=team_id))
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                "The bot token cannot read user profiles (`users.list`). "
                "Indexing still works, but message authors appear as raw Slack "
                "ids instead of names.",
            )
        members = users_page.members
        if not members:
            return
        try:
            slack_client.fetch_user_info(members[0]["id"])
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                "The bot token cannot read a single user profile "
                "(`users.info`), which indexing uses to resolve message "
                "authors. Authors would appear as raw Slack ids instead of "
                "names.",
            )


class _ConfiguredChannelsVisibleCheck(CapabilityCheck):
    """Verifies every configured channel name is visible to the bot.

    Existed only as commented-out code in ``validate_connector_settings``
    (removed as too slow for a synchronous request); resurrected here where slow
    runs are acceptable. Composes the same enumeration the connector runs
    (``get_channels`` / ``get_channels_across_teams``).
    """

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="slack_configured_channels_visible",
            display_name="Configured channels are visible to the bot",
            requires_connector_instance=False,
            requires_connector_config=True,
            timeout_seconds=_CHANNEL_ENUMERATION_TIMEOUT_SECONDS,
            remediation=(
                "Fix the channel name, or invite the bot to the private "
                "channel (`/invite @<bot>` in Slack) and grant `groups:read`."
            ),
            docs_link=_SLACK_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config = context.connector_specific_config or {}
        channels_to_include = config.get("channels")
        if not channels_to_include:
            # No channel filter configured; whatever is visible gets indexed.
            return
        if config.get("channel_regex_enabled"):
            # Regex includes match dynamically; existence cannot be pre-checked.
            return
        slack_client = _slack_client(context)
        try:
            if _auth_test(slack_client).enterprise_id:
                team_ids = list_grid_team_ids(slack_client)
                all_channels = get_channels_across_teams(
                    slack_client=slack_client, team_ids=team_ids
                )
            else:
                all_channels = get_channels(slack_client=slack_client)
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                "The bot token cannot enumerate channels "
                "(`conversations.list`), so the configured channels could not "
                "be verified.",
            )
        visible_names = {channel["name"] for channel in all_channels}
        configured_names = [str(name).removeprefix("#") for name in channels_to_include]
        missing = sorted(set(configured_names) - visible_names)
        if missing:
            raise ConnectorValidationError(
                f"Configured channels are not visible to the bot: {missing}. "
                "Each may be a typo, an archived channel, or a private channel "
                "the bot has not been invited to (private channels also "
                "require the `groups:read` scope to be listed)."
            )


class _PermSyncChannelListingCheck(CapabilityCheck):
    """Lists one channel under the permission-sync capability.

    Doc sync enumerates every channel to build per-channel access lists and
    fails outright when it cannot; this is the same ``channels:read`` scope the
    INDEXING listing check probes, verified under the capability whose verdict
    depends on it.
    """

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="slack_perm_sync_channel_listing",
            display_name="Channels can be listed for permission sync",
            requires_connector_instance=False,
            remediation=_ADD_SCOPE_REMEDIATION.format(scope="channels:read"),
            docs_link=_SLACK_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        try:
            next(
                _slack_client(context).list_channels(
                    variant=SlackChannelVariant.PUBLIC,
                    channel_types=["public_channel"],
                    limit=1,
                )
            )
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                "The bot token cannot list channels (`conversations.list`), "
                "which permission sync requires to enumerate channels and "
                "build per-channel access lists.",
            )


class _PermSyncPrivateChannelListingCheck(CapabilityCheck):
    """Lists one private channel under the permission-sync capability.

    Not required: doc sync has the same silent public-only fallback indexing has
    when private channels cannot be listed, so the capability degrades rather
    than breaks.
    """

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="slack_perm_sync_private_channel_listing",
            display_name="Private channels can be listed for permission sync",
            required=False,
            requires_connector_instance=False,
            remediation=_ADD_SCOPE_REMEDIATION.format(scope="groups:read"),
            docs_link=_SLACK_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        try:
            next(
                _slack_client(context).list_channels(
                    variant=SlackChannelVariant.PRIVATE,
                    channel_types=["private_channel"],
                    limit=1,
                )
            )
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                "The bot token cannot list private channels. Permission sync "
                "does NOT fail on this: it silently syncs public channels "
                "only, so private-channel access lists are never created or "
                "updated. Previously indexed private documents keep stale "
                "access lists, so users removed from a private channel keep "
                "access in Onyx.",
            )


class _UserEmailVisibilityCheck(CapabilityCheck):
    """Samples users and requires at least one visible email address."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="slack_user_email_visibility",
            display_name="User emails are visible",
            requires_connector_instance=False,
            remediation=(
                _ADD_SCOPE_REMEDIATION.format(scope="users:read.email")
                + " Slack only returns email fields once the app is "
                "reinstalled."
            ),
            docs_link=_SLACK_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        slack_client = _slack_client(context)
        team_id = _first_grid_team_id(slack_client)
        try:
            users_page = next(
                slack_client.list_users(limit=_EMAIL_PROBE_PAGE_SIZE, team_id=team_id)
            )
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                "The bot token cannot list users (`users.list`), which "
                "permission sync requires to map Slack members to Onyx users "
                "by email.",
            )
        human_members = [
            member
            for member in users_page.members
            if not member.get("is_bot")
            and not member.get("deleted")
            and member.get("id") != "USLACKBOT"
        ]
        if not human_members:
            raise UnexpectedValidationError(
                "`users.list` returned no active human members to sample, so "
                "email visibility could not be verified."
            )
        if not any(member.get("profile", {}).get("email") for member in human_members):
            raise InsufficientPermissionsError(
                "`users.list` succeeded but returned no email addresses, so "
                "permission sync cannot map Slack members to Onyx users. This "
                "is how a missing `users:read.email` scope manifests -- Slack "
                "omits the email field instead of raising a scope error."
            )


class _PrivateChannelMemberListingCheck(CapabilityCheck):
    """Lists one private channel's members, then resolves one member.

    The ``users.info`` step mirrors doc sync's fallback for members missing from
    the workspace user list (external users). Listing scope failures pass here:
    doc sync silently degrades to public-only without ``groups:read``, and
    ``slack_perm_sync_private_channel_listing`` owns that warning.
    """

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="slack_private_channel_member_listing",
            display_name="Private-channel members can be listed",
            requires_connector_instance=False,
            remediation=(
                _ADD_SCOPE_REMEDIATION.format(scope="groups:read")
                + " Member-to-user resolution also needs `users:read`."
            ),
            docs_link=_SLACK_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        slack_client = _slack_client(context)
        channel = _first_private_channel(slack_client)
        if channel is None:
            return
        try:
            members_page = next(
                slack_client.list_channel_members(channel_id=channel["id"])
            )
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                "The bot token cannot list private-channel members "
                "(`conversations.members`), which permission sync requires to "
                "build per-channel member ACLs.",
            )
        members = members_page.members
        if not members:
            return
        try:
            slack_client.fetch_user_info(members[0])
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                "The bot token cannot resolve channel members to user "
                "profiles (`users.info`), which permission sync uses for "
                "members missing from the workspace user list.",
            )


class _GridPublicChannelScopingCheck(CapabilityCheck):
    """Verifies per-workspace user listing on Enterprise Grid.

    Not required: without it, permission sync still runs but silently marks
    every public channel visible org-wide in Onyx.
    """

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="slack_grid_public_channel_scoping",
            display_name="Grid public channels can be workspace-scoped",
            required=False,
            requires_connector_instance=False,
            remediation=(
                _ADD_SCOPE_REMEDIATION.format(scope="users:read")
                + " Also grant `users:read.email` and `team:read` so "
                "per-workspace user lists can be built."
            ),
            docs_link=_SLACK_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        slack_client = _slack_client(context)
        team_id = _first_grid_team_id(slack_client)
        if team_id is None:
            # Off-Grid, public channels are workspace-public by design.
            return
        try:
            next(slack_client.list_users(limit=1, team_id=team_id))
        except SlackApiError as e:
            _raise_for_slack_api_error(
                e,
                "On Enterprise Grid, per-workspace user listing (`users.list` "
                "with `team_id`) scopes public channels to their workspaces. "
                "Without it, permission sync silently marks every public "
                "channel visible org-wide in Onyx (over-sharing).",
            )


def build_slack_indexing_checks() -> list[CapabilityCheck]:
    """Returns the INDEXING capability checks for Slack."""
    return [
        _TokenAuthCheck(),
        _PublicChannelListingCheck(),
        _PrivateChannelListingCheck(),
        _MessageHistoryReadCheck(),
        _PrivateMessageHistoryReadCheck(),
        _ChannelJoinScopeCheck(),
        _GridWorkspaceListingCheck(),
        _UserProfileReadCheck(),
        _ConfiguredChannelsVisibleCheck(),
    ]


def build_slack_doc_permission_sync_checks() -> list[CapabilityCheck]:
    """Returns the DOC_PERMISSION_SYNC capability checks for Slack.

    Registered via the EE capability-check hook; defined here so the probe
    logic and remediation text live with the connector.
    """
    return [
        _PermSyncChannelListingCheck(),
        _PermSyncPrivateChannelListingCheck(),
        _UserEmailVisibilityCheck(),
        _PrivateChannelMemberListingCheck(),
        _GridPublicChannelScopingCheck(),
    ]
