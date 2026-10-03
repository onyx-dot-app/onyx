"""Behavior tests for the Confluence capability checks.

Every test runs a check against an autospecced ``ConfluenceSourceOperations``.
The readiness tests use the config the web form sends: every tab's fields, with
"" for the empty ones.
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, create_autospec
from urllib.parse import unquote

import pytest
import requests
from requests import HTTPError

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.draft_runs import (
    DraftCheckStateKind,
    decide_draft_check_state,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityVerdict,
    CredentialCapability,
    compute_capability_verdicts,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.confluence.capability_checks import (
    build_confluence_indexing_checks,
)
from onyx.connectors.confluence.source_operations import (
    ConfluenceNoVisibleSpacesError,
    ConfluenceProbeVariant,
    ConfluenceRetriesExhaustedError,
    ConfluenceSearchVariant,
    ConfluenceSourceOperations,
    ConfluenceSpaceNotFoundError,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)

_CHECKS_BY_ID = {check.check_id: check for check in build_confluence_indexing_checks()}
_WIKI_BASE = "https://acme.atlassian.net/wiki"
_PAGE = {
    "id": "42",
    "type": "page",
    "body": {"storage": {"value": "<p>hi</p>"}},
    "version": {"by": {"accountId": "acct-1"}},
}
_MODE_CHECK_IDS = {
    "confluence_configured_space",
    "confluence_configured_page",
    "confluence_cql_query",
}


def _form(**overrides: Any) -> dict[str, Any]:
    """The config the create form sends, with "" for empty tab fields."""
    return {
        "wiki_base": _WIKI_BASE,
        "is_cloud": True,
        "scoped_token": False,
        "space": "",
        "page_id": "",
        "index_recursively": True,
        "cql_query": "",
        "include_attachments": True,
        **overrides,
    }


def _http_error(status: int, url: str = f"{_WIKI_BASE}/rest/api") -> HTTPError:
    response = requests.Response()
    response.status_code = status
    response.url = url
    response.reason = "Mock"
    response._content = b'{"message": "mock detail"}'
    return HTTPError(response=response)


def _gateway() -> MagicMock:
    gateway = create_autospec(ConfluenceSourceOperations, instance=True)
    gateway.list_spaces.side_effect = lambda **_: iter([{"key": "KB"}])
    gateway.get_space.return_value = {"key": "KB"}
    gateway.search_pages.side_effect = lambda **_: iter([dict(_PAGE)])
    gateway.search_pages_from_url.side_effect = lambda **_: iter([dict(_PAGE)])
    gateway.search_comments.side_effect = lambda **_: iter([])
    gateway.search_attachments.side_effect = lambda **_: iter([])
    gateway.lookup_user_display_name.return_value = "Ada Lovelace"
    return gateway


def _context(
    gateway: MagicMock | None = None,
    config: dict[str, Any] | None = None,
    credential_json: dict[str, Any] | None = None,
) -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.CONFLUENCE,
        credential_json=credential_json or {},
        connector_specific_config=config,
        source_operations=gateway if gateway is not None else _gateway(),
    )


def _run(check_id: str, context: CapabilityCheckContext) -> None:
    _CHECKS_BY_ID[check_id].run(context)


def _draft_states(config: dict[str, Any] | None) -> dict[str, DraftCheckStateKind]:
    context = _context(config=config)
    return {
        check.check_id: decide_draft_check_state(check, context).state
        for check in build_confluence_indexing_checks()
    }


# Readiness: what runs for each form state.


def test_config_less_run_skips_every_check_and_the_verdict() -> None:
    context = _context(config=None)

    results = run_capability_checks(build_confluence_indexing_checks(), context)

    assert {result.status.value for result in results} == {"skipped"}
    verdicts = compute_capability_verdicts({CredentialCapability.INDEXING}, results)
    assert verdicts[CredentialCapability.INDEXING] == CapabilityVerdict.SKIPPED


def test_blank_site_url_waits_for_it() -> None:
    context = _context(config=_form(wiki_base=""))

    for check in build_confluence_indexing_checks():
        state = decide_draft_check_state(check, context)
        assert state.state == DraftCheckStateKind.WAITING, check.check_id
        assert state.missing_fields == ["wiki_base"], check.check_id


def test_blank_tab_fields_mean_everything_mode() -> None:
    states = _draft_states(_form())

    for check_id in _MODE_CHECK_IDS:
        assert states[check_id] == DraftCheckStateKind.NOT_APPLICABLE, check_id
    assert states["confluence_auth"] == DraftCheckStateKind.PENDING
    assert states["confluence_scoped_token_auth"] == DraftCheckStateKind.NOT_APPLICABLE
    assert states["confluence_content_read"] == DraftCheckStateKind.PENDING
    assert states["confluence_attachments_read"] == DraftCheckStateKind.PENDING


@pytest.mark.parametrize(
    "overrides,runnable_mode_check",
    [
        ({"space": "KB"}, "confluence_configured_space"),
        ({"space": "KB", "page_id": "42"}, "confluence_configured_page"),
        (
            {"space": "KB", "page_id": "42", "cql_query": "type=page"},
            "confluence_cql_query",
        ),
        ({"space": "  ", "page_id": "42"}, "confluence_configured_page"),
    ],
)
def test_mode_checks_follow_the_connector_precedence(
    overrides: dict[str, Any], runnable_mode_check: str
) -> None:
    states = _draft_states(_form(**overrides))

    for check_id in _MODE_CHECK_IDS:
        expected = (
            DraftCheckStateKind.PENDING
            if check_id == runnable_mode_check
            else DraftCheckStateKind.NOT_APPLICABLE
        )
        assert states[check_id] == expected, check_id


def test_absent_mode_fields_mean_everything_mode() -> None:
    states = _draft_states({"wiki_base": _WIKI_BASE, "is_cloud": False})

    for check_id in _MODE_CHECK_IDS:
        assert states[check_id] == DraftCheckStateKind.NOT_APPLICABLE, check_id
    assert states["confluence_content_read"] == DraftCheckStateKind.PENDING


def test_scoped_token_picks_the_scoped_auth_check() -> None:
    states = _draft_states(_form(scoped_token=True))

    assert states["confluence_auth"] == DraftCheckStateKind.NOT_APPLICABLE
    assert states["confluence_scoped_token_auth"] == DraftCheckStateKind.PENDING


def test_attachments_off_is_not_applicable() -> None:
    states = _draft_states(_form(include_attachments=False))

    assert states["confluence_attachments_read"] == DraftCheckStateKind.NOT_APPLICABLE


def test_full_run_in_space_mode_passes_the_indexing_verdict() -> None:
    gateway = _gateway()
    context = _context(gateway, _form(space="KB"))

    results = run_capability_checks(build_confluence_indexing_checks(), context)

    verdicts = compute_capability_verdicts({CredentialCapability.INDEXING}, results)
    assert verdicts[CredentialCapability.INDEXING] == CapabilityVerdict.PASSED
    gateway.probe_site.assert_called_once_with(variant=ConfluenceProbeVariant.UNSCOPED)


def test_indexing_checks_exercise_the_indexing_units_of_shared_operations() -> None:
    """``list_spaces``, ``search_pages`` and ``search_attachments`` are exempt
    from the coverage harness because they also serve permission sync, and
    ``download_attachment`` because the harness spy gives no attachment size.
    Their INDEXING units must still be exercised."""
    spy = _gateway()
    spy.search_attachments.side_effect = lambda **_: _attachments(10)

    results = run_capability_checks(
        build_confluence_indexing_checks(), _context(spy, _form(space="KB"))
    )

    assert all(result.error_type is None for result in results), results
    exercised: set[tuple[str, str | None]] = set()
    for name, _args, kwargs in spy.mock_calls:
        variant = kwargs.get("variant")
        exercised.add((name.split(".")[0], variant.value if variant else None))

    assert {
        ("list_spaces", None),
        ("search_pages", ConfluenceSearchVariant.CONTENT.value),
        ("search_attachments", ConfluenceSearchVariant.CONTENT.value),
        ("download_attachment", None),
    } <= exercised
    # The slim unit needs a page id or a CQL query in the config.
    gateway = _gateway()
    _run("confluence_configured_page", _context(gateway, _form(page_id="42")))
    assert (
        gateway.search_pages.call_args.kwargs["variant"] == ConfluenceSearchVariant.SLIM
    )


# confluence_auth / confluence_scoped_token_auth


def test_auth_passes() -> None:
    gateway = _gateway()

    _run("confluence_auth", _context(gateway, _form()))

    gateway.probe_site.assert_called_once_with(variant=ConfluenceProbeVariant.UNSCOPED)


def test_scoped_auth_uses_the_scoped_probe() -> None:
    gateway = _gateway()

    _run("confluence_scoped_token_auth", _context(gateway, _form(scoped_token=True)))

    gateway.probe_site.assert_called_once_with(variant=ConfluenceProbeVariant.SCOPED)


def test_auth_401_is_an_expired_credential() -> None:
    gateway = _gateway()
    gateway.probe_site.side_effect = _http_error(401)

    with pytest.raises(CredentialExpiredError, match="HTTP 401"):
        _run("confluence_auth", _context(gateway, _form()))


def test_auth_403_is_insufficient_permissions() -> None:
    gateway = _gateway()
    gateway.probe_site.side_effect = _http_error(403)

    with pytest.raises(InsufficientPermissionsError, match="HTTP 403"):
        _run("confluence_auth", _context(gateway, _form()))


def test_auth_404_names_the_site_url() -> None:
    gateway = _gateway()
    gateway.probe_site.side_effect = _http_error(404)

    with pytest.raises(ConnectorValidationError, match="ends in /wiki") as error:
        _run("confluence_auth", _context(gateway, _form()))
    assert _WIKI_BASE in str(error.value)


def test_auth_with_no_visible_space_leaves_it_to_the_spaces_check() -> None:
    gateway = _gateway()
    gateway.probe_site.side_effect = ConfluenceNoVisibleSpacesError("none")

    _run("confluence_auth", _context(gateway, _form()))


def test_scoped_auth_tenant_info_server_error_is_indeterminate() -> None:
    gateway = _gateway()
    gateway.probe_site.side_effect = _http_error(
        503, url="https://acme.atlassian.net/_edge/tenant_info"
    )

    with pytest.raises(UnexpectedValidationError, match="HTTP 503"):
        _run(
            "confluence_scoped_token_auth", _context(gateway, _form(scoped_token=True))
        )


def test_scoped_auth_tenant_info_failure_names_the_cloud_id() -> None:
    gateway = _gateway()
    gateway.probe_site.side_effect = _http_error(
        404, url="https://acme.atlassian.net/_edge/tenant_info"
    )

    with pytest.raises(ConnectorValidationError, match="cloud id"):
        _run(
            "confluence_scoped_token_auth", _context(gateway, _form(scoped_token=True))
        )


def test_auth_connection_error_is_indeterminate() -> None:
    gateway = _gateway()
    gateway.probe_site.side_effect = requests.ConnectionError("dns")

    with pytest.raises(UnexpectedValidationError, match="cannot connect"):
        _run("confluence_auth", _context(gateway, _form()))


# confluence_spaces_visible


def test_spaces_visible_passes() -> None:
    gateway = _gateway()

    _run("confluence_spaces_visible", _context(gateway, _form()))

    gateway.list_spaces.assert_called_once_with(limit=1)


def test_no_visible_space_fails() -> None:
    gateway = _gateway()
    gateway.list_spaces.side_effect = lambda **_: iter([])

    with pytest.raises(InsufficientPermissionsError, match="No Confluence space"):
        _run("confluence_spaces_visible", _context(gateway, _form()))


def test_spaces_403_names_the_oauth_scope() -> None:
    gateway = _gateway()
    gateway.list_spaces.side_effect = _http_error(403)

    with pytest.raises(InsufficientPermissionsError, match="read:space:confluence"):
        _run(
            "confluence_spaces_visible",
            _context(
                gateway, _form(), credential_json={"confluence_refresh_token": "r"}
            ),
        )


def test_spaces_403_names_the_classic_scope_for_a_scoped_token() -> None:
    gateway = _gateway()
    gateway.list_spaces.side_effect = _http_error(403)

    with pytest.raises(
        InsufficientPermissionsError, match="read:confluence-space.summary"
    ):
        _run("confluence_spaces_visible", _context(gateway, _form(scoped_token=True)))


# confluence_configured_space


def test_configured_space_passes() -> None:
    gateway = _gateway()

    _run("confluence_configured_space", _context(gateway, _form(space=" KB ")))

    gateway.get_space.assert_called_once_with(space_key="KB")


def test_configured_space_not_found_names_the_key() -> None:
    gateway = _gateway()
    gateway.get_space.side_effect = ConfluenceSpaceNotFoundError("missing")

    with pytest.raises(ConnectorValidationError, match="`NOPE`"):
        _run("confluence_configured_space", _context(gateway, _form(space="NOPE")))


def test_configured_space_401_is_an_expired_credential() -> None:
    gateway = _gateway()
    gateway.get_space.side_effect = _http_error(401)

    with pytest.raises(CredentialExpiredError):
        _run("confluence_configured_space", _context(gateway, _form(space="KB")))


# confluence_configured_page


def test_configured_page_searches_by_id() -> None:
    gateway = _gateway()

    _run("confluence_configured_page", _context(gateway, _form(page_id="42")))

    kwargs = gateway.search_pages.call_args.kwargs
    assert kwargs["cql"] == "type=page and id='42'"
    assert kwargs["limit"] == 1


def test_configured_page_must_be_a_number() -> None:
    gateway = _gateway()

    with pytest.raises(ConnectorValidationError, match="not a number"):
        _run("confluence_configured_page", _context(gateway, _form(page_id="Home")))
    gateway.search_pages.assert_not_called()


def test_configured_page_not_found() -> None:
    gateway = _gateway()
    gateway.search_pages.side_effect = lambda **_: iter([])

    with pytest.raises(ConnectorValidationError, match="No page with the ID `42`"):
        _run("confluence_configured_page", _context(gateway, _form(page_id="42")))


# confluence_cql_query


def test_cql_query_runs_the_connector_query() -> None:
    gateway = _gateway()

    _run(
        "confluence_cql_query",
        _context(gateway, _form(cql_query="type=page and space=KB")),
    )

    cql = gateway.search_pages.call_args.kwargs["cql"]
    assert cql.startswith("type=page and space=KB")
    assert cql.endswith(" order by lastmodified asc")


@pytest.mark.parametrize(
    "cql,message",
    [
        ("type=page and lastModified > now('-1d')", "lastModified"),
        ("type=page and LASTMODIFIED > now('-1d')", "lastModified"),
        ("type=page order by created", "ORDER BY"),
        ("type=page ORDER  BY created", "ORDER BY"),
    ],
)
def test_cql_query_rejects_filters_onyx_adds_itself(cql: str, message: str) -> None:
    gateway = _gateway()

    with pytest.raises(ConnectorValidationError, match=message):
        _run("confluence_cql_query", _context(gateway, _form(cql_query=cql)))
    gateway.search_pages.assert_not_called()


@pytest.mark.parametrize(
    "cql",
    [
        'type=page and text ~ "how order by works"',
        "type=page and title ~ 'lastModified notes'",
    ],
)
def test_cql_query_ignores_the_words_in_quoted_values(cql: str) -> None:
    gateway = _gateway()

    _run("confluence_cql_query", _context(gateway, _form(cql_query=cql)))

    gateway.search_pages.assert_called_once()


def _results(*types: str) -> Iterator[dict[str, Any]]:
    return iter([{"id": str(index), "type": kind} for index, kind in enumerate(types)])


@pytest.mark.parametrize(
    "cql,types",
    [
        ("type in (page)", ("page", "page")),
        ("space=OR", ("page",)),
        ("type=page and (space=KB or space=ENG)", ("page", "page", "page")),
    ],
)
def test_cql_query_that_returns_only_pages_passes(
    cql: str, types: tuple[str, ...]
) -> None:
    gateway = _gateway()
    gateway.search_pages.side_effect = lambda **_: _results(*types)

    _run("confluence_cql_query", _context(gateway, _form(cql_query=cql)))

    assert gateway.search_pages.call_args.kwargs["limit"] == 5


@pytest.mark.parametrize(
    "cql,types,found",
    [
        ("NOT (type=page)", ("blogpost",), "blogpost"),
        ("type=page or type=comment", ("page", "comment"), "comment"),
        (
            "type=page or type=blogpost or type=attachment",
            ("page", "blogpost", "attachment"),
            "attachment, blogpost",
        ),
    ],
)
def test_cql_query_that_returns_other_content_fails(
    cql: str, types: tuple[str, ...], found: str
) -> None:
    gateway = _gateway()
    gateway.search_pages.side_effect = lambda **_: _results(*types)

    with pytest.raises(ConnectorValidationError, match=f"found: {found}"):
        _run("confluence_cql_query", _context(gateway, _form(cql_query=cql)))


def test_cql_query_bad_syntax_shows_the_confluence_message() -> None:
    gateway = _gateway()
    gateway.search_pages.side_effect = _http_error(400)

    with pytest.raises(ConnectorValidationError, match="mock detail"):
        _run("confluence_cql_query", _context(gateway, _form(cql_query="type=page (")))


def test_cql_query_with_no_match_fails() -> None:
    gateway = _gateway()
    gateway.search_pages.side_effect = lambda **_: iter([])

    with pytest.raises(UnexpectedValidationError, match="matches no page"):
        _run("confluence_cql_query", _context(gateway, _form(cql_query="type=page")))


# confluence_content_read


def test_content_read_uses_the_indexing_url_for_the_scope() -> None:
    gateway = _gateway()

    _run("confluence_content_read", _context(gateway, _form(space="KB")))

    url = unquote(gateway.search_pages_from_url.call_args.kwargs["url"])
    assert url.startswith("rest/api/content/search?cql=type=page and space='KB'")
    assert "body.storage.value" in url
    assert url.endswith("limit=1")


def test_content_read_without_body_fails() -> None:
    gateway = _gateway()
    gateway.search_pages_from_url.side_effect = lambda **_: iter([{"id": "42"}])

    with pytest.raises(InsufficientPermissionsError, match="without its content"):
        _run("confluence_content_read", _context(gateway, _form()))


@pytest.mark.parametrize("overrides", [{}, {"space": "KB"}])
def test_content_read_with_an_empty_scope_is_indeterminate(
    overrides: dict[str, Any],
) -> None:
    gateway = _gateway()
    gateway.search_pages_from_url.side_effect = lambda **_: iter([])

    with pytest.raises(UnexpectedValidationError, match="no page"):
        _run("confluence_content_read", _context(gateway, _form(**overrides)))


# confluence_comments_read


def test_comments_read_searches_the_sample_page() -> None:
    gateway = _gateway()

    _run("confluence_comments_read", _context(gateway, _form()))

    cql = gateway.search_comments.call_args.kwargs["cql"]
    assert cql.startswith("type=comment and container='42'")


def test_comments_read_403_fails() -> None:
    gateway = _gateway()
    gateway.search_comments.side_effect = _http_error(403)

    with pytest.raises(InsufficientPermissionsError, match="comments"):
        _run("confluence_comments_read", _context(gateway, _form()))


@pytest.mark.parametrize(
    "check_id",
    [
        "confluence_comments_read",
        "confluence_attachments_read",
        "confluence_user_names",
    ],
)
def test_sample_probes_leave_a_rejected_scope_query_to_the_scope_checks(
    check_id: str,
) -> None:
    gateway = _gateway()
    gateway.search_pages.side_effect = _http_error(400)

    with pytest.raises(UnexpectedValidationError, match="scope settings"):
        _run(check_id, _context(gateway, _form(page_id="42")))


def test_comments_read_without_pages_passes() -> None:
    gateway = _gateway()
    gateway.search_pages.side_effect = lambda **_: iter([])

    _run("confluence_comments_read", _context(gateway, _form()))

    gateway.search_comments.assert_not_called()


# confluence_attachments_read


def _attachments(*sizes: int) -> Iterator[dict[str, Any]]:
    return iter(
        [
            {"id": f"att{index}", "title": "f.txt", "extensions": {"fileSize": size}}
            for index, size in enumerate(sizes)
        ]
    )


def test_attachments_none_found_passes_without_download() -> None:
    gateway = _gateway()

    _run("confluence_attachments_read", _context(gateway, _form()))

    gateway.search_attachments.assert_called_once()
    gateway.download_attachment.assert_not_called()


def test_attachments_downloads_the_smallest() -> None:
    gateway = _gateway()
    gateway.search_attachments.side_effect = lambda **_: _attachments(900, 10, 50)

    _run("confluence_attachments_read", _context(gateway, _form()))

    kwargs = gateway.download_attachment.call_args.kwargs
    assert kwargs["attachment"]["id"] == "att1"
    assert kwargs["parent_content_id"] == "42"


def test_attachments_too_large_proves_only_the_listing() -> None:
    gateway = _gateway()
    gateway.search_attachments.side_effect = lambda **_: _attachments(10**9)

    _run("confluence_attachments_read", _context(gateway, _form()))

    gateway.download_attachment.assert_not_called()


def test_attachments_without_a_known_size_prove_only_the_listing() -> None:
    gateway = _gateway()
    gateway.search_attachments.side_effect = lambda **_: iter(
        [{"id": "att0", "title": "f.txt", "extensions": {}}]
    )

    _run("confluence_attachments_read", _context(gateway, _form()))

    gateway.download_attachment.assert_not_called()


def test_attachments_download_403_fails() -> None:
    gateway = _gateway()
    gateway.search_attachments.side_effect = lambda **_: _attachments(10)
    gateway.download_attachment.side_effect = _http_error(403)

    with pytest.raises(InsufficientPermissionsError, match="HTTP 403"):
        _run("confluence_attachments_read", _context(gateway, _form()))


def test_attachments_listing_403_names_the_scope() -> None:
    gateway = _gateway()
    gateway.search_attachments.side_effect = _http_error(403)

    with pytest.raises(InsufficientPermissionsError, match="readonly:content"):
        _run(
            "confluence_attachments_read",
            _context(
                gateway, _form(), credential_json={"confluence_refresh_token": "r"}
            ),
        )


def test_attachments_download_retries_exhausted_is_indeterminate() -> None:
    gateway = _gateway()
    gateway.search_attachments.side_effect = lambda **_: _attachments(10)
    gateway.download_attachment.side_effect = ConfluenceRetriesExhaustedError(
        "Retries exhausted", last_status_code=429
    )

    with pytest.raises(UnexpectedValidationError, match="did not finish"):
        _run("confluence_attachments_read", _context(gateway, _form()))


# confluence_user_names


def test_user_names_resolve_the_page_author() -> None:
    gateway = _gateway()

    _run("confluence_user_names", _context(gateway, _form()))

    gateway.lookup_user_display_name.assert_called_once_with(user_id="acct-1")


def test_unknown_user_name_fails() -> None:
    gateway = _gateway()
    gateway.lookup_user_display_name.return_value = None

    with pytest.raises(InsufficientPermissionsError, match="Unknown Confluence User"):
        _run("confluence_user_names", _context(gateway, _form()))


@pytest.mark.parametrize(
    "error",
    [
        _http_error(429),
        _http_error(503),
        ConfluenceRetriesExhaustedError("exhausted", last_status_code=429),
        requests.Timeout("slow"),
    ],
)
def test_user_name_lookup_errors_are_indeterminate(error: Exception) -> None:
    gateway = _gateway()
    gateway.lookup_user_display_name.side_effect = error

    with pytest.raises(UnexpectedValidationError):
        _run("confluence_user_names", _context(gateway, _form()))


def test_user_names_without_an_author_pass() -> None:
    gateway = _gateway()
    gateway.search_pages.side_effect = lambda **_: iter([{"id": "42"}])

    _run("confluence_user_names", _context(gateway, _form()))

    gateway.lookup_user_display_name.assert_not_called()


def test_optional_checks_are_the_approved_ones() -> None:
    optional = {
        check.check_id
        for check in build_confluence_indexing_checks()
        if not check.required
    }

    assert optional == {
        "confluence_comments_read",
        "confluence_attachments_read",
        "confluence_user_names",
    }


def test_every_check_waits_for_the_site_fields() -> None:
    checks: list[CapabilityCheck[Any]] = list(build_confluence_indexing_checks())

    for check in checks:
        assert check.requires_fields == {"wiki_base", "is_cloud"}, check.check_id
        assert not check.requires_connector_instance, check.check_id
