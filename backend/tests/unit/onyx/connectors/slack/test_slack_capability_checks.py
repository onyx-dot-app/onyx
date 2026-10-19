"""Behavior tests for the Slack capability checks.

Checks compose gateway operations, so every test runs a check against an
autospecced ``SlackSourceOperations`` whose operations return the gateway's
typed page models; probe reach (which operations each check exercises) is
enforced separately by the auto-discovering coverage harness.
"""

from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    MAX_FINDING_OPTIONS,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CapabilityVerdict,
    CheckFinding,
    CheckFindingKey,
    CheckNotApplicableError,
    CheckNotRunReason,
    CheckOutput,
    CredentialCapability,
    FindingOption,
    OptionsFinding,
    compute_capability_verdicts,
)
from onyx.connectors.capability_checks.registry import get_capability_checks
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    CredentialInvalidError,
    InconclusiveValidationError,
    InsufficientPermissionsError,
    NothingToCheckError,
    RateLimitedValidationError,
)
from onyx.connectors.slack.capability_checks import (
    _CHANNEL_SCAN_BOUND,
    _CHANNEL_SCAN_PAGE_LIMIT,
    _CHANNEL_SCAN_PAGE_SIZE,
    build_slack_doc_permission_sync_checks,
    build_slack_indexing_checks,
)
from onyx.connectors.slack.source_operations import (
    SlackApiError,
    SlackAuthTestResponse,
    SlackChannelMembersPage,
    SlackChannelsPage,
    SlackChannelVariant,
    SlackHistoryPage,
    SlackSourceOperations,
    SlackTeamsPage,
    SlackUsersPage,
)

_ALL_INDEXING_SCOPES = [
    "channels:read",
    "channels:history",
    "channels:join",
    "groups:read",
    "groups:history",
    "users:read",
    "users:read.email",
]

_CHECKS_BY_ID = {
    check.check_id: check
    for check in build_slack_indexing_checks()
    + build_slack_doc_permission_sync_checks()
}


def _findings(output: CheckOutput | None) -> list[CheckFinding]:
    assert output is not None
    return output.findings


def _advisory_messages(output: CheckOutput | None) -> list[str]:
    assert output is not None
    return [advisory.message for advisory in output.advisories]


def _slack_error(error: str, needed: str | None = None) -> SlackApiError:
    data: dict[str, Any] = {"ok": False, "error": error}
    if needed is not None:
        data["needed"] = needed
    return SlackApiError("slack api error", data)


def _auth_response(
    enterprise_id: str | None = None,
    granted_scopes: list[str] | None = None,
) -> SlackAuthTestResponse:
    return SlackAuthTestResponse(
        ok=True,
        url="https://example.slack.com",
        enterprise_id=enterprise_id,
        granted_scopes=granted_scopes,
    )


def _gateway() -> MagicMock:
    """An autospecced gateway; tests set per-operation returns as needed."""
    gateway = create_autospec(SlackSourceOperations, instance=True)
    gateway.check_auth.return_value = _auth_response()
    return gateway


def _context(
    gateway: MagicMock,
    credential_json: dict[str, Any] | None = None,
    connector_specific_config: dict[str, Any] | None = None,
) -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.SLACK,
        credential_json=(
            {"slack_bot_token": "xoxb-test-token"}
            if credential_json is None
            else credential_json
        ),
        connector_specific_config=connector_specific_config,
        source_operations=gateway,
    )


def _run(check_id: str, context: CapabilityCheckContext) -> CheckOutput | None:
    return _CHECKS_BY_ID[check_id].run(context)


def _tracked_pages(pages: list[Any], consumed: list[Any]) -> Any:
    """A ``side_effect`` yielding ``pages`` lazily and recording each page the
    caller reads."""

    def make(**kwargs: Any) -> Any:
        del kwargs
        for page in pages:
            consumed.append(page)
            yield page

    return make


def _pages(page: Any) -> Any:
    """A ``side_effect`` yielding a fresh one-page generator per call."""

    def make(**kwargs: Any) -> Any:
        del kwargs
        return iter([page])

    return make


def test_token_auth_missing_token() -> None:
    """
    Verifies that an absent ``slack_bot_token`` key is a credential failure.
    """
    # Under test and postcondition.
    with pytest.raises(CredentialInvalidError, match="slack_bot_token"):
        _run("slack_token_auth", _context(_gateway(), credential_json={}))


def test_token_auth_rejects_user_token() -> None:
    """Verifies that non-bot tokens (no ``xoxb-`` prefix) are rejected."""
    # Under test and postcondition.
    with pytest.raises(CredentialInvalidError, match="xoxb"):
        _run(
            "slack_token_auth",
            _context(_gateway(), credential_json={"slack_bot_token": "xoxp-user"}),
        )


def test_token_auth_maps_invalid_auth_to_expired() -> None:
    """Verifies that ``invalid_auth`` from ``auth.test`` maps to expiry."""
    # Precondition.
    gateway = _gateway()
    gateway.check_auth.side_effect = _slack_error("invalid_auth")

    # Under test and postcondition.
    with pytest.raises(CredentialExpiredError, match="invalid_auth"):
        _run("slack_token_auth", _context(gateway))


def test_token_auth_maps_token_expired_to_expired() -> None:
    """Verifies ``token_expired`` (apps with token rotation) maps to expiry."""
    # Precondition.
    gateway = _gateway()
    gateway.check_auth.side_effect = _slack_error("token_expired")

    # Under test and postcondition.
    with pytest.raises(CredentialExpiredError, match="token_expired"):
        _run("slack_token_auth", _context(gateway))


def test_token_auth_passes_for_valid_bot_token() -> None:
    """Verifies the happy path for token validation."""
    # Under test and postcondition.
    _run("slack_token_auth", _context(_gateway()))


