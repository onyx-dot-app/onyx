"""The Slack checks' rows: the design's names, short lines and descriptions,
the run order and the form unlock, the partial Find of selected channels, and
what a check that tested nothing says."""

from typing import Any
from unittest.mock import MagicMock
from urllib.error import URLError

from slack_sdk.web import SlackResponse

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckErrorKind,
    CheckNotRunReason,
    FindingOption,
    OptionsFinding,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.slack.capability_checks import (
    build_slack_doc_permission_sync_checks,
    build_slack_indexing_checks,
)
from onyx.connectors.slack.source_operations import (
    SlackApiError,
    SlackAuthTestResponse,
    SlackChannelMembersPage,
    SlackChannelsPage,
    SlackHistoryPage,
    SlackResponseMetadata,
    SlackTeamsPage,
)
from tests.unit.onyx.connectors.slack.slack_check_helpers import (
    autospec_gateway,
    coherent_gateway,
    page_side_effect,
    slack_error,
    tracked_pages,
)

_ALL_CHECKS: list[CapabilityCheck] = (
    build_slack_indexing_checks() + build_slack_doc_permission_sync_checks()
)


def _run_all(
    check_ids: list[str],
    gateway: MagicMock,
    config: dict[str, Any] | None = None,
    *,
    credential_json: dict[str, Any] | None = None,
    form_run: bool = False,
) -> dict[str, CapabilityCheckResult]:
    checks = [check for check in _ALL_CHECKS if check.check_id in check_ids]
    context = CapabilityCheckContext(
        source=DocumentSource.SLACK,
        credential_json=credential_json or {"slack_bot_token": "xoxb-test-token"},
        connector_specific_config=config,
        source_operations=gateway,
    )
    return {
        result.check_id: result
        for result in run_capability_checks(checks, context, form_run=form_run)
    }


def _run(
    check_id: str,
    gateway: MagicMock,
    config: dict[str, Any] | None = None,
    *,
    credential_json: dict[str, Any] | None = None,
    form_run: bool = False,
) -> CapabilityCheckResult:
    return _run_all(
        [check_id],
        gateway,
        config,
        credential_json=credential_json,
        form_run=form_run,
    )[check_id]


def _grid_gateway() -> MagicMock:
    gateway = coherent_gateway()
    gateway.check_auth.return_value = SlackAuthTestResponse(ok=True, enterprise_id="E1")
    gateway.list_teams.side_effect = page_side_effect(
        SlackTeamsPage(
            teams=[{"id": "T1", "name": "Acme"}, {"id": "T2", "name": "Labs"}]
        )
    )
    return gateway


# --- Rows and the form unlock ---


def test_the_checks_use_the_design_row_names() -> None:
    names = {check.check_id: check.display_name for check in _ALL_CHECKS}

    assert names["slack_token_auth"] == "Sign in to Slack"
    assert names["slack_grid_workspace_listing"] == "List Grid workspaces"
    assert names["slack_grid_public_channel_scoping"] == "List users per workspace"
    assert all(len(name) <= 24 for name in names.values())


def test_variants_of_a_probe_share_one_row() -> None:
    row_ids = {check.check_id: check.row_id for check in _ALL_CHECKS}

    assert (
        row_ids["slack_readable_channel_listing"]
        == row_ids["slack_perm_sync_channel_listing"]
        == row_ids["slack_public_channel_listing"]
    )
    assert (
        row_ids["slack_perm_sync_private_channel_listing"]
        == row_ids["slack_private_channel_listing"]
    )


def test_sign_in_and_grid_listing_unlock_the_form() -> None:
    assert {check.check_id for check in _ALL_CHECKS if check.validates_binding} == {
        "slack_token_auth",
        "slack_grid_workspace_listing",
    }


# --- Sign in to Slack ---


