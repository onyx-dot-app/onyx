"""Guards classification order in litellm_exception_to_error_msg:
ContextWindowExceededError and ContentPolicyViolationError subclass
BadRequestError and must be matched first, or context overflow is mislabeled
BAD_REQUEST instead of CONTEXT_TOO_LONG.
"""

import json

import pytest
from litellm.exceptions import (
    APIError,
    BadRequestError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    RateLimitError,
)

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


def _anthropic_error(message: str) -> BadRequestError:
    """LiteLLM passes the raw response bytes as the message, so the body is a bytes repr."""
    body: bytes = json.dumps(
        {
            "type": "error",
            "error": {"type": "invalid_request_error", "message": message},
        }
    ).encode()
    return BadRequestError(
        message=f"AnthropicException - {body!r}",
        model="claude",
        llm_provider="anthropic",
    )


_CREDIT_MESSAGE = (
    "Your credit balance is too low to access the Anthropic API. "
    "Please go to Plans & Billing to upgrade or purchase credits."
)


def test_anthropic_credit_error_is_a_billing_error() -> None:
    """Anthropic reports an empty balance as a 400. The user must see a billing
    error that they cannot retry, not a bad request."""
    msg, code, is_retryable = litellm_exception_to_error_msg(
        _anthropic_error(_CREDIT_MESSAGE), None
    )
    assert code == "BUDGET_EXCEEDED"
    assert is_retryable is False
    assert msg == f"The LLM provider quota exceeded: {_CREDIT_MESSAGE}"


def test_bad_request_shows_the_provider_message() -> None:
    msg, code, _ = litellm_exception_to_error_msg(
        _anthropic_error("max_tokens: must be at least 1"), None
    )
    assert code == "BAD_REQUEST"
    assert msg == "Bad request: max_tokens: must be at least 1"


def test_provider_message_with_quotes_and_non_ascii_is_not_cut_short() -> None:
    """A bytes repr escapes both, so the body needs decoding before it is read."""
    message = "Invalid tool name \"my tool\". It isn’t an 'object'."
    msg, _, _ = litellm_exception_to_error_msg(_anthropic_error(message), None)
    assert msg == f"Bad request: {message}"


def test_bad_request_keeps_the_raw_text_when_the_body_is_cut_off() -> None:
    exc = BadRequestError(
        message='AnthropicException - b\'{"error":{"message":"cut of',
        model="claude",
        llm_provider="anthropic",
    )
    msg, code, _ = litellm_exception_to_error_msg(exc, None)
    assert code == "BAD_REQUEST"
    assert "AnthropicException" in msg


def test_user_input_echoed_in_the_body_is_never_shown_as_the_error() -> None:
    exc = BadRequestError(
        message='X - {"detail":[{"msg":"Field required","input":{"message":"what is our PTO policy?"}}]}',
        model="m",
        llm_provider="p",
    )
    msg, _, _ = litellm_exception_to_error_msg(exc, None)
    assert msg != "Bad request: what is our PTO policy?"
    assert "Field required" in msg


@pytest.mark.parametrize(
    "body",
    [
        "{not json at all}",
        "b'{}', b'{}'",
        "b'{\"error\": \\xff}'",
        "[" * 9000 + "{" + "]" * 9000 + "}",
        "{" * 256_000,
    ],
    ids=["malformed", "two-literals", "bad-utf8", "deep-nesting", "huge"],
)
def test_hostile_provider_body_never_breaks_error_handling(body: str) -> None:
    """This runs inside the shared error path. If it raised, the web chat and the
    API would lose the error they were about to report."""
    exc = BadRequestError(message=f"X - {body}", model="m", llm_provider="p")

    msg, code, _ = litellm_exception_to_error_msg(exc, None)

    assert code == "BAD_REQUEST"
    assert msg.startswith("Bad request: ")


_OPENAI_QUOTA = (
    "RateLimitError: OpenAIException - Error code: 429 - {'error': {'message': "
    "'You exceeded your current quota, please check your plan and billing details.', "
    "'type': 'insufficient_quota', 'param': None, 'code': 'insufficient_quota'}}"
)


def test_openai_quota_error_shows_the_provider_message_not_the_raw_exception() -> None:
    """The OpenAI SDK embeds a Python dict repr, not JSON."""
    exc = RateLimitError(message=_OPENAI_QUOTA, model="gpt", llm_provider="openai")
    msg, code, is_retryable = litellm_exception_to_error_msg(exc, None)
    assert code == "BUDGET_EXCEEDED"
    assert is_retryable is False
    assert msg == (
        "The LLM provider quota exceeded: You exceeded your current quota, "
        "please check your plan and billing details."
    )


def test_rate_limit_without_a_readable_body_never_shows_the_raw_exception() -> None:
    """A proxy can put internal detail in the text, and Slack states this code."""
    exc = RateLimitError(
        message="upstream http://10.2.3.4:8080/v1 rejected key sk-live-abc123",
        model="m",
        llm_provider="p",
    )
    msg, code, _ = litellm_exception_to_error_msg(exc, None)
    assert code == "RATE_LIMIT"
    assert "10.2.3.4" not in msg
    assert "sk-live" not in msg