def test_invalid_unrelated_setting_does_not_stop_sign_in() -> None:
    """Verifies an invalid setting stops only the checks that read settings."""
    # Precondition.
    gateway = _gateway()
    context = _context(
        gateway,
        connector_specific_config={
            "batch_size": "not-a-number",
            "channels": ["gen.*"],
            "channel_regex_enabled": True,
        },
    )

    # Under test.
    auth, patterns = run_capability_checks(
        [_CHECKS_BY_ID["slack_token_auth"], _CHECKS_BY_ID["slack_channel_patterns"]],
        context,
    )

    # Postcondition.
    assert auth.status == CapabilityCheckStatus.PASSED
    gateway.check_auth.assert_called_once()
    assert patterns.status == CapabilityCheckStatus.FAILED
    assert "batch_size" in patterns.message


def test_public_channel_listing_missing_scope() -> None:
    """Verifies the ``channels:read`` probe shape and its failure mapping."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _slack_error(
        "missing_scope", needed="channels:read"
    )

    # Under test and postcondition.
    with pytest.raises(InsufficientPermissionsError, match="channels:read"):
        _run("slack_public_channel_listing", _context(gateway))
    gateway.list_channels.assert_called_once_with(
        variant=SlackChannelVariant.PUBLIC,
        channel_types=["public_channel"],
        exclude_archived=None,
        limit=_CHANNEL_SCAN_PAGE_SIZE,
    )


def test_public_channel_listing_probes_channel_info() -> None:
    """Verifies the net-new ``conversations.info`` probe on a listed channel."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _pages(
        SlackChannelsPage(channels=[{"id": "C1", "name": "general"}])
    )
    gateway.fetch_channel_info.side_effect = _slack_error(
        "missing_scope", needed="channels:read"
    )

    # Under test and postcondition.
    with pytest.raises(InsufficientPermissionsError, match="conversations.info"):
        _run("slack_public_channel_listing", _context(gateway))
    gateway.fetch_channel_info.assert_called_once_with(channel_id="C1")


def test_public_channel_listing_empty_workspace_skips_info_probe() -> None:
    """Verifies an empty listing still proves the listing scope."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _pages(SlackChannelsPage(channels=[]))

    # Under test.
    output = _run("slack_public_channel_listing", _context(gateway))

    # Postcondition.
    gateway.fetch_channel_info.assert_not_called()
    assert output is not None
    assert output.summary == "No public channel in first 200 scanned"
    (message,) = _advisory_messages(output)
    assert "details read" in message


def test_private_channel_listing_missing_scope_mentions_silent_skip() -> None:
    """
    Verifies the ``groups:read`` probe explains the silent-fallback hazard.
    """
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _slack_error(
        "missing_scope", needed="groups:read"
    )

    # Under test and postcondition.
    with pytest.raises(InsufficientPermissionsError, match="silently"):
        _run("slack_private_channel_listing", _context(gateway))
    gateway.list_channels.assert_called_once_with(
        variant=SlackChannelVariant.PRIVATE,
        channel_types=["private_channel"],
        exclude_archived=None,
        limit=_CHANNEL_SCAN_PAGE_SIZE,
    )


@pytest.mark.parametrize(
    "check_id",
    ["slack_private_channel_listing", "slack_perm_sync_private_channel_listing"],
)
def test_private_channel_listing_without_channels_adds_advisory(
    check_id: str,
) -> None:
    """
    Verifies an empty private listing passes, but says no private channel was
    found to read.
    """
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _pages(SlackChannelsPage(channels=[]))

    # Under test.
    output = _run(check_id, _context(gateway))

    # Postcondition.
    (message,) = _advisory_messages(output)
    assert "no private channel" in message


@pytest.mark.parametrize(
    "check_id",
    ["slack_private_channel_listing", "slack_perm_sync_private_channel_listing"],
)
def test_private_channel_listing_with_a_channel_has_no_advisory(
    check_id: str,
) -> None:
    """Verifies a private listing that returns a channel passes without a
    caveat and names the channel."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _pages(
        SlackChannelsPage(channels=[{"id": "C_PRIV", "name": "secret"}])
    )

    # Under test.
    output = _run(check_id, _context(gateway))

    # Postcondition.
    assert output is not None
    assert output.summary == "Found private channel #secret"
    assert output.advisories == []


@pytest.mark.parametrize(
    "check_id",
    ["slack_private_channel_listing", "slack_perm_sync_private_channel_listing"],
)
def test_private_channel_listing_finds_a_channel_on_a_later_page(
    check_id: str,
) -> None:
    """
    Verifies the search follows the cursor past an empty page: Slack applies
    ``limit`` before it filters by type.
    """
    # Precondition.
    gateway = _gateway()
    consumed: list[Any] = []
    gateway.list_channels.side_effect = _tracked_pages(
        [
            SlackChannelsPage(channels=[]),
            SlackChannelsPage(channels=[{"id": "C_PRIV", "name": "secret"}]),
        ],
        consumed,
    )

    # Under test.
    output = _run(check_id, _context(gateway))

    # Postcondition.
    assert _advisory_messages(output) == []
    assert len(consumed) == 2


def test_private_channel_search_stops_at_the_bound() -> None:
    """
    Verifies the search reads no more than the page limit and then reports the
    existing advisory, even when a later page has a private channel.
    """
    # Precondition.
    gateway = _gateway()
    consumed: list[Any] = []
    gateway.list_channels.side_effect = _tracked_pages(
        [SlackChannelsPage(channels=[]) for _ in range(_CHANNEL_SCAN_PAGE_LIMIT)]
        + [SlackChannelsPage(channels=[{"id": "C_PRIV", "name": "secret"}])],
        consumed,
    )

    # Under test.
    output = _run("slack_private_channel_listing", _context(gateway))

    # Postcondition.
    assert len(consumed) == _CHANNEL_SCAN_PAGE_LIMIT
    (message,) = _advisory_messages(output)
    assert "no private channel" in message
    assert f"among the {_CHANNEL_SCAN_BOUND} scanned" in message