def test_sign_in_names_the_bot_and_the_workspace() -> None:
    gateway = autospec_gateway()
    gateway.check_auth.return_value = SlackAuthTestResponse(
        ok=True, user="onyx", team="Acme"
    )

    result = _run("slack_token_auth", gateway)

    assert result.status == CapabilityCheckStatus.PASSED
    assert result.summary == "Signed in as @onyx in Acme"


def test_a_missing_token_says_so() -> None:
    result = _run(
        "slack_token_auth", autospec_gateway(), credential_json={"other": "x"}
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Account has no bot token"


def test_a_user_token_is_not_a_bot_token() -> None:
    result = _run(
        "slack_token_auth",
        autospec_gateway(),
        credential_json={"slack_bot_token": "xoxp-user"},
    )

    assert result.summary == "Token is not a bot token"


def test_each_rejection_has_its_line() -> None:
    lines = {
        "invalid_auth": "Slack rejected the bot token",
        "account_inactive": "Workspace or bot user is deactivated",
        "token_revoked": "Bot token was revoked",
        "token_expired": "Bot token expired",
    }
    for error, line in lines.items():
        gateway = autospec_gateway()
        gateway.check_auth.side_effect = slack_error(error)

        result = _run("slack_token_auth", gateway)

        assert result.status == CapabilityCheckStatus.FAILED
        assert result.error_kind == CheckErrorKind.REJECTED
        assert result.summary == line


def test_an_unreachable_slack_fails_only_a_form_run() -> None:
    gateway = autospec_gateway()
    gateway.check_auth.side_effect = URLError("refused")

    form = _run("slack_token_auth", gateway, form_run=True)
    stored = _run("slack_token_auth", gateway)

    assert form.status == CapabilityCheckStatus.FAILED
    assert stored.status == CapabilityCheckStatus.INCOMPLETE
    assert form.summary == stored.summary == "Cannot reach Slack"


def test_a_rate_limit_at_sign_in_is_incomplete() -> None:
    gateway = autospec_gateway()
    gateway.check_auth.side_effect = slack_error("ratelimited")

    auth = _run("slack_token_auth", gateway)

    assert auth.status == CapabilityCheckStatus.INCOMPLETE
    assert auth.error_kind == CheckErrorKind.RATE_LIMITED
    assert auth.summary == "Rate limited by Slack"


def test_a_rate_limit_stops_the_checks_after_it() -> None:
    gateway = autospec_gateway()
    gateway.list_channels.side_effect = slack_error("ratelimited")

    results = _run_all(
        ["slack_public_channel_listing", "slack_channel_join_scope"], gateway
    )

    assert results["slack_public_channel_listing"].summary == "Rate limited by Slack"
    assert (
        results["slack_channel_join_scope"].not_run_reason
        == CheckNotRunReason.RATE_LIMITED
    )


def test_a_failed_sign_in_stops_the_checks_after_it() -> None:
    gateway = autospec_gateway()
    gateway.check_auth.side_effect = slack_error("invalid_auth")
    after_sign_in = [
        "slack_public_channel_listing",
        "slack_message_history_read",
        "slack_private_channel_listing",
        "slack_user_email_visibility",
    ]

    results = _run_all(["slack_token_auth", *after_sign_in], gateway)

    for check_id in after_sign_in:
        assert results[check_id].status == CapabilityCheckStatus.SKIPPED
        assert results[check_id].blocked_by == "slack_token_auth"
    gateway.list_channels.assert_not_called()


def test_a_slack_error_carries_the_request_and_body() -> None:
    gateway = autospec_gateway()
    response = SlackResponse(
        client=None,
        http_verb="POST",
        api_url="https://slack.com/api/conversations.list",
        req_args={},
        data={"ok": False, "error": "missing_scope", "needed": "channels:read"},
        headers={},
        status_code=200,
    )
    gateway.list_channels.side_effect = SlackApiError("missing_scope", response)

    result = _run("slack_public_channel_listing", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Bot cannot list public channels"
    assert result.error_detail is not None
    assert result.error_detail.request == "POST slack.com/api/conversations.list"
    assert result.error_detail.response_excerpt is not None
    assert "missing_scope" in result.error_detail.response_excerpt


# --- Grid ---


def test_grid_listing_counts_the_workspaces() -> None:
    result = _run("slack_grid_workspace_listing", _grid_gateway())

    assert result.status == CapabilityCheckStatus.PASSED
    assert result.summary == "2 workspaces in the org"


def test_grid_listing_without_team_read_names_the_scope() -> None:
    gateway = _grid_gateway()
    gateway.list_teams.side_effect = slack_error("missing_scope", needed="team:read")

    result = _run("slack_grid_workspace_listing", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Bot cannot list Grid workspaces"
    assert result.description is not None
    assert "team:read" in result.description


def test_a_failed_grid_listing_stops_the_workspace_user_check() -> None:
    gateway = _grid_gateway()
    gateway.list_teams.side_effect = slack_error("missing_scope", needed="team:read")

    results = _run_all(
        ["slack_grid_workspace_listing", "slack_grid_public_channel_scoping"], gateway
    )

    scoping = results["slack_grid_public_channel_scoping"]
    assert scoping.status == CapabilityCheckStatus.SKIPPED
    assert scoping.summary == "Not run: List Grid workspaces failed"


def test_workspace_user_listing_names_the_workspace() -> None:
    result = _run("slack_grid_public_channel_scoping", _grid_gateway())

    assert result.summary == "Listed users in workspace Acme"


def test_a_grid_org_without_workspaces_is_incomplete() -> None:
    gateway = _grid_gateway()
    gateway.list_teams.side_effect = page_side_effect(SlackTeamsPage(teams=[]))

    result = _run("slack_user_profile_read", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "Grid org returned no workspaces"


# --- Channels ---


def test_public_listing_names_the_channel_it_read() -> None:
    result = _run("slack_public_channel_listing", coherent_gateway())

    assert result.summary == "Found #general and read its details"


def test_message_sample_follows_the_cursor_past_an_empty_first_page() -> None:
    gateway = autospec_gateway()
    consumed: list[Any] = []
    gateway.list_channels.side_effect = tracked_pages(
        [
            SlackChannelsPage(channels=[]),
            SlackChannelsPage(
                channels=[{"id": "C1", "name": "general", "is_member": True}]
            ),
        ],
        consumed,
    )
    gateway.fetch_channel_history.side_effect = page_side_effect(
        SlackHistoryPage(messages=[])
    )

    result = _run("slack_message_history_read", gateway)

    assert len(consumed) == 2
    assert result.summary == "Read #general; it has no messages"


def test_no_public_channel_to_sample_is_incomplete() -> None:
    gateway = autospec_gateway()
    gateway.list_channels.side_effect = page_side_effect(SlackChannelsPage(channels=[]))

    result = _run("slack_message_history_read", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "No public channel found to test"


def test_the_channel_picker_counts_the_channels() -> None:
    result = _run("slack_readable_channel_listing", coherent_gateway())

    assert result.summary == "1 public channel found"
    assert result.findings == [
        OptionsFinding(
            key=result.findings[0].key,
            field_name="channels",
            options=[FindingOption(value="C1", label="general")],
        )
    ]


def test_missing_join_scope_header_is_incomplete() -> None:
    gateway = autospec_gateway()
    gateway.check_auth.return_value = SlackAuthTestResponse(ok=True)

    result = _run("slack_channel_join_scope", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "Slack did not report the token's scopes"


def test_a_bad_pattern_names_it() -> None:
    result = _run(
        "slack_channel_patterns",
        autospec_gateway(),
        {"channels": ["eng-["], "channel_regex_enabled": True},
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Invalid channel pattern: eng-["


def test_patterns_count_what_compiled() -> None:
    result = _run(
        "slack_channel_patterns",
        autospec_gateway(),
        {
            "channels": ["eng-.*", "ops"],
            "channel_regex_enabled": True,
            "exclude_channels": ["tmp-.*"],
            "exclude_channel_regex_enabled": True,
        },
    )

    assert result.summary == "All 3 patterns are valid"


def test_names_without_regex_mode_have_no_patterns_to_compile() -> None:
    result = _run(
        "slack_channel_patterns", autospec_gateway(), {"channels": ["general"]}
    )

    assert result.applicable is False


# --- Find selected channels ---


def test_all_selected_channels_found() -> None:
    gateway = autospec_gateway()
    gateway.list_channels.side_effect = page_side_effect(
        SlackChannelsPage(
            channels=[
                {"id": "C0GENERAL1", "name": "general"},
                {"id": "C0RANDOM01", "name": "random"},
            ]
        )
    )

    result = _run(
        "slack_configured_channels_visible",
        gateway,
        {"channels": ["#General", "C0RANDOM01"]},
    )

    assert result.status == CapabilityCheckStatus.PASSED
    assert result.summary == "All 2 selected channels found"


def test_some_selected_channels_missing_is_incomplete() -> None:
    result = _run(
        "slack_configured_channels_visible",
        coherent_gateway(),
        {"channels": ["general", "gone", "typo"]},
    )

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.partial
    assert result.summary == "2 selected channels not visible"
    assert result.description is not None
    assert "gone, typo" in result.description


def test_no_selected_channel_found_fails() -> None:
    result = _run(
        "slack_configured_channels_visible", coherent_gateway(), {"channels": ["gone"]}
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "No selected channel found"


# --- Private channels and members ---


def test_private_listing_without_a_channel_passes_with_a_caveat() -> None:
    gateway = autospec_gateway()
    gateway.list_channels.side_effect = page_side_effect(SlackChannelsPage(channels=[]))

    result = _run("slack_private_channel_listing", gateway)

    assert result.status == CapabilityCheckStatus.PASSED
    assert result.summary == "Bot is in no private channel"
    assert result.advisories


def test_checks_after_an_empty_private_listing_have_nothing_to_test() -> None:
    gateway = autospec_gateway()
    gateway.list_channels.side_effect = page_side_effect(SlackChannelsPage(channels=[]))

    results = _run_all(
        [
            "slack_private_channel_listing",
            "slack_private_message_history_read",
            "slack_perm_sync_private_channel_listing",
            "slack_private_channel_member_listing",
        ],
        gateway,
    )

    for check_id in (
        "slack_private_message_history_read",
        "slack_private_channel_member_listing",
    ):
        assert results[check_id].status == CapabilityCheckStatus.SKIPPED
        assert results[check_id].not_run_reason == CheckNotRunReason.NOTHING_IN_SCOPE
        assert results[check_id].summary == "Bot is in no private channel"


def test_member_listing_counts_the_members() -> None:
    gateway = coherent_gateway()

    result = _run("slack_private_channel_member_listing", gateway)

    assert result.summary == "Listed 1 member of #secret"


def test_member_listing_marks_a_cut_page() -> None:
    gateway = coherent_gateway()
    gateway.list_channel_members.side_effect = page_side_effect(
        _members_page(["U1", "U2"], next_cursor="more")
    )

    result = _run("slack_private_channel_member_listing", gateway)

    assert result.summary == "Listed 2+ members of #secret"


def _members_page(members: list[str], next_cursor: str) -> SlackChannelMembersPage:
    return SlackChannelMembersPage(
        members=members,
        response_metadata=SlackResponseMetadata(next_cursor=next_cursor),
    )


# --- Users ---


def test_emails_count_the_users_with_one() -> None:
    result = _run("slack_user_email_visibility", coherent_gateway())

    assert result.summary == "Emails visible for 1 of 1 users"


def test_user_profiles_say_names_are_readable() -> None:
    result = _run("slack_user_profile_read", coherent_gateway())

    assert result.summary == "User names readable"
