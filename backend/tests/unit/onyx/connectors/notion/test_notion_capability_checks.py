"""Behaviour of the named Notion INDEXING checks: each probe composes the
gateway operations indexing uses, and every Notion answer maps onto the
validation-exception family the runner understands."""

from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
)
from onyx.connectors.capability_checks.registry import get_capability_checks
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.notion.capability_checks import build_notion_indexing_checks
from onyx.connectors.notion.source_operations import (
    NotionApiError,
    NotionSourceOperations,
    NotionTransportError,
)

_CHECKS_BY_ID = {check.check_id: check for check in build_notion_indexing_checks()}

_PAGE = {"id": "page-1", "object": "page"}
_DATA_SOURCE = {
    "id": "ds-1",
    "object": "data_source",
    "parent": {"type": "database_id", "database_id": "db-1"},
}


def _api_error(status_code: int) -> NotionApiError:
    return NotionApiError(status_code, {"object": "error"}, "https://api.notion.com")


def _gateway(search_results: list[dict[str, Any]] | None = None) -> MagicMock:
    gateway = create_autospec(NotionSourceOperations, instance=True)
    gateway.search.return_value = {
        "results": [_PAGE] if search_results is None else search_results,
        "has_more": False,
    }
    return gateway


def _context(
    gateway: MagicMock,
    credential_json: dict[str, Any] | None = None,
    connector_specific_config: dict[str, Any] | None = None,
) -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.NOTION,
        credential_json=(
            {"notion_integration_token": "ntn_test"}
            if credential_json is None
            else credential_json
        ),
        connector_specific_config=connector_specific_config,
        source_operations=gateway,
    )


def _run(check_id: str, context: CapabilityCheckContext) -> None:
    _CHECKS_BY_ID[check_id].run(context)


def test_registry_serves_the_named_checks_without_fallback() -> None:
    checks: list[CapabilityCheck] = get_capability_checks(DocumentSource.NOTION)
    assert {check.check_id for check in checks} == set(_CHECKS_BY_ID)
    assert not any(check.is_fallback for check in checks)


def test_token_auth_missing_token() -> None:
    gateway = _gateway()
    gateway.get_bot_user.side_effect = ConnectorMissingCredentialError("Notion")
    with pytest.raises(CredentialInvalidError):
        _run("notion_token_auth", _context(gateway, credential_json={}))


def test_token_auth_maps_401_to_expired() -> None:
    gateway = _gateway()
    gateway.get_bot_user.side_effect = _api_error(401)
    with pytest.raises(CredentialExpiredError):
        _run("notion_token_auth", _context(gateway))


def test_token_auth_transport_failure_is_indeterminate() -> None:
    gateway = _gateway()
    gateway.get_bot_user.side_effect = NotionTransportError("timed out")
    with pytest.raises(UnexpectedValidationError):
        _run("notion_token_auth", _context(gateway))


def test_token_auth_passes() -> None:
    gateway = _gateway()
    _run("notion_token_auth", _context(gateway))
    gateway.get_bot_user.assert_called_once_with()


def test_shared_pages_defers_to_the_root_page_check_when_configured() -> None:
    gateway = _gateway(search_results=[])
    _run(
        "notion_shared_pages",
        _context(gateway, connector_specific_config={"root_page_id": "root-1"}),
    )
    gateway.search.assert_not_called()


def test_missing_token_fails_every_check() -> None:
    gateway = _gateway()
    gateway.search.side_effect = ConnectorMissingCredentialError("Notion")
    with pytest.raises(CredentialInvalidError):
        _run("notion_page_content", _context(gateway, credential_json={}))


def test_shared_pages_fails_when_search_is_empty() -> None:
    with pytest.raises(ConnectorValidationError, match="No page is shared"):
        _run("notion_shared_pages", _context(_gateway(search_results=[])))


def test_shared_pages_rate_limit_is_indeterminate() -> None:
    gateway = _gateway()
    gateway.search.side_effect = _api_error(429)
    with pytest.raises(UnexpectedValidationError):
        _run("notion_shared_pages", _context(gateway))


def test_shared_pages_passes_with_one_result() -> None:
    gateway = _gateway()
    _run("notion_shared_pages", _context(gateway))
    assert gateway.search.call_args.kwargs["query"]["page_size"] == 1


def test_root_page_check_requires_the_field() -> None:
    check = _CHECKS_BY_ID["notion_root_page"]
    assert check.requires_fields == frozenset({"root_page_id"})
    assert check.requires_connector_config