def test_private_history_finds_a_private_channel_on_a_later_page() -> None:
    """Verifies the private history probe uses the bounded search."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _tracked_pages(
        [
            SlackChannelsPage(channels=[]),
            SlackChannelsPage(channels=[{"id": "C_PRIV", "name": "secret"}]),
        ],
        [],
    )
    gateway.fetch_channel_history.side_effect = _pages(
        SlackHistoryPage(messages=[{"ts": "333.444"}])
    )
    gateway.fetch_thread_replies.side_effect = _pages(SlackHistoryPage())

    # Under test.
    output = _run("slack_private_message_history_read", _context(gateway))

    # Postcondition.
    assert output is not None
    assert output.summary == "Read a thread in #secret"
    gateway.list_channels.assert_called_once_with(
        variant=SlackChannelVariant.PRIVATE,
        channel_types=["private_channel"],
        exclude_archived=True,
        limit=_CHANNEL_SCAN_PAGE_SIZE,
    )
    gateway.fetch_channel_history.assert_called_once_with(
        variant=SlackChannelVariant.PRIVATE, channel_id="C_PRIV", limit=1
    )


def test_message_history_prefers_member_channel() -> None:
    """Verifies the history probe targets a channel the bot is a member of."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _pages(
        SlackChannelsPage(
            channels=[
                {"id": "C_NOT_MEMBER", "name": "a", "is_member": False},
                {"id": "C_MEMBER", "name": "b", "is_member": True},
            ]
        )
    )
    gateway.fetch_channel_history.side_effect = _pages(SlackHistoryPage(messages=[]))

    # Under test.
    _run("slack_message_history_read", _context(gateway))

    # Postcondition.
    gateway.fetch_channel_history.assert_called_once_with(
        variant=SlackChannelVariant.PUBLIC, channel_id="C_MEMBER", limit=1
    )


def test_message_history_not_in_channel_counts_as_scope_proof() -> None:
    """Verifies ``not_in_channel`` passes: membership is fixed by auto-join."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _pages(
        SlackChannelsPage(channels=[{"id": "C1", "name": "a", "is_member": False}])
    )
    gateway.fetch_channel_history.side_effect = _slack_error("not_in_channel")

    # Under test.
    output = _run("slack_message_history_read", _context(gateway))

    # Postcondition.
    assert output is not None
    assert output.summary == "Scope accepted; bot not in #a"
    (message,) = _advisory_messages(output)
    assert "the bot is not in the channel" in message
    gateway.fetch_thread_replies.assert_not_called()


def test_message_history_missing_scope() -> None:
    """Verifies a missing history scope is a real failure."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _pages(
        SlackChannelsPage(channels=[{"id": "C1", "name": "a", "is_member": True}])
    )
    gateway.fetch_channel_history.side_effect = _slack_error(
        "missing_scope", needed="channels:history"
    )

    # Under test and postcondition.
    with pytest.raises(InsufficientPermissionsError, match="channels:history"):
        _run("slack_message_history_read", _context(gateway))


def test_message_history_no_visible_channels_is_incomplete() -> None:
    """Verifies an unprobeable workspace is inconclusive, not a failure."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _pages(SlackChannelsPage(channels=[]))

    # Under test and postcondition.
    with pytest.raises(InconclusiveValidationError, match="[Nn]o public channels"):
        _run("slack_message_history_read", _context(gateway))


def test_message_history_probes_a_thread() -> None:
    """Verifies the net-new ``conversations.replies`` probe uses a real ts."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _pages(
        SlackChannelsPage(channels=[{"id": "C1", "name": "a", "is_member": True}])
    )
    gateway.fetch_channel_history.side_effect = _pages(
        SlackHistoryPage(messages=[{"ts": "111.222"}])
    )
    gateway.fetch_thread_replies.side_effect = _slack_error(
        "missing_scope", needed="channels:history"
    )

    # Under test and postcondition.
    with pytest.raises(InsufficientPermissionsError, match="conversations.replies"):
        _run("slack_message_history_read", _context(gateway))
    gateway.fetch_thread_replies.assert_called_once_with(
        variant=SlackChannelVariant.PUBLIC, channel_id="C1", thread_ts="111.222"
    )


def test_message_history_read_thread_has_no_advisory() -> None:
    """Verifies a full history and thread read passes without an advisory."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _pages(
        SlackChannelsPage(channels=[{"id": "C1", "name": "a", "is_member": True}])
    )
    gateway.fetch_channel_history.side_effect = _pages(
        SlackHistoryPage(messages=[{"ts": "111.222"}])
    )
    gateway.fetch_thread_replies.side_effect = _pages(SlackHistoryPage())

    # Under test.
    output = _run("slack_message_history_read", _context(gateway))

    # Postcondition.
    assert output is not None
    assert output.summary == "Read a thread in #a"
    assert output.advisories == []


def test_message_history_empty_channel_skips_thread_probe() -> None:
    """Verifies an empty channel proves history access without a thread."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _pages(
        SlackChannelsPage(channels=[{"id": "C1", "name": "a", "is_member": True}])
    )
    gateway.fetch_channel_history.side_effect = _pages(SlackHistoryPage(messages=[]))

    # Under test.
    output = _run("slack_message_history_read", _context(gateway))

    # Postcondition.
    gateway.fetch_thread_replies.assert_not_called()
    assert output is not None
    assert output.summary == "Read #a; it has no messages"
    (message,) = _advisory_messages(output)
    assert "thread reads were not tested" in message


