"""The Notion checks' rows: the design's short lines and descriptions, what
passing checks found, the run order, and what a check that tested nothing
says."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckErrorKind,
    CheckNotRunReason,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.notion.capability_checks import build_notion_indexing_checks
from onyx.connectors.notion.source_operations import NotionApiError
from tests.unit.onyx.connectors.notion.test_notion_capability_checks import (
    _api_error,
    _gateway,
)

_ALL_CHECK_IDS = [check.check_id for check in build_notion_indexing_checks()]
_BOT_USER = {
    "object": "user",
    "type": "bot",
    "name": "Onyx",
    "bot": {"owner": {"type": "workspace"}, "workspace_name": "Acme"},
}


def _rich_text(text: str) -> list[dict[str, Any]]:
    return [{"type": "text", "plain_text": text}]


def _page(title: str) -> dict[str, Any]:
    return {
        "id": "page-1",
        "object": "page",
        "properties": {"Name": {"type": "title", "title": _rich_text(title)}},
    }


def _data_source(title: str) -> dict[str, Any]:
    return {
        "id": "ds-1",
        "object": "data_source",
        "title": _rich_text(title),
        "parent": {"type": "database_id", "database_id": "db-1"},
    }


def _run_all(
    check_ids: list[str],
    gateway: MagicMock,
    config: dict[str, Any] | None,
    *,
    form_run: bool = False,
) -> dict[str, CapabilityCheckResult]:
    checks: list[CapabilityCheck] = [
        check for check in build_notion_indexing_checks() if check.check_id in check_ids
    ]
    context = CapabilityCheckContext(
        source=DocumentSource.NOTION,
        credential_json={"notion_integration_token": "secret"},
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
    form_run: bool = False,
) -> CapabilityCheckResult:
    return _run_all([check_id], gateway, config or {}, form_run=form_run)[check_id]


def _titled_gateway(**kwargs: Any) -> MagicMock:
    gateway = _gateway(**kwargs)
    gateway.get_bot_user.return_value = _BOT_USER
    return gateway


# --- Names ---


def test_rows_have_the_design_names() -> None:
    names = [check.display_name for check in build_notion_indexing_checks()]

    assert names == [
        "Sign in to Notion",
        "Find shared pages",
        "Find root page",
        "Sample page content",
        "Sample database rows",
        "Read user names",
    ]


# --- Sign in to Notion ---


def test_sign_in_names_the_bot_and_workspace() -> None:
    assert _run("notion_auth", _titled_gateway()).summary == "Signed in as Onyx in Acme"


def test_a_rejected_token_says_so() -> None:
    gateway = _gateway()
    gateway.get_bot_user.side_effect = _api_error(401, "unauthorized")

    result = _run("notion_auth", gateway)

    assert result.error_kind == CheckErrorKind.REJECTED
    assert result.summary == "Notion rejected the integration token"
    assert result.description is not None
    assert "Internal Integration Secret" in result.description
    assert "HTTP 401" in result.message


def test_a_denied_bot_user_says_so() -> None:
    gateway = _gateway()
    gateway.get_bot_user.side_effect = _api_error(403, "restricted_resource")

    result = _run("notion_auth", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Integration cannot read its bot user"


def test_a_missing_token_fails_sign_in() -> None:
    gateway = _gateway()
    gateway.get_bot_user.side_effect = ConnectorMissingCredentialError("Notion")

    result = _run("notion_auth", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_kind == CheckErrorKind.REJECTED
    assert result.summary == "Account has no integration token"


@pytest.mark.parametrize(
    "error,summary",
    [
        (NotionApiError("reset", status_code=None, code=None), "Cannot reach Notion"),
        (
            NotionApiError("slow", status_code=None, code=None, timed_out=True),
            "Sign-in timed out",
        ),
    ],
    ids=["unreachable", "timeout"],
)
def test_an_unreachable_notion_fails_only_a_form_run(
    error: NotionApiError, summary: str
) -> None:
    gateway = _gateway()
    gateway.get_bot_user.side_effect = error

    form = _run("notion_auth", gateway, form_run=True)
    stored = _run("notion_auth", gateway)

    assert form.status == CapabilityCheckStatus.FAILED
    assert stored.status == CapabilityCheckStatus.INCOMPLETE
    assert form.summary == stored.summary == summary


def test_a_rate_limit_is_incomplete_and_stops_the_run() -> None:
    gateway = _gateway()
    gateway.iter_search.side_effect = _api_error(429, "rate_limited")

    results = _run_all(
        ["notion_auth", "notion_shared_content", "notion_user_info"], gateway, {}
    )

    limited = results["notion_shared_content"]
    assert limited.status == CapabilityCheckStatus.INCOMPLETE
    assert limited.error_kind == CheckErrorKind.RATE_LIMITED
    assert limited.summary == "Rate limited by Notion"
    assert results["notion_user_info"].not_run_reason == CheckNotRunReason.RATE_LIMITED
    gateway.list_users.assert_not_called()


def test_a_failed_sign_in_stops_every_check_after_it() -> None:
    gateway = _gateway()
    gateway.get_bot_user.side_effect = _api_error(401, "unauthorized")

    results = _run_all(_ALL_CHECK_IDS, gateway, {})

    for check_id in (
        "notion_shared_content",
        "notion_page_content",
        "notion_database_rows",
        "notion_user_info",
    ):
        assert results[check_id].status == CapabilityCheckStatus.SKIPPED
        assert results[check_id].blocked_by == "notion_auth"
    assert (
        results["notion_shared_content"].summary == "Not run: Sign in to Notion failed"
    )
    gateway.iter_search.assert_not_called()


def test_an_api_error_carries_the_request_and_body() -> None:
    gateway = _gateway()
    gateway.get_bot_user.side_effect = NotionApiError(
        "500",
        status_code=500,
        code="internal_server_error",
        method="GET",
        url="https://api.notion.com/v1/users/me",
        body='{"code": "internal_server_error"}',
    )

    result = _run("notion_auth", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "Unexpected response from Notion"
    assert result.error_detail is not None
    assert result.error_detail.request == "GET api.notion.com/v1/users/me"
    assert result.error_detail.response_excerpt == '{"code": "internal_server_error"}'


# --- Find shared pages ---


def test_shared_pages_names_the_page() -> None:
    gateway = _titled_gateway(pages=[_page("Roadmap")])

    assert _run("notion_shared_content", gateway).summary == "Found shared page Roadmap"


def test_shared_pages_names_a_database_when_no_page_is_shared() -> None:
    gateway = _titled_gateway(pages=[], data_sources=[_data_source("Tasks")])

    result = _run("notion_shared_content", gateway)

    assert result.status == CapabilityCheckStatus.PASSED
    assert result.summary == "Found shared database Tasks"


def test_nothing_shared_fails_the_first_check_that_reads_the_scope() -> None:
    result = _run("notion_shared_content", _gateway(pages=[], data_sources=[]))

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_kind == CheckErrorKind.PERMISSION
    assert result.summary == "No pages shared with the integration"


def test_a_long_title_is_cut() -> None:
    gateway = _titled_gateway(pages=[_page("Quarterly planning notes for 2027")])

    assert (
        _run("notion_shared_content", gateway).summary
        == "Found shared page Quarterly planning note…"
    )


def test_search_without_read_content_names_the_capability() -> None:
    gateway = _gateway()
    gateway.iter_search.side_effect = _api_error(403, "restricted_resource")

    result = _run("notion_shared_content", gateway)

    assert result.summary == "Integration cannot read content"
    assert result.description is not None
    assert "select Read content" in result.description


# --- Find root page ---


def test_root_page_names_the_page() -> None:
    gateway = _gateway()
    gateway.get_page.return_value = _page("Handbook")

    result = _run("notion_root_page", gateway, {"root_page_id": "root"})

    assert result.summary == "Read root page Handbook"


def test_root_page_names_a_wiki() -> None:
    gateway = _gateway()
    gateway.get_page.side_effect = _api_error(404, "object_not_found")
    gateway.get_database.return_value = {"object": "database", **_data_source("Wiki")}

    result = _run("notion_root_page", gateway, {"root_page_id": "root"})

    assert result.summary == "Read root page Wiki"


@pytest.mark.parametrize(
    "status,summary,error_kind",
    [
        (404, "Root page not found or not shared", CheckErrorKind.INVALID),
        (400, "Root page ID is not valid", CheckErrorKind.INVALID),
        (403, "Integration cannot read content", CheckErrorKind.PERMISSION),
    ],
)
def test_root_page_failures_have_the_design_lines(
    status: int, summary: str, error_kind: CheckErrorKind
) -> None:
    gateway = _gateway()
    gateway.get_page.side_effect = _api_error(status)
    gateway.get_database.side_effect = _api_error(status)

    result = _run("notion_root_page", gateway, {"root_page_id": "root"})

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_kind == error_kind
    assert result.summary == summary


def test_a_run_without_config_reads_every_shared_page() -> None:
    """No config means no root page, as in indexing: the root page check does
    not apply, and page content runs after the shared pages check."""
    gateway = _titled_gateway(pages=[_page("Roadmap")])

    results = _run_all(_ALL_CHECK_IDS, gateway, None)

    assert not results["notion_root_page"].applicable
    assert results["notion_shared_content"].status == CapabilityCheckStatus.PASSED
    assert results["notion_page_content"].status == CapabilityCheckStatus.PASSED


def test_page_content_runs_after_the_root_page() -> None:
    gateway = _gateway()
    gateway.get_page.side_effect = _api_error(400, "validation_error")

    results = _run_all(_ALL_CHECK_IDS, gateway, {"root_page_id": "root"})

    assert not results["notion_shared_content"].applicable
    content = results["notion_page_content"]
    assert content.status == CapabilityCheckStatus.SKIPPED
    assert content.not_run_reason == CheckNotRunReason.DEPENDENCY_FAILED
    assert content.summary == "Not run: Find root page failed"
    gateway.get_block_children.assert_not_called()
    # The other checks run after sign-in only.
    assert results["notion_database_rows"].status == CapabilityCheckStatus.PASSED
    assert results["notion_user_info"].status == CapabilityCheckStatus.PASSED


# --- Sample page content ---


def test_page_content_names_the_page() -> None:
    gateway = _titled_gateway(pages=[_page("Roadmap")])

    assert _run("notion_page_content", gateway).summary == "Read content of Roadmap"


def test_unreadable_content_of_a_found_page_is_a_denial() -> None:
    gateway = _gateway()
    gateway.get_block_children.side_effect = _api_error(404, "object_not_found")

    result = _run("notion_page_content", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_kind == CheckErrorKind.PERMISSION
    assert result.summary == "Page found but content unreadable"


def test_page_content_is_incomplete_when_the_root_page_has_no_blocks() -> None:
    gateway = _gateway(pages=[])
    gateway.get_block_children.side_effect = _api_error(404, "object_not_found")

    result = _run("notion_page_content", gateway, {"root_page_id": "root"})

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.error_kind == CheckErrorKind.INCONCLUSIVE
    assert result.summary == "No page content to sample"


# --- Sample database rows ---


def test_database_rows_names_the_database() -> None:
    gateway = _titled_gateway(data_sources=[_data_source("Tasks")])
    gateway.query_data_source.return_value = {"results": [{"id": "row-1"}]}

    result = _run("notion_database_rows", gateway)

    assert result.status == CapabilityCheckStatus.PASSED
    assert result.summary == "Read a row of Tasks"
    assert not result.advisories


def test_an_empty_database_passes_with_a_caveat() -> None:
    gateway = _titled_gateway(data_sources=[_data_source("Tasks")])

    result = _run("notion_database_rows", gateway)

    assert result.status == CapabilityCheckStatus.PASSED
    assert result.summary == "Queried Tasks"
    assert len(result.advisories) == 1


def test_database_rows_without_read_content_names_the_capability() -> None:
    gateway = _gateway()
    gateway.query_data_source.side_effect = _api_error(403, "restricted_resource")

    result = _run("notion_database_rows", gateway)

    assert result.summary == "Integration cannot read database rows"


# --- Read user names ---


@pytest.mark.parametrize(
    "users,has_more,summary",
    [
        ([{"id": "u1"}], False, "Names readable for 1 user"),
        ([{"id": "u1"}, {"id": "u2"}], False, "Names readable for 2 users"),
        ([{"id": "u1"}, {"id": "u2"}], True, "Names readable for 2+ users"),
    ],
)
def test_user_names_counts_the_users(
    users: list[dict[str, Any]], has_more: bool, summary: str
) -> None:
    gateway = _gateway()
    gateway.list_users.return_value = {"results": users, "has_more": has_more}

    assert _run("notion_user_info", gateway).summary == summary


def test_user_names_without_the_capability_says_so() -> None:
    gateway = _gateway()
    gateway.list_users.side_effect = _api_error(403, "restricted_resource")

    result = _run("notion_user_info", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Integration cannot read user names"
    assert result.description is not None
    assert "Read user information" in result.description
