import json

import httplib2  # type: ignore[import-untyped]
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

from onyx.connectors.google_utils.google_utils import _is_rate_limit_error


def _make_http_error(
    status: int,
    reason: str = "unknown",
    error_reason: str = "",
) -> HttpError:
    resp = httplib2.Response({"status": status})
    if error_reason:
        body = json.dumps(
            {
                "error": {
                    "message": reason,
                    "errors": [{"reason": error_reason, "message": reason}],
                }
            }
        ).encode()
    else:
        body = json.dumps({"error": {"message": reason}}).encode()
    return HttpError(resp, body)


def test_429_is_rate_limit() -> None:
    assert _is_rate_limit_error(_make_http_error(429))


def test_403_user_rate_limit_exceeded() -> None:
    err = _make_http_error(
        403,
        reason="User rate limit exceeded.",
        error_reason="userRateLimitExceeded",
    )
    assert _is_rate_limit_error(err)


def test_403_rate_limit_exceeded() -> None:
    err = _make_http_error(
        403,
        reason="Rate limit exceeded.",
        error_reason="rateLimitExceeded",
    )
    assert _is_rate_limit_error(err)


def test_403_permission_denied_is_not_rate_limit() -> None:
    err = _make_http_error(
        403,
        reason="The caller does not have permission",
        error_reason="forbidden",
    )
    assert not _is_rate_limit_error(err)


def test_404_is_not_rate_limit() -> None:
    assert not _is_rate_limit_error(_make_http_error(404))


def test_500_is_not_rate_limit() -> None:
    assert not _is_rate_limit_error(_make_http_error(500))