def test_private_history_skips_when_no_private_channels_in_scope() -> None:
    """Verifies a bot in no private channels has nothing to probe."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _pages(SlackChannelsPage(channels=[]))

    # Under test and postcondition.
    with pytest.raises(NothingToCheckError, match="no private channel"):
        _run("slack_private_message_history_read", _context(gateway))
    gateway.fetch_channel_history.assert_not_called()


def test_private_history_leaves_listing_scope_failures_to_the_listing_check() -> None:
    """
    Verifies a listing scope failure does not double-report here: without
    ``groups:read``, no private channels are in scope at all.
    """
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _slack_error(
        "missing_scope", needed="groups:read"
    )
    checks = [
        _CHECKS_BY_ID["slack_private_channel_listing"],
        _CHECKS_BY_ID["slack_private_message_history_read"],
    ]

    # Under test.
    listing, history = run_capability_checks(checks, _context(gateway))

    # Postcondition.
    assert listing.status == CapabilityCheckStatus.FAILED
    assert history.status == CapabilityCheckStatus.SKIPPED
    assert history.blocked_by == "slack_private_channel_listing"
    gateway.fetch_channel_history.assert_not_called()


def test_private_history_rate_limited_listing_is_incomplete() -> None:
    """
    Verifies the listing gate passes only scope failures: a rate-limited listing
    must not turn into a false pass of a required check.
    """
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _slack_error("ratelimited")

    # Under test and postcondition.
    with pytest.raises(RateLimitedValidationError, match="rate limited"):
        _run("slack_private_message_history_read", _context(gateway))


def test_private_history_missing_groups_history_fails() -> None:
    """
    Verifies the review P1 regression: a token that lists private channels but
    cannot read them (``channels:history`` without ``groups:history``) must not
    pass.
    """
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _pages(
        SlackChannelsPage(channels=[{"id": "C_PRIV", "name": "secret"}])
    )
    gateway.fetch_channel_history.side_effect = _slack_error(
        "missing_scope", needed="groups:history"
    )

    # Under test and postcondition.
    with pytest.raises(InsufficientPermissionsError, match="groups:history"):
        _run("slack_private_message_history_read", _context(gateway))
    gateway.fetch_channel_history.assert_called_once_with(
        variant=SlackChannelVariant.PRIVATE, channel_id="C_PRIV", limit=1
    )


def test_private_history_probes_a_private_thread() -> None:
    """Verifies the thread probe carries the private variant."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _pages(
        SlackChannelsPage(channels=[{"id": "C_PRIV", "name": "secret"}])
    )
    gateway.fetch_channel_history.side_effect = _pages(
        SlackHistoryPage(messages=[{"ts": "333.444"}])
    )
    gateway.fetch_thread_replies.side_effect = _pages(SlackHistoryPage())

    # Under test.
    output = _run("slack_private_message_history_read", _context(gateway))

    # Postcondition.
    gateway.fetch_thread_replies.assert_called_once_with(
        variant=SlackChannelVariant.PRIVATE, channel_id="C_PRIV", thread_ts="333.444"
    )
    assert output is not None
    assert output.summary == "Read a thread in #secret"


def test_channel_join_scope_present_passes() -> None:
    """Verifies the granted-scopes check accepts a granted ``channels:join``."""
    # Precondition.
    gateway = _gateway()
    gateway.check_auth.return_value = _auth_response(
        granted_scopes=_ALL_INDEXING_SCOPES
    )

    # Under test and postcondition.
    _run("slack_channel_join_scope", _context(gateway))


def test_channel_join_scope_missing_fails() -> None:
    """Verifies a missing ``channels:join`` scope is a real failure."""
    # Precondition.
    gateway = _gateway()
    gateway.check_auth.return_value = _auth_response(
        granted_scopes=["channels:read", "users:read"]
    )

    # Under test and postcondition.
    with pytest.raises(InsufficientPermissionsError, match="channels:join"):
        _run("slack_channel_join_scope", _context(gateway))


def test_channel_join_scope_absent_header_is_incomplete() -> None:
    """Verifies that a missing scopes header cannot fail the credential."""
    # Precondition.
    gateway = _gateway()
    gateway.check_auth.return_value = _auth_response(granted_scopes=None)

    # Under test and postcondition.
    with pytest.raises(InconclusiveValidationError, match="X-OAuth-Scopes"):
        _run("slack_channel_join_scope", _context(gateway))


@pytest.mark.parametrize(
    "check_id",
    ["slack_grid_workspace_listing", "slack_grid_public_channel_scoping"],
)
def test_grid_checks_do_not_apply_off_grid(check_id: str) -> None:
    """Verifies the Grid-only checks are SKIPPED and not applicable off Grid."""
    # Precondition.
    gateway = _gateway()

    # Under test.
    (result,) = run_capability_checks([_CHECKS_BY_ID[check_id]], _context(gateway))

    # Postcondition.
    assert result.status == CapabilityCheckStatus.SKIPPED
    assert result.applicable is False
    assert result.error_type == CheckNotApplicableError.__name__
    assert "Enterprise Grid" in result.message
    gateway.list_teams.assert_not_called()
    gateway.list_users.assert_not_called()


def test_grid_workspace_listing_missing_team_read() -> None:
    """Verifies the Grid ``team:read`` requirement is surfaced."""
    # Precondition.
    gateway = _gateway()
    gateway.check_auth.return_value = _auth_response(enterprise_id="E123")
    gateway.list_teams.side_effect = _slack_error("missing_scope", needed="team:read")

    # Under test and postcondition.
    with pytest.raises(InsufficientPermissionsError, match="team:read"):
        _run("slack_grid_workspace_listing", _context(gateway))


