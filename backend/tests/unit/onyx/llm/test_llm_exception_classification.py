"""Guards classification order in litellm_exception_to_error_msg:
ContextWindowExceededError and ContentPolicyViolationError subclass
BadRequestError and must be matched first, or context overflow is mislabeled
BAD_REQUEST instead of CONTEXT_TOO_LONG.
"""

from litellm.exceptions import (
    APIError,
    BadRequestError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
)

from onyx.llm.exceptions import (
    ClassifiedLLMError,
    litellm_exception_to_error_msg,
    litellm_exception_to_safe_error,
)
from onyx.llm.models import ToolChoiceOptions


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


def test_generic_api_error_keeps_provider_payload_out_of_public_message() -> None:
    payload = '{"provider_error": "' + "sensitive upstream detail " * 300 + '"}'
    error = APIError(
        status_code=500, message=payload, llm_provider="openrouter", model="test"
    )
    message, code, retryable = litellm_exception_to_error_msg(error, None)
    assert (
        message
        == "The model provider could not complete this request. Please try again."
    )
    assert code == "API_ERROR"
    assert retryable is True
    assert payload in str(error)


def test_explicit_classification_keeps_safe_diagnostics_and_hides_its_cause() -> None:
    error = ClassifiedLLMError(
        client_error_msg="Empty response private-secret",
        error_code="EMPTY_LLM_RESPONSE",
        is_retryable=False,
        tool_choice=ToolChoiceOptions.REQUIRED,
        finish_reason="length private-secret",
    )
    error.__cause__ = RuntimeError("raw-provider-detail")
    info = litellm_exception_to_safe_error(error, secrets=iter(["private-secret"]))
    assert info.error_code == "EMPTY_LLM_RESPONSE"
    assert not info.is_retryable
    assert info.tool_choice == ToolChoiceOptions.REQUIRED
    assert info.finish_reason is not None and info.finish_reason.startswith("length")
    assert "private-secret" not in info.model_dump_json()
    assert "raw-provider-detail" not in info.model_dump_json()
