"""Error details: the HTTP response an error carries, without the query
string, and a stack trace only when the cause is unknown."""

import requests

from onyx.connectors.capability_checks.models import (
    MAX_RESPONSE_EXCERPT_CHARS,
    CheckErrorDetail,
    CheckErrorKind,
    check_error_detail,
    check_error_kind,
    credential_strings,
)
from onyx.connectors.exceptions import (
    InsufficientPermissionsError,
    SourceApiError,
    UnexpectedValidationError,
)


def _http_error(status: int, url: str, body: str) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    response.url = url
    response._content = body.encode()
    response.request = requests.Request("GET", url).prepare()
    return requests.HTTPError(f"HTTP {status}", response=response)


def _detail(error: Exception) -> CheckErrorDetail | None:
    try:
        raise error
    except Exception as raised:
        return check_error_detail(raised, check_error_kind(raised), [])


def test_a_mapped_http_error_keeps_the_response_but_not_the_query() -> None:
    http_error = _http_error(
        403, "https://acme.atlassian.net/wiki/rest/api/space?token=secret", "Denied."
    )
    try:
        raise InsufficientPermissionsError("No permission.") from http_error
    except InsufficientPermissionsError as error:
        detail = check_error_detail(error, CheckErrorKind.PERMISSION, [])

    assert detail == CheckErrorDetail(
        status_code=403,
        request="GET acme.atlassian.net/wiki/rest/api/space",
        response_excerpt="Denied.",
    )


def test_a_source_api_error_gives_its_response() -> None:
    api_error = SourceApiError(
        "HTTP 404",
        status_code=404,
        method="GET",
        url="https://jira.acme.com/rest/api/2/project/ENG",
        body="x" * (MAX_RESPONSE_EXCERPT_CHARS * 2),
    )
    try:
        raise UnexpectedValidationError("Unexpected Jira response.") from api_error
    except UnexpectedValidationError as error:
        detail = check_error_detail(error, CheckErrorKind.INVALID, [])

    assert detail is not None
    assert detail.status_code == 404
    assert detail.request == "GET jira.acme.com/rest/api/2/project/ENG"
    assert detail.response_excerpt == "x" * MAX_RESPONSE_EXCERPT_CHARS
    assert detail.stack_trace is None


def test_an_error_raised_while_handling_one_keeps_its_response() -> None:
    http_error = _http_error(401, "https://jira.acme.com/rest/api/2/myself", "No.")
    try:
        try:
            raise http_error
        except requests.HTTPError:
            raise InsufficientPermissionsError("Jira rejected the token.")
    except InsufficientPermissionsError as error:
        detail = check_error_detail(error, CheckErrorKind.PERMISSION, [])

    assert detail == CheckErrorDetail(
        status_code=401,
        request="GET jira.acme.com/rest/api/2/myself",
        response_excerpt="No.",
    )


def test_a_suppressed_context_gives_no_response() -> None:
    try:
        try:
            raise _http_error(401, "https://jira.acme.com/rest/api/2/myself", "No.")
        except requests.HTTPError:
            raise InsufficientPermissionsError("Jira rejected the token.") from None
    except InsufficientPermissionsError as error:
        detail = check_error_detail(error, CheckErrorKind.PERMISSION, [])

    assert detail is None


def test_an_error_chain_with_a_cycle_ends() -> None:
    first = InsufficientPermissionsError("First.")
    second = InsufficientPermissionsError("Second.")
    first.__context__ = second
    second.__context__ = first

    assert check_error_detail(first, CheckErrorKind.PERMISSION, []) is None


def test_an_unknown_cause_keeps_a_stack_trace() -> None:
    detail = _detail(RuntimeError("Boom."))

    assert detail is not None
    assert detail.status_code is None
    assert detail.stack_trace is not None
    assert "RuntimeError: Boom." in detail.stack_trace


def test_a_known_cause_without_a_response_has_no_detail() -> None:
    assert _detail(InsufficientPermissionsError("No scope.")) is None


def test_credential_values_and_url_queries_are_redacted() -> None:
    secrets = credential_strings(
        {"token": "sk-secret-value", "nested": {"refresh": "rt-secret-value"}}
    )
    http_error = _http_error(
        500,
        "https://api.example.com/v1/items?key=sk-secret-value",
        "Bad token sk-secret-value and rt-secret-value.",
    )
    try:
        raise RuntimeError(
            "Failed: https://api.example.com/v1/items?key=sk-secret-value"
        ) from http_error
    except RuntimeError as error:
        detail = check_error_detail(error, CheckErrorKind.UNEXPECTED, secrets)

    assert detail is not None
    assert detail.response_excerpt == "Bad token [REDACTED] and [REDACTED]."
    assert detail.stack_trace is not None
    assert "sk-secret-value" not in detail.stack_trace
    assert "rt-secret-value" not in detail.stack_trace
    assert "?key=" not in detail.stack_trace


def test_urls_keep_only_host_and_path_whatever_their_form() -> None:
    try:
        raise RuntimeError(
            "Tried HTTPS://user:pw@api.example.com:8443/v1/items;p=1?k=v#f "
            "and ftp://admin:pw@files.example.com/x and http://bad:port/y"
        )
    except RuntimeError as error:
        detail = check_error_detail(error, CheckErrorKind.UNEXPECTED, [])

    assert detail is not None and detail.stack_trace is not None
    assert "api.example.com:8443/v1/items " in detail.stack_trace
    assert "files.example.com/x" in detail.stack_trace
    for leaked in ("user:pw", "admin:pw", "p=1", "k=v", "#f", "bad:port"):
        assert leaked not in detail.stack_trace


def test_a_secret_at_the_excerpt_cut_is_still_redacted() -> None:
    secret = "sk-secret-value-that-is-long"
    body = "x" * (MAX_RESPONSE_EXCERPT_CHARS - 5) + secret
    try:
        raise UnexpectedValidationError("Bad.") from SourceApiError(
            "HTTP 500", status_code=500, body=body
        )
    except UnexpectedValidationError as error:
        detail = check_error_detail(error, CheckErrorKind.INVALID, [secret])

    assert detail is not None and detail.response_excerpt is not None
    assert detail.response_excerpt.endswith("[REDA")
    assert "sk-se" not in detail.response_excerpt


def test_a_url_that_does_not_parse_is_replaced() -> None:
    detail = _detail(RuntimeError("Tried http://[::1/path?token=t and more"))

    assert detail is not None and detail.stack_trace is not None
    assert "[URL]" in detail.stack_trace
    assert "token=t" not in detail.stack_trace
