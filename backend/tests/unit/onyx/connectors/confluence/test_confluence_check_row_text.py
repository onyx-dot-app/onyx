"""The Confluence checks' row text: names, the line and description of each
outcome, the account type's line of what is needed, and merged rows."""

from typing import Any
from unittest.mock import MagicMock, create_autospec

import requests
from requests import HTTPError

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckErrorKind,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.confluence.capability_checks import (
    build_confluence_doc_permission_sync_checks,
    build_confluence_group_sync_checks,
    build_confluence_indexing_checks,
)
from onyx.connectors.confluence.source_operations import (
    ConfluenceSourceOperations,
)

_WIKI_BASE = "https://acme.atlassian.net/wiki"
_EMAIL = "service-account@acme.com"
_OAUTH = {"confluence_refresh_token": "refresh", "cloud_id": "c1"}
_API_TOKEN = {"confluence_username": _EMAIL, "confluence_access_token": "t"}


def _form(**overrides: Any) -> dict[str, Any]:
    return {"wiki_base": _WIKI_BASE, "is_cloud": True, "space": "", **overrides}


def _http_error(status: int, body: bytes = b'{"message": "mock"}') -> HTTPError:
    response = requests.Response()
    response.status_code = status
    response.url = f"{_WIKI_BASE}/rest/api/space"
    response._content = body
    return HTTPError(response=response)


def _gateway() -> MagicMock:
    gateway = create_autospec(ConfluenceSourceOperations, instance=True)
    gateway.list_spaces.side_effect = lambda **_: iter(
        [{"key": "ENG", "name": "Engineering"}, {"key": "KB", "name": "Knowledge"}]
    )
    gateway.get_space.return_value = {"key": "ENG", "name": "Engineering"}
    return gateway


def _results(
    gateway: MagicMock,
    credential_json: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> dict[str, CapabilityCheckResult]:
    context = CapabilityCheckContext(
        source=DocumentSource.CONFLUENCE,
        credential_json=credential_json,
        connector_specific_config=config or _form(),
        source_operations=gateway,
    )
    checks = [
        check
        for check in build_confluence_indexing_checks()
        if check.check_id
        in {"confluence_auth", "confluence_spaces_visible", "confluence_space_listing"}
    ]
    return {
        result.check_id: result for result in run_capability_checks(checks, context)
    }


def test_sign_in_names_the_account_and_list_spaces_counts() -> None:
    results = _results(_gateway(), _API_TOKEN)

    assert results["confluence_auth"].summary == f"Signed in as {_EMAIL}"
    assert results["confluence_spaces_visible"].summary == "Spaces visible"
    assert results["confluence_space_listing"].summary == "2 spaces visible"


def test_oauth_sign_in_names_no_user() -> None:
    assert _results(_gateway(), _OAUTH)["confluence_auth"].summary == "Signed in"


def test_an_anonymous_403_on_sign_in_is_a_rejected_api_token() -> None:
    gateway = _gateway()
    gateway.probe_site.side_effect = _http_error(
        403,
        b'{"message": "Request rejected because caller cannot access Confluence"}',
    )

    result = _results(gateway, _API_TOKEN)["confluence_auth"]

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_kind == CheckErrorKind.REJECTED
    assert result.summary == "Sign-in rejected"


def test_a_403_on_oauth_sign_in_is_no_access() -> None:
    gateway = _gateway()
    gateway.probe_site.side_effect = _http_error(
        403,
        b'{"message": "Request rejected because caller cannot access Confluence"}',
    )

    result = _results(gateway, _OAUTH)["confluence_auth"]

    assert result.error_kind == CheckErrorKind.PERMISSION
    assert result.summary == "No Confluence access on this site"


def test_a_denied_probe_names_what_the_account_type_needs() -> None:
    gateway = _gateway()
    gateway.list_spaces.side_effect = _http_error(403)

    oauth = _results(gateway, _OAUTH)["confluence_spaces_visible"]
    token = _results(gateway, _API_TOKEN)["confluence_spaces_visible"]

    assert oauth.summary == token.summary == "No permission to list spaces"
    assert oauth.description == (
        "The account cannot list spaces. (HTTP 403)\n"
        "Required scope: read:space:confluence"
    )
    assert token.description == (
        "The account cannot list spaces. (HTTP 403)\n"
        "Give the token's user view permission on the spaces to index."
    )


def test_variants_and_steps_share_a_row() -> None:
    checks = [
        *build_confluence_indexing_checks(),
        *build_confluence_doc_permission_sync_checks(),
        *build_confluence_group_sync_checks(),
    ]
    rows: dict[str, set[str]] = {}
    for check in checks:
        rows.setdefault(check.row_id, set()).add(check.check_id)

    assert rows["confluence_auth"] == {
        "confluence_auth",
        "confluence_scoped_token_auth",
    }
    assert rows["confluence_spaces_visible"] == {
        "confluence_spaces_visible",
        "confluence_space_listing",
    }
    assert len(rows["confluence_space_permissions_read"]) == 3
    # 25 checks on the 17 rows of the design.
    assert len({check.check_id for check in checks}) == 25
    assert len(rows) == 17
    assert all(len(check.display_name) <= 24 for check in checks)
