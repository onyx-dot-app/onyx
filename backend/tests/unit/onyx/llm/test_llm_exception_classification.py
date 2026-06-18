"""Guards classification order in litellm_exception_to_error_msg:
ContextWindowExceededError and ContentPolicyViolationError subclass
BadRequestError and must be matched first, or context overflow is mislabeled
BAD_REQUEST instead of CONTEXT_TOO_LONG.
"""

from litellm.exceptions import BadRequestError
from litellm.exceptions import ContentPolicyViolationError
from litellm.exceptions import ContextWindowExceededError

from onyx.llm.utils import litellm_exception_to_error_msg


def _err(exc_cls: type[BadRequestError]) -> BadRequestError:
    return exc_cls("boom", model="m", llm_provider="p")


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