def test_user_profile_read_off_grid_omits_team_id() -> None:
    """Verifies the non-Grid ``users.list`` call shape."""
    # Precondition.
    gateway = _gateway()
    gateway.list_users.side_effect = _pages(SlackUsersPage(members=[{"id": "U1"}]))

    # Under test.
    _run("slack_user_profile_read", _context(gateway))

    # Postcondition.
    gateway.list_users.assert_called_once_with(limit=1, team_id=None)


def test_user_profile_read_on_grid_passes_team_id() -> None:
    """Verifies Grid installs mirror production and pass a ``team_id``."""
    # Precondition.
    gateway = _gateway()
    gateway.check_auth.return_value = _auth_response(enterprise_id="E123")
    gateway.list_teams.side_effect = _pages(SlackTeamsPage(teams=[{"id": "T1"}]))
    gateway.list_users.side_effect = _pages(SlackUsersPage(members=[{"id": "U1"}]))

    # Under test.
    _run("slack_user_profile_read", _context(gateway))

    # Postcondition.
    gateway.list_users.assert_called_once_with(limit=1, team_id="T1")


def test_user_profile_read_without_users_is_inconclusive() -> None:
    """Verifies an empty user page cannot pass: no profile was read."""
    # Precondition.
    gateway = _gateway()
    gateway.list_users.side_effect = _pages(SlackUsersPage(members=[]))

    # Under test and postcondition.
    with pytest.raises(InconclusiveValidationError, match="users.info"):
        _run("slack_user_profile_read", _context(gateway))
    gateway.fetch_user_info.assert_not_called()


def test_user_profile_read_missing_scope() -> None:
    """Verifies a missing ``users:read`` scope is a real failure."""
    # Precondition.
    gateway = _gateway()
    gateway.list_users.side_effect = _slack_error("missing_scope", needed="users:read")

    # Under test and postcondition.
    with pytest.raises(InsufficientPermissionsError, match="users:read"):
        _run("slack_user_profile_read", _context(gateway))


def test_user_profile_read_resolves_a_single_profile() -> None:
    """Verifies the net-new ``users.info`` probe mirrors author resolution."""
    # Precondition.
    gateway = _gateway()
    gateway.list_users.side_effect = _pages(SlackUsersPage(members=[{"id": "U1"}]))
    gateway.fetch_user_info.side_effect = _slack_error(
        "missing_scope", needed="users:read"
    )

    # Under test and postcondition.
    with pytest.raises(InsufficientPermissionsError, match="users.info"):
        _run("slack_user_profile_read", _context(gateway))
    gateway.fetch_user_info.assert_called_once_with("U1")


def test_email_visibility_passes_when_emails_present() -> None:
    """Verifies the happy path: at least one human member exposes an email."""
    # Precondition.
    gateway = _gateway()
    gateway.list_users.side_effect = _pages(
        SlackUsersPage(
            members=[
                {"id": "B1", "is_bot": True, "deleted": False, "profile": {}},
                {
                    "id": "U1",
                    "is_bot": False,
                    "deleted": False,
                    "profile": {"email": "user@example.com"},
                },
            ]
        )
    )

    # Under test and postcondition.
    _run("slack_user_email_visibility", _context(gateway))


def test_email_visibility_fails_when_emails_absent() -> None:
    """Verifies the content-based detection of a missing ``users:read.email``.

    Slack omits email fields rather than raising ``missing_scope``, so the check
    must fail on successful-but-emailless responses.
    """
    # Precondition.
    gateway = _gateway()
    gateway.list_users.side_effect = _pages(
        SlackUsersPage(
            members=[
                {"id": "U1", "is_bot": False, "deleted": False, "profile": {}},
                {"id": "U2", "is_bot": False, "deleted": False, "profile": {}},
            ]
        )
    )

    # Under test and postcondition.
    with pytest.raises(InsufficientPermissionsError, match="users:read.email"):
        _run("slack_user_email_visibility", _context(gateway))


def test_email_visibility_incomplete_without_human_sample() -> None:
    """
    Verifies bots, deleted users, and Slackbot are excluded from the sample.
    """
    # Precondition.
    gateway = _gateway()
    gateway.list_users.side_effect = _pages(
        SlackUsersPage(
            members=[
                {"id": "B1", "is_bot": True, "deleted": False, "profile": {}},
                {"id": "U1", "is_bot": False, "deleted": True, "profile": {}},
                {"id": "USLACKBOT", "is_bot": False, "deleted": False, "profile": {}},
            ]
        )
    )

    # Under test and postcondition.
    with pytest.raises(InconclusiveValidationError, match="human members"):
        _run("slack_user_email_visibility", _context(gateway))


def test_perm_sync_channel_listing_missing_scope() -> None:
    """Verifies the perm-sync enumeration probe and its failure mapping."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _slack_error(
        "missing_scope", needed="channels:read"
    )

    # Under test and postcondition.
    with pytest.raises(InsufficientPermissionsError, match="permission sync"):
        _run("slack_perm_sync_channel_listing", _context(gateway))
    gateway.list_channels.assert_called_once_with(
        variant=SlackChannelVariant.PUBLIC,
        channel_types=["public_channel"],
        exclude_archived=None,
        limit=_CHANNEL_SCAN_PAGE_SIZE,
    )


def test_perm_sync_private_listing_warning_names_stale_access_lists() -> None:
    """Verifies the warning states the silent degradation and its hazard."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _slack_error(
        "missing_scope", needed="groups:read"
    )

    # Under test and postcondition.
    with pytest.raises(InsufficientPermissionsError, match="stale"):
        _run("slack_perm_sync_private_channel_listing", _context(gateway))