def test_root_page_passes_on_a_page() -> None:
    gateway = _gateway()
    _run(
        "notion_root_page",
        _context(gateway, connector_specific_config={"root_page_id": "root-1"}),
    )
    gateway.get_page.assert_called_once_with(page_id="root-1")
    gateway.get_database.assert_not_called()


def test_root_page_falls_back_to_a_database_for_a_wiki() -> None:
    gateway = _gateway()
    gateway.get_page.side_effect = _api_error(404)
    _run(
        "notion_root_page",
        _context(gateway, connector_specific_config={"root_page_id": "root-1"}),
    )
    gateway.get_database.assert_called_once_with(database_id="root-1")


def test_root_page_unshared_fails_after_both_fetches() -> None:
    gateway = _gateway()
    gateway.get_page.side_effect = _api_error(404)
    gateway.get_database.side_effect = _api_error(404)
    with pytest.raises(ConnectorValidationError, match="root page `root-1`"):
        _run(
            "notion_root_page",
            _context(gateway, connector_specific_config={"root_page_id": "root-1"}),
        )


def test_root_page_malformed_id_is_a_failure() -> None:
    gateway = _gateway()
    gateway.get_page.side_effect = _api_error(400)
    gateway.get_database.side_effect = _api_error(400)
    with pytest.raises(ConnectorValidationError, match="HTTP 400"):
        _run(
            "notion_root_page",
            _context(gateway, connector_specific_config={"root_page_id": "not-an-id"}),
        )


def test_root_page_5xx_is_indeterminate_without_a_database_fetch() -> None:
    gateway = _gateway()
    gateway.get_page.side_effect = _api_error(502)
    with pytest.raises(UnexpectedValidationError):
        _run(
            "notion_root_page",
            _context(gateway, connector_specific_config={"root_page_id": "root-1"}),
        )
    gateway.get_database.assert_not_called()


def test_root_page_401_does_not_try_the_database() -> None:
    gateway = _gateway()
    gateway.get_page.side_effect = _api_error(401)
    with pytest.raises(CredentialExpiredError):
        _run(
            "notion_root_page",
            _context(gateway, connector_specific_config={"root_page_id": "root-1"}),
        )
    gateway.get_database.assert_not_called()


def test_page_content_reads_the_first_shared_page() -> None:
    gateway = _gateway()
    _run("notion_page_content", _context(gateway))
    gateway.get_page.assert_called_once_with(page_id="page-1")
    gateway.list_block_children.assert_called_once_with(block_id="page-1")


def test_page_content_reads_the_configured_root_without_searching() -> None:
    gateway: MagicMock = _gateway(search_results=[])
    _run(
        "notion_page_content",
        _context(gateway, connector_specific_config={"root_page_id": "root-1"}),
    )
    gateway.search.assert_not_called()
    gateway.list_block_children.assert_called_once_with(block_id="root-1")


def test_page_content_unshared_root_fails() -> None:
    gateway: MagicMock = _gateway(search_results=[])
    gateway.list_block_children.side_effect = _api_error(404)
    with pytest.raises(ConnectorValidationError, match="root page `root-1`"):
        _run(
            "notion_page_content",
            _context(gateway, connector_specific_config={"root_page_id": "root-1"}),
        )


def test_page_content_skips_without_pages() -> None:
    gateway = _gateway(search_results=[])
    _run("notion_page_content", _context(gateway))
    gateway.list_block_children.assert_not_called()


def test_page_content_403_is_insufficient_permissions() -> None:
    gateway = _gateway()
    gateway.list_block_children.side_effect = _api_error(403)
    with pytest.raises(InsufficientPermissionsError):
        _run("notion_page_content", _context(gateway))


def test_database_query_is_not_required() -> None:
    assert _CHECKS_BY_ID["notion_database_query"].required is False


def test_database_query_reads_database_and_data_source() -> None:
    gateway = _gateway(search_results=[_DATA_SOURCE])
    _run("notion_database_query", _context(gateway))
    gateway.get_database.assert_called_once_with(database_id="db-1")
    gateway.query_data_source.assert_called_once_with(data_source_id="ds-1")


def test_database_query_skips_without_databases() -> None:
    gateway = _gateway(search_results=[])
    _run("notion_database_query", _context(gateway))
    gateway.get_database.assert_not_called()
    gateway.query_data_source.assert_not_called()


def test_database_query_unshared_database_fails() -> None:
    gateway = _gateway(search_results=[_DATA_SOURCE])
    gateway.query_data_source.side_effect = _api_error(404)
    with pytest.raises(ConnectorValidationError, match="db-1"):
        _run("notion_database_query", _context(gateway))
