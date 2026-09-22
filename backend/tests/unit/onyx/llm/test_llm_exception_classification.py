"""Guards classification order in llm_exception_to_error_msg:
ContextWindowExceededError and ContentPolicyViolationError subclass
BadRequestError and must be matched first, or context overflow is mislabeled
BAD_REQUEST instead of CONTEXT_TOO_LONG.
"""

from pydantic_ai.exceptions import ModelHTTPError

from onyx.llm.utils import llm_exception_to_error_msg


def _err(message: str) -> ModelHTTPError:
    return ModelHTTPError(400, "test", message)


_NGINX_413_HTML = (
    "<html>\n<head><title>413 Request Entity Too Large</title></head>\n"
    "<body>\n<center><h1>413 Request Entity Too Large</h1></center>\n"
    "<hr><center>nginx</center>\n</body>\n</html>"
)


def test_context_window_exceeded_classified_before_bad_request() -> None:
    _, code, is_retryable = llm_exception_to_error_msg(
        _err("context_length_exceeded"), None
    )
    assert code == "CONTEXT_TOO_LONG"
    assert is_retryable is False


def test_content_policy_classified_before_bad_request() -> None:
    _, code, _ = llm_exception_to_error_msg(_err("content_policy_violation"), None)
    assert code == "CONTENT_POLICY"


def test_plain_bad_request_still_bad_request() -> None:
    _, code, _ = llm_exception_to_error_msg(_err("bad request"), None)
    assert code == "BAD_REQUEST"


def test_413_status_code_classified_as_request_too_large() -> None:
    """A gateway 413 (e.g. nginx rejecting a large image payload) maps to an
    actionable message instead of dumping the raw HTML."""
    exc = ModelHTTPError(413, "test", _NGINX_413_HTML)
    msg, code, is_retryable = llm_exception_to_error_msg(exc, None)
    assert code == "REQUEST_TOO_LARGE"
    assert is_retryable is False
    assert "413" in msg
    assert "client_max_body_size" in msg
    # Raw nginx HTML should not be surfaced to the user.
    assert "<html>" not in msg


def test_413_in_message_classified_when_status_code_absent() -> None:
    """Some upstreams surface the 413 only in the body; match on text too."""
    exc = ModelHTTPError(500, "test", _NGINX_413_HTML)
    # status_code 500 won't match the numeric branch, but the body text will.
    _, code, _ = llm_exception_to_error_msg(exc, None)
    assert code == "REQUEST_TOO_LARGE"