def test_private_member_listing_does_not_run_after_a_failed_listing() -> None:
    """
    Verifies a listing scope failure is reported once, by the perm-sync
    private listing: doc sync silently degrades to public-only, and the member
    check does not run.
    """
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _slack_error(
        "missing_scope", needed="groups:read"
    )
    checks = [
        _CHECKS_BY_ID["slack_perm_sync_private_channel_listing"],
        _CHECKS_BY_ID["slack_private_channel_member_listing"],
    ]

    # Under test.
    listing, members = run_capability_checks(checks, _context(gateway))

    # Postcondition.
    assert listing.status == CapabilityCheckStatus.FAILED
    assert members.status == CapabilityCheckStatus.SKIPPED
    assert members.not_run_reason == CheckNotRunReason.DEPENDENCY_FAILED
    gateway.list_channel_members.assert_not_called()


def test_private_member_listing_skips_without_private_channels() -> None:
    """Verifies a bot in no private channels has nothing to probe."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _pages(SlackChannelsPage(channels=[]))

    # Under test and postcondition.
    with pytest.raises(NothingToCheckError):
        _run("slack_private_channel_member_listing", _context(gateway))
    gateway.list_channel_members.assert_not_called()


def test_private_member_listing_without_members_is_inconclusive() -> None:
    """Verifies an empty member page cannot pass: no profile was read."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _pages(
        SlackChannelsPage(channels=[{"id": "C_PRIV", "name": "secret"}])
    )
    gateway.list_channel_members.side_effect = _pages(
        SlackChannelMembersPage(members=[])
    )

    # Under test and postcondition.
    with pytest.raises(InconclusiveValidationError, match="users.info"):
        _run("slack_private_channel_member_listing", _context(gateway))
    gateway.fetch_user_info.assert_not_called()


def test_private_member_listing_missing_scope() -> None:
    """Verifies ``conversations.members`` failures surface for perm sync."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _pages(
        SlackChannelsPage(channels=[{"id": "C_PRIV", "name": "secret"}])
    )
    gateway.list_channel_members.side_effect = _slack_error(
        "missing_scope", needed="groups:read"
    )

    # Under test and postcondition.
    with pytest.raises(InsufficientPermissionsError, match="groups:read"):
        _run("slack_private_channel_member_listing", _context(gateway))
    gateway.list_channel_members.assert_called_once_with(channel_id="C_PRIV")


def test_private_member_listing_resolves_one_member() -> None:
    """
    Verifies the ``users.info`` step mirrors doc sync's external-user fallback.
    """
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _pages(
        SlackChannelsPage(channels=[{"id": "C_PRIV", "name": "secret"}])
    )
    gateway.list_channel_members.side_effect = _pages(
        SlackChannelMembersPage(members=["U_EXT"])
    )
    gateway.fetch_user_info.side_effect = _slack_error(
        "missing_scope", needed="users:read"
    )

    # Under test and postcondition.
    with pytest.raises(InsufficientPermissionsError, match="users.info"):
        _run("slack_private_channel_member_listing", _context(gateway))
    gateway.fetch_user_info.assert_called_once_with("U_EXT")


def test_grid_public_scoping_failure_explains_over_sharing() -> None:
    """Verifies the over-sharing degradation is named on failure."""
    # Precondition.
    gateway = _gateway()
    gateway.check_auth.return_value = _auth_response(enterprise_id="E123")
    gateway.list_teams.side_effect = _pages(SlackTeamsPage(teams=[{"id": "T1"}]))
    gateway.list_users.side_effect = _slack_error("missing_scope", needed="users:read")

    # Under test and postcondition.
    with pytest.raises(InsufficientPermissionsError, match="org-wide"):
        _run("slack_grid_public_channel_scoping", _context(gateway))
    gateway.list_users.assert_called_once_with(limit=1, team_id="T1")


def test_configured_channels_all_visible_passes() -> None:
    """Verifies the config check accepts channels present in the listing."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _pages(
        SlackChannelsPage(channels=[{"id": "C1", "name": "general"}])
    )
    # A typed name is matched without its ``#`` and in any case, as the
    # connector normalizes it.
    context = _context(gateway, connector_specific_config={"channels": ["#General"]})

    # Under test and postcondition.
    _run("slack_configured_channels_visible", context)


def test_configured_channels_by_id_pass_after_a_rename() -> None:
    """Verifies the config check accepts a channel id whose name changed."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _pages(
        SlackChannelsPage(channels=[{"id": "C0GENERAL1", "name": "general-renamed"}])
    )
    context = _context(gateway, connector_specific_config={"channels": ["C0GENERAL1"]})

    # Under test and postcondition.
    _run("slack_configured_channels_visible", context)


def test_configured_channels_some_missing_is_a_partial_find() -> None:
    """Verifies invisible configured channels are named in a partial result."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _pages(
        SlackChannelsPage(channels=[{"id": "C1", "name": "general"}])
    )
    context = _context(
        gateway, connector_specific_config={"channels": ["general", "not-a-channel"]}
    )

    # Under test.
    output = _run("slack_configured_channels_visible", context)

    # Postcondition.
    assert output is not None
    assert output.partial
    assert output.summary == "1 selected channel not visible"
    assert output.description is not None
    assert "not-a-channel" in output.description


def test_configured_channels_none_visible_fails() -> None:
    """Verifies the check fails when no configured channel is visible."""
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _pages(
        SlackChannelsPage(channels=[{"id": "C1", "name": "general"}])
    )
    context = _context(gateway, connector_specific_config={"channels": ["gone"]})

    # Under test and postcondition.
    with pytest.raises(ConnectorValidationError, match="gone"):
        _run("slack_configured_channels_visible", context)


