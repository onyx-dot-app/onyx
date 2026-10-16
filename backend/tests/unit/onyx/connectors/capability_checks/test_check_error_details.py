"""Error details: the HTTP response an error carries, without the query
string, and a stack trace only when the cause is unknown."""

import requests

from onyx.connectors.capability_checks.models import (
    MAX_RESPONSE_EXCERPT_CHARS,
    CheckErrorDetail,
    CheckErrorKind,
    check_error_detail,
    check_error_kind,
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
        return check_error_detail(raised, check_error_kind(raised))


def test_a_mapped_http_error_keeps_the_response_but_not_the_query() -> None:
    http_error = _http_error(
        403, "https://acme.atlassian.net/wiki/rest/api/space?token=secret", "Denied."
    )
    try:
        raise InsufficientPermissionsError("No permission.") from http_error
    except InsufficientPermissionsError as error:
        detail = check_error_detail(error, CheckErrorKind.PERMISSION)

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
        detail = check_error_detail(error, CheckErrorKind.INVALID)

    assert detail is not None
    assert detail.status_code == 404
    assert detail.request == "GET jira.acme.com/rest/api/2/project/ENG"
    assert detail.response_excerpt == "x" * MAX_RESPONSE_EXCERPT_CHARS
    assert detail.stack_trace is None


def test_an_unknown_cause_keeps_a_stack_trace() -> None:
    detail = _detail(RuntimeError("Boom."))

    assert detail is not None
    assert detail.status_code is None
    assert detail.stack_trace is not None
    assert "RuntimeError: Boom." in detail.stack_trace


def test_a_known_cause_without_a_response_has_no_detail() -> None:
    assert _detail(InsufficientPermissionsError("No scope.")) is None
