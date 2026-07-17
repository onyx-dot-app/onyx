"""Guards classification order in litellm_exception_to_error_msg:
ContextWindowExceededError and ContentPolicyViolationError subclass
BadRequestError and must be matched first, or context overflow is mislabeled
BAD_REQUEST instead of CONTEXT_TOO_LONG.
"""

from litellm.exceptions import APIError
from litellm.exceptions import BadRequestError
from litellm.exceptions import ContentPolicyViolationError
from litellm.exceptions import ContextWindowExceededError

from onyx.llm.utils import litellm_exception_to_error_msg


def _err(exc_cls: type[BadRequestError]) -> BadRequestError:
    return exc_cls("boom", model="m", llm_provider="p")


_NGINX_413_HTML = (
    "<html>\n<head><title>413 Request Entity Too Large</title></head>\n"
    "<body>\n<center><h1>413 Request Entity Too Large</h1></center>\n"
    "<hr><center>nginx</center>\n</body>\n</html>"
)


def test_context_window_exceeded_classified_before_bad_request() -> None:
    _, code, is_retryable = litellm_exception_to_error_msg(
        _err(ContextWindowExceededError), None
    )
    assert code == "CONTEXT_TOO_LONG"
    assert is_retryable is False


def test_content_policy_classified_before_bad_request() -> None:
    _, code, _ = litellm_exception_to_error_msg(_err(ContentPolicyViolationError), None)
    assert code == "CONTENT_POLICY"


def test_plain_bad_request_still_bad_request() -> None:
    _, code, _ = litellm_exception_to_error_msg(_err(BadRequestError), None)
    assert code == "BAD_REQUEST"


def test_413_status_code_classified_as_request_too_large() -> None:
    """A gateway 413 (e.g. nginx rejecting a large image payload) maps to an
    actionable message instead of dumping the raw HTML."""
    exc = APIError(
        status_code=413,
        message=_NGINX_413_HTML,
        llm_provider="bifrost",
        model="vertex/gemini-3-pro-image-preview",
    )
    msg, code, is_retryable = litellm_exception_to_error_msg(exc, None)
    assert code == "REQUEST_TOO_LARGE"
    assert is_retryable is False
    assert "413" in msg
    assert "client_max_body_size" in msg
    # Raw nginx HTML should not be surfaced to the user.
    assert "<html>" not in msg


def test_413_in_message_classified_when_status_code_absent() -> None:
    """Some upstreams surface the 413 only in the body; match on text too."""
    exc = APIError(
        status_code=500,  # upstream mislabels; body is the source of truth
        message=_NGINX_413_HTML,
        llm_provider="bifrost",
        model="m",
    )
    # status_code 500 won't match the numeric branch, but the body text will.
    _, code, _ = litellm_exception_to_error_msg(exc, None)
    assert code == "REQUEST_TOO_LARGE"