@pytest.mark.parametrize(
    "config",
    [{"channels": ["gen.*"], "channel_regex_enabled": True}, {"channels": []}],
)
def test_configured_channels_without_exact_names_does_not_apply(
    config: dict[str, Any],
) -> None:
    """Verifies regex-mode and filter-less configs have no names to find."""
    # Precondition.
    gateway = _gateway()
    context = _context(gateway, connector_specific_config=config)

    # Under test.
    (result,) = run_capability_checks(
        [_CHECKS_BY_ID["slack_configured_channels_visible"]], context
    )

    # Postcondition.
    assert result.applicable is False
    gateway.list_channels.assert_not_called()


# slack_readable_channel_listing


def test_readable_channel_listing_finds_channel_ids_as_channel_options() -> None:
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = lambda **_: iter(
        [
            SlackChannelsPage(channels=[{"id": "C1", "name": "general"}]),
            SlackChannelsPage(channels=[{"id": "C2", "name": "random"}]),
        ]
    )

    # Under test.
    findings: list[CheckFinding] = _findings(
        _CHECKS_BY_ID["slack_readable_channel_listing"].run(_context(gateway))
    )

    # Postcondition.
    assert findings == [
        OptionsFinding(
            key=CheckFindingKey.READABLE_CHANNELS,
            field_name="channels",
            options=[
                FindingOption(value="C1", label="general"),
                FindingOption(value="C2", label="random"),
            ],
        )
    ]
    gateway.list_channels.assert_called_once_with(
        variant=SlackChannelVariant.PUBLIC,
        channel_types=["public_channel"],
        exclude_archived=True,
        team_id=None,
    )


def test_readable_channel_listing_lists_each_grid_workspace() -> None:
    # Precondition.
    gateway = _gateway()
    gateway.check_auth.return_value = _auth_response(enterprise_id="E1")
    gateway.list_teams.side_effect = _pages(
        SlackTeamsPage(
            teams=[{"id": "T1", "name": "Acme"}, {"id": "T2", "name": "Labs"}]
        )
    )
    channels_by_team = {
        "T1": [{"id": "C1", "name": "general"}],
        # A shared channel appears in both workspaces and is one option. Another
        # workspace's own channel with the same name is a second option, told
        # apart by its workspace.
        "T2": [
            {"id": "C1", "name": "general"},
            {"id": "C3", "name": "general"},
            {"id": "C2", "name": "eng"},
        ],
    }
    gateway.list_channels.side_effect = lambda **kwargs: iter(
        [SlackChannelsPage(channels=channels_by_team[kwargs["team_id"]])]
    )

    # Under test.
    findings: list[CheckFinding] = _findings(
        _CHECKS_BY_ID["slack_readable_channel_listing"].run(_context(gateway))
    )

    # Postcondition.
    listing: CheckFinding = findings[0]
    assert isinstance(listing, OptionsFinding)
    assert [
        (option.value, option.label, option.detail) for option in listing.options
    ] == [
        ("C1", "general", "Acme"),
        ("C3", "general", "Labs"),
        ("C2", "eng", "Labs"),
    ]


def test_readable_channel_listing_stops_at_the_option_cap() -> None:
    # Precondition.
    gateway = _gateway()
    pages_read: list[int] = []

    def list_channels(**kwargs: Any) -> Any:
        del kwargs
        for page_number in range(50):
            pages_read.append(page_number)
            yield SlackChannelsPage(
                channels=[
                    {"id": f"C{page_number}-{n}", "name": f"c{page_number}-{n}"}
                    for n in range(100)
                ]
            )

    gateway.list_channels.side_effect = list_channels

    # Under test.
    findings: list[CheckFinding] = _findings(
        _CHECKS_BY_ID["slack_readable_channel_listing"].run(_context(gateway))
    )

    # Postcondition.
    listing: CheckFinding = findings[0]
    assert isinstance(listing, OptionsFinding)
    assert len(listing.options) == MAX_FINDING_OPTIONS
    assert listing.truncated is True
    # The listing stops one page past the cap instead of reading every page.
    assert len(pages_read) == MAX_FINDING_OPTIONS // 100 + 1


def test_readable_channel_listing_missing_scope_fails_only_this_check() -> None:
    # Precondition.
    gateway = _gateway()
    gateway.list_channels.side_effect = _slack_error(
        "missing_scope", needed="channels:read"
    )

    # Under test and postcondition.
    with pytest.raises(InsufficientPermissionsError, match="channels:read"):
        _run("slack_readable_channel_listing", _context(gateway))
    check = _CHECKS_BY_ID["slack_readable_channel_listing"]
    assert check.discovery is True
    assert check.required is False


def test_channel_patterns_rejects_a_malformed_exclude_regex() -> None:
    # Precondition.
    context = _context(
        _gateway(),
        connector_specific_config={
            "channels": ["[unclosed"],
            "exclude_channels": ["(open"],
            "exclude_channel_regex_enabled": True,
        },
    )

    # Under test and postcondition.
    # Include patterns are plain names here, so only the exclude regex fails.
    with pytest.raises(ConnectorValidationError, match="excluded channel regex"):
        _run("slack_channel_patterns", context)


def test_check_metadata_is_pinned() -> None:
    """Verifies builder metadata: ids, requiredness, and execution needs."""
    # Precondition.
    checks = build_slack_indexing_checks() + build_slack_doc_permission_sync_checks()

    # Under test and postcondition.
    check_ids = [check.check_id for check in checks]
    assert len(check_ids) == len(set(check_ids)), "Check ids must be unique."
    assert all(not check.requires_connector_instance for check in checks), (
        "Slack checks compose the gateway; none needs a connector instance."
    )
    config_requiring = {
        check.check_id for check in checks if check.requires_connector_config
    }
    assert config_requiring == {
        "slack_channel_patterns",
        "slack_configured_channels_visible",
    }
    optional = {
        check.check_id for check in checks if not check.required and not check.discovery
    }
    assert optional == {
        "slack_private_channel_listing",
        "slack_perm_sync_private_channel_listing",
        "slack_user_profile_read",
        "slack_grid_public_channel_scoping",
        # Not required (a fully invited bot works without ``channels:join``),
        # but the warning text demands action in most setups.
        "slack_channel_join_scope",
    }
    assert {check.check_id for check in checks if check.discovery} == {
        "slack_readable_channel_listing"
    }
    assert all(check.remediation for check in checks)
    assert all(check.docs_link for check in checks)
    # The full-workspace enumeration is the one probe with a raised hang guard.
    assert _CHECKS_BY_ID["slack_configured_channels_visible"].timeout_seconds == 1800


