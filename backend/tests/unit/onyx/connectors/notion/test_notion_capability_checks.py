from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
)
from onyx.connectors.capability_checks.registry import get_capability_checks
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.notion.capability_checks import build_notion_indexing_checks
from onyx.connectors.notion.connector import NotionConnector
from onyx.connectors.notion.models import NotionSearchObjectType, NotionSearchResponse
from onyx.connectors.notion.source_operations import (
    NotionApiError,
    NotionSourceOperations,
)

_CREDENTIAL = {"notion_integration_token": "secret"}
_PAGE = {"id": "page-1", "object": "page"}
_DATA_SOURCE = {
    "id": "ds-1",
    "object": "data_source",
    "parent": {"type": "database_id", "database_id": "db-1"},
}


def _search_page(results: list[dict[str, Any]]) -> NotionSearchResponse:
    return NotionSearchResponse(results=results, next_cursor=None, has_more=False)


def _gateway(
    *,
    pages: list[dict[str, Any]] | None = None,
    data_sources: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """A workspace that shares the given pages and data sources."""
    shared: dict[NotionSearchObjectType, list[dict[str, Any]]] = {
        NotionSearchObjectType.PAGE: [_PAGE] if pages is None else pages,
        NotionSearchObjectType.DATA_SOURCE: (
            [_DATA_SOURCE] if data_sources is None else data_sources
        ),
    }

    def iter_search(
        *, object_type: NotionSearchObjectType, **_kwargs: Any
    ) -> Iterator[NotionSearchResponse]:
        return iter([_search_page(shared[object_type])])

    gateway: MagicMock = create_autospec(NotionSourceOperations, instance=True)
    gateway.iter_search.side_effect = iter_search
    gateway.get_bot_user.return_value = {"object": "user", "type": "bot"}
    gateway.get_page.return_value = {"object": "page", "id": "root"}
    gateway.get_database.return_value = {"object": "database", "id": "db-1"}
    gateway.get_block_children.return_value = {"results": [], "next_cursor": None}
    gateway.query_data_source.return_value = {"results": [], "next_cursor": None}
    gateway.list_users.return_value = {"results": [], "next_cursor": None}
    return gateway


def _api_error(status: int | None, code: str | None = None) -> NotionApiError:
    return NotionApiError(f"HTTP {status} {code}", status_code=status, code=code)


def _run(
    check_id: str,
    gateway: MagicMock,
    config: dict[str, Any] | None = None,
) -> CapabilityCheckResult:
    checks: list[CapabilityCheck] = [
        check for check in build_notion_indexing_checks() if check.check_id == check_id
    ]
    context: CapabilityCheckContext = CapabilityCheckContext(
        source=DocumentSource.NOTION,
        credential_json=_CREDENTIAL,
        connector_specific_config=config if config is not None else {},
        source_operations=gateway,
    )
    (result,) = run_capability_checks(checks, context)
    return result


def test_named_checks_replace_the_fallback() -> None:
    checks: list[CapabilityCheck] = get_capability_checks(DocumentSource.NOTION)

    assert not any(check.is_fallback for check in checks)


def test_every_check_probes_without_waiting_on_rate_limits() -> None:
    """Every call a check makes is fast, so a rate limit raises at once."""
    gateway: MagicMock = _gateway()

    for check in build_notion_indexing_checks():
        _run(check.check_id, gateway, {"root_page_id": "root"})

    calls = [call for call in gateway.mock_calls if call[0]]
    assert calls
    assert all(kwargs.get("fast") is True for _name, _args, kwargs in calls)


# --- notion_auth ---


def test_auth_passes() -> None:
    result: CapabilityCheckResult = _run("notion_auth", _gateway())

    assert result.status == CapabilityCheckStatus.PASSED


def test_auth_fails_for_a_rejected_token() -> None:
    gateway: MagicMock = _gateway()
    gateway.get_bot_user.side_effect = _api_error(401, "unauthorized")

    result: CapabilityCheckResult = _run("notion_auth", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_type == "CredentialExpiredError"


@pytest.mark.parametrize(
    "error",
    [
        _api_error(429, "rate_limited"),
        _api_error(503, "service_unavailable"),
        _api_error(None),
    ],
    ids=["rate-limited", "unavailable", "network"],
)
def test_auth_is_incomplete_for_transient_errors(error: NotionApiError) -> None:
    gateway: MagicMock = _gateway()
    gateway.get_bot_user.side_effect = error

    result: CapabilityCheckResult = _run("notion_auth", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE


# --- notion_shared_content ---


def test_shared_content_passes_with_a_shared_page() -> None:
    result: CapabilityCheckResult = _run("notion_shared_content", _gateway())

    assert result.status == CapabilityCheckStatus.PASSED


def test_shared_content_passes_with_only_a_shared_database() -> None:
    result: CapabilityCheckResult = _run("notion_shared_content", _gateway(pages=[]))

    assert result.status == CapabilityCheckStatus.PASSED


def test_shared_content_fails_when_nothing_is_shared() -> None:
    gateway: MagicMock = _gateway(pages=[], data_sources=[])

    result: CapabilityCheckResult = _run("notion_shared_content", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_type == "InsufficientPermissionsError"
    assert "Connections" in result.message


def test_shared_content_fails_without_the_read_content_capability() -> None:
    gateway: MagicMock = _gateway()
    gateway.iter_search.side_effect = _api_error(403, "restricted_resource")

    result: CapabilityCheckResult = _run("notion_shared_content", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert "Read content" in result.message


def test_shared_content_does_not_apply_with_a_root_page() -> None:
    result: CapabilityCheckResult = _run(
        "notion_shared_content", _gateway(), {"root_page_id": "root"}
    )

    assert not result.applicable


# --- notion_root_page ---


def test_root_page_applies_only_with_a_root_page() -> None:
    assert not _run("notion_root_page", _gateway()).applicable


def test_root_page_skips_a_run_without_config() -> None:
    """A credential-time run has no config: the check skips and calls
    nothing."""
    gateway: MagicMock = _gateway()
    (check,) = [
        check
        for check in build_notion_indexing_checks()
        if check.check_id == "notion_root_page"
    ]
    context: CapabilityCheckContext = CapabilityCheckContext(
        source=DocumentSource.NOTION,
        credential_json=_CREDENTIAL,
        connector_specific_config=None,
        source_operations=gateway,
    )

    (result,) = run_capability_checks([check], context)

    assert result.status == CapabilityCheckStatus.SKIPPED
    gateway.get_page.assert_not_called()


def test_connector_reads_a_blank_root_page_id_as_unset() -> None:
    """The checks and indexing read the same root page ID."""
    assert NotionConnector(root_page_id="   ").root_page_id is None
    assert NotionConnector(root_page_id=" root ").root_page_id == "root"


def test_root_page_passes() -> None:
    gateway: MagicMock = _gateway()

    result: CapabilityCheckResult = _run(
        "notion_root_page", gateway, {"root_page_id": " root "}
    )

    assert result.status == CapabilityCheckStatus.PASSED
    gateway.get_page.assert_called_once_with(page_id="root", fast=True)
    gateway.get_database.assert_not_called()


def test_root_page_passes_for_a_wiki() -> None:
    """A page that became a wiki is a database; indexing reads it as one."""
    gateway: MagicMock = _gateway()
    gateway.get_page.side_effect = _api_error(404, "object_not_found")

    result: CapabilityCheckResult = _run(
        "notion_root_page", gateway, {"root_page_id": "root"}
    )

    assert result.status == CapabilityCheckStatus.PASSED
    gateway.get_database.assert_called_once_with(database_id="root", fast=True)


def test_root_page_fails_when_not_shared() -> None:
    gateway: MagicMock = _gateway()
    gateway.get_page.side_effect = _api_error(404, "object_not_found")
    gateway.get_database.side_effect = _api_error(404, "object_not_found")

    result: CapabilityCheckResult = _run(
        "notion_root_page", gateway, {"root_page_id": "root"}
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_type == "ConnectorValidationError"
    assert "shared with the integration" in result.message


def test_root_page_fails_for_an_invalid_id() -> None:
    gateway: MagicMock = _gateway()
    gateway.get_page.side_effect = _api_error(400, "validation_error")

    result: CapabilityCheckResult = _run(
        "notion_root_page", gateway, {"root_page_id": "My Page"}
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert "not a valid Notion page ID" in result.message
    gateway.get_database.assert_not_called()


# --- notion_page_content ---


def test_page_content_reads_a_searched_page() -> None:
    gateway: MagicMock = _gateway()

    result: CapabilityCheckResult = _run("notion_page_content", gateway)

    assert result.status == CapabilityCheckStatus.PASSED
    gateway.get_block_children.assert_called_once_with(
        block_id="page-1", page_size=1, fast=True
    )


def test_page_content_reads_the_root_page_when_search_is_empty() -> None:
    gateway: MagicMock = _gateway(pages=[])

    result: CapabilityCheckResult = _run(
        "notion_page_content", gateway, {"root_page_id": "root"}
    )

    assert result.status == CapabilityCheckStatus.PASSED
    gateway.get_block_children.assert_called_once_with(
        block_id="root", page_size=1, fast=True
    )


def test_page_content_is_incomplete_when_nothing_is_shared() -> None:
    result: CapabilityCheckResult = _run(
        "notion_page_content", _gateway(pages=[], data_sources=[])
    )

    assert result.status == CapabilityCheckStatus.INCOMPLETE


def test_page_content_passes_when_only_empty_databases_are_shared() -> None:
    """Sharing a database alone is a valid setup; with no row there is no page
    content to read."""
    gateway: MagicMock = _gateway(pages=[])

    result: CapabilityCheckResult = _run("notion_page_content", gateway)

    assert result.status == CapabilityCheckStatus.PASSED
    gateway.get_block_children.assert_not_called()


def test_page_content_fails_without_the_read_content_capability() -> None:
    gateway: MagicMock = _gateway()
    gateway.get_block_children.side_effect = _api_error(403, "restricted_resource")

    result: CapabilityCheckResult = _run("notion_page_content", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_type == "InsufficientPermissionsError"


def test_page_content_leaves_an_unreadable_root_page_to_its_check() -> None:
    gateway: MagicMock = _gateway(pages=[])
    gateway.get_block_children.side_effect = _api_error(404, "object_not_found")

    result: CapabilityCheckResult = _run(
        "notion_page_content", gateway, {"root_page_id": "root"}
    )

    assert result.status == CapabilityCheckStatus.INCOMPLETE


# --- notion_database_rows ---


def test_database_rows_reads_one_row() -> None:
    gateway: MagicMock = _gateway()

    result: CapabilityCheckResult = _run("notion_database_rows", gateway)

    assert result.status == CapabilityCheckStatus.PASSED
    assert not result.required
    gateway.get_database.assert_called_once_with(database_id="db-1", fast=True)
    gateway.query_data_source.assert_called_once_with(
        data_source_id="ds-1", page_size=1, fast=True
    )


def test_database_rows_passes_without_databases() -> None:
    gateway: MagicMock = _gateway(data_sources=[])

    result: CapabilityCheckResult = _run("notion_database_rows", gateway)

    assert result.status == CapabilityCheckStatus.PASSED
    gateway.query_data_source.assert_not_called()


@pytest.mark.parametrize(
    "error,error_type",
    [
        (_api_error(403, "restricted_resource"), "InsufficientPermissionsError"),
        (_api_error(404, "object_not_found"), "ConnectorValidationError"),
    ],
)
def test_database_rows_fails_when_rows_are_not_readable(
    error: NotionApiError, error_type: str
) -> None:
    gateway: MagicMock = _gateway()
    gateway.query_data_source.side_effect = error

    result: CapabilityCheckResult = _run("notion_database_rows", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_type == error_type


# --- notion_user_info ---


def test_user_info_passes() -> None:
    gateway: MagicMock = _gateway()

    result: CapabilityCheckResult = _run("notion_user_info", gateway)

    assert result.status == CapabilityCheckStatus.PASSED
    assert not result.required


def test_user_info_warns_without_the_user_capability() -> None:
    gateway: MagicMock = _gateway()
    gateway.list_users.side_effect = _api_error(403, "restricted_resource")

    result: CapabilityCheckResult = _run("notion_user_info", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert not result.required
    assert "without email addresses" in result.message


def test_user_info_is_incomplete_when_rate_limited() -> None:
    gateway: MagicMock = _gateway()
    gateway.list_users.side_effect = _api_error(429, "rate_limited")

    result: CapabilityCheckResult = _run("notion_user_info", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