def test_slack_registers_named_indexing_checks() -> None:
    """
    Verifies the registry serves Slack's named INDEXING checks rather than
    synthesizing the ``validate_connector_settings`` fallback.
    """
    # Under test.
    checks = get_capability_checks(DocumentSource.SLACK)

    # Postcondition.
    indexing_ids = {
        check.check_id
        for check in checks
        if check.capability == CredentialCapability.INDEXING
    }
    assert indexing_ids == {check.check_id for check in build_slack_indexing_checks()}
    assert not any(check.is_fallback for check in checks)


def _coherent_gateway() -> MagicMock:
    """An off-Grid gateway with every probe answering like a healthy token."""
    gateway = _gateway()
    gateway.check_auth.return_value = _auth_response(
        granted_scopes=_ALL_INDEXING_SCOPES
    )

    def list_channels(**kwargs: Any) -> Any:
        if "public_channel" in kwargs["channel_types"]:
            return iter(
                [
                    SlackChannelsPage(
                        channels=[{"id": "C1", "name": "general", "is_member": True}]
                    )
                ]
            )
        return iter([SlackChannelsPage(channels=[{"id": "G1", "name": "secret"}])])

    gateway.list_channels.side_effect = list_channels
    gateway.fetch_channel_history.side_effect = _pages(SlackHistoryPage(messages=[]))
    gateway.list_channel_members.side_effect = _pages(
        SlackChannelMembersPage(members=["U1"])
    )
    gateway.list_users.side_effect = _pages(
        SlackUsersPage(
            members=[
                {
                    "id": "U1",
                    "is_bot": False,
                    "deleted": False,
                    "profile": {"email": "user@example.com"},
                }
            ]
        )
    )
    return gateway


_GRID_CHECK_IDS = ("slack_grid_workspace_listing", "slack_grid_public_channel_scoping")


def _pop_off_grid_checks(
    results: list[CapabilityCheckResult],
    status_by_id: dict[str, CapabilityCheckStatus],
) -> None:
    """Asserts the Grid-only checks do not apply off Grid, then drops them."""
    not_applicable_ids = {
        result.check_id for result in results if not result.applicable
    }
    assert not_applicable_ids == set(_GRID_CHECK_IDS)
    for check_id in _GRID_CHECK_IDS:
        assert status_by_id.pop(check_id) == CapabilityCheckStatus.SKIPPED


def test_full_slack_check_run_happy_path() -> None:
    """Verifies an end-to-end run over all Slack checks with a healthy token."""
    # Precondition.
    checks = build_slack_indexing_checks() + build_slack_doc_permission_sync_checks()
    context = _context(
        _coherent_gateway(),
        connector_specific_config={
            "channels": ["#general"],
            "exclude_channels": ["^tmp-"],
            "exclude_channel_regex_enabled": True,
        },
    )

    # Under test.
    results = run_capability_checks(checks, context)

    # Postcondition.
    status_by_id = {result.check_id: result.status for result in results}
    _pop_off_grid_checks(results, status_by_id)
    assert all(
        status == CapabilityCheckStatus.PASSED for status in status_by_id.values()
    ), f"Expected every applicable check to pass, got {status_by_id}."
    verdicts = compute_capability_verdicts(
        {CredentialCapability.INDEXING, CredentialCapability.DOC_PERMISSION_SYNC},
        results,
    )
    assert verdicts == {
        CredentialCapability.INDEXING: CapabilityVerdict.PASSED,
        CredentialCapability.DOC_PERMISSION_SYNC: CapabilityVerdict.PASSED,
        CredentialCapability.EXTERNAL_GROUP_SYNC: CapabilityVerdict.NOT_APPLICABLE,
    }


def test_configless_run_gates_indexing_on_the_required_config_check() -> None:
    """
    Verifies the credential-time verdict semantics: every runnable check passes,
    but the required config-reading checks skip, which keeps INDEXING at SKIPPED
    (no pass-ish claim on a partially verified capability) until connector
    binding re-runs the checks.
    """
    # Precondition.
    checks = build_slack_indexing_checks() + build_slack_doc_permission_sync_checks()
    context = _context(_coherent_gateway())

    # Under test.
    results = run_capability_checks(checks, context)

    # Postcondition.
    status_by_id = {result.check_id: result.status for result in results}
    _pop_off_grid_checks(results, status_by_id)
    for config_check_id in (
        "slack_channel_patterns",
        "slack_configured_channels_visible",
    ):
        assert status_by_id.pop(config_check_id) == CapabilityCheckStatus.SKIPPED
    assert all(
        status == CapabilityCheckStatus.PASSED for status in status_by_id.values()
    ), f"Expected all non-config checks to pass, got {status_by_id}."
    verdicts = compute_capability_verdicts(
        {CredentialCapability.INDEXING, CredentialCapability.DOC_PERMISSION_SYNC},
        results,
    )
    assert verdicts == {
        CredentialCapability.INDEXING: CapabilityVerdict.SKIPPED,
        CredentialCapability.DOC_PERMISSION_SYNC: CapabilityVerdict.PASSED,
        CredentialCapability.EXTERNAL_GROUP_SYNC: CapabilityVerdict.NOT_APPLICABLE,
    }
