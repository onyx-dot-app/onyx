from collections.abc import Iterable
from typing import TYPE_CHECKING

from pydantic import BaseModel

from onyx.configs.app_configs import LITELLM_CUSTOM_ERROR_MESSAGE_MAPPINGS
from onyx.llm.model_capabilities import get_max_input_tokens
from onyx.utils.logger import setup_logger
from onyx.utils.redaction import scrub_sensitive_values

if TYPE_CHECKING:
    from onyx.llm.interfaces import LLM

logger = setup_logger()


class LLMErrorInfo(BaseModel):
    message: str
    error_code: str
    is_retryable: bool


class ClassifiedLLMError(RuntimeError):
    def __init__(
        self,
        *,
        client_error_msg: str,
        error_code: str,
        is_retryable: bool,
    ) -> None:
        super().__init__(client_error_msg)
        self.client_error_msg = client_error_msg
        self.error_code = error_code
        self.is_retryable = is_retryable


class LLMTimeoutError(TimeoutError):
    """A model generation exceeded a transport or total request timeout."""


class LLMRateLimitError(Exception):
    """The provider rejected a request because its rate limit was reached."""


class LLMContextLimitError(Exception):
    """The generation input exceeds the selected model context limit."""


def _unwrap_nested_exception(error: Exception) -> Exception:
    """
    Traverse common exception wrappers to surface the underlying LiteLLM error.
    """
    visited: set[int] = set()
    current = error
    for _ in range(100):
        visited.add(id(current))
        candidate: Exception | None = None
        cause = getattr(current, "__cause__", None)  # ods: ignore[getattr]
        if isinstance(cause, Exception):
            candidate = cause
        elif (
            hasattr(current, "args")
            and len(current.args) == 1
            and isinstance(current.args[0], Exception)
        ):
            candidate = current.args[0]
        if candidate is None or id(candidate) in visited:
            break
        current = candidate
    return current


def litellm_exception_to_error_msg(  # noqa: C901 - Provider errors have distinct failure policies.
    e: Exception,
    llm: "LLM | None",
    fallback_to_error_msg: bool = False,
    custom_error_msg_mappings: (
        dict[str, str] | None
    ) = LITELLM_CUSTOM_ERROR_MESSAGE_MAPPINGS,
) -> tuple[str, str, bool]:
    """Convert a LiteLLM exception to a user-friendly error message with classification.

    Returns:
        tuple: (error_message, error_code, is_retryable)
            - error_message: User-friendly error description
            - error_code: Categorized error code for frontend display
            - is_retryable: Whether the user should try again
    """
    from litellm.exceptions import (
        APIConnectionError,
        APIError,
        AuthenticationError,
        BadRequestError,
        BudgetExceededError,
        ContentPolicyViolationError,
        ContextWindowExceededError,
        NotFoundError,
        PermissionDeniedError,
        RateLimitError,
        ServiceUnavailableError,
        Timeout,
        UnprocessableEntityError,
    )

    core_exception = _unwrap_nested_exception(e)
    error_msg = str(core_exception)
    error_code = "UNKNOWN_ERROR"
    is_retryable = True

    # This is raised by us in cases where we already have computed the stuff we
    # normally pull out of litellm errors. Just send it through.
    if isinstance(core_exception, ClassifiedLLMError):
        return (
            core_exception.client_error_msg,
            core_exception.error_code,
            core_exception.is_retryable,
        )

    if custom_error_msg_mappings:
        for error_msg_pattern, custom_error_msg in custom_error_msg_mappings.items():
            if error_msg_pattern in error_msg:
                return custom_error_msg, "CUSTOM_ERROR", True

    # Both subclass BadRequestError, so they must precede the BadRequestError
    # branch or they'd be misclassified as BAD_REQUEST.
    if isinstance(core_exception, (ContextWindowExceededError, LLMContextLimitError)):
        error_msg = (
            "Context window exceeded: Your input is too long for the model to process."
        )
        if llm is not None:
            try:
                max_context = get_max_input_tokens(
                    model_name=llm.info.model_name,
                    model_provider=llm.info.model_provider,
                )
                error_msg += f" Your invoked model ({llm.info.model_name}) has a maximum context size of {max_context}."
            except Exception:
                logger.warning(
                    "Unable to get maximum input token for LiteLLM exception handling"
                )
        error_code = "CONTEXT_TOO_LONG"
        is_retryable = False
    elif isinstance(core_exception, ContentPolicyViolationError):
        error_msg = "Content policy violation: Your request violates the content policy. Please revise your input."
        error_code = "CONTENT_POLICY"
        is_retryable = False
    elif isinstance(core_exception, BadRequestError):
        error_msg = f"Bad request: {str(core_exception)}"
        error_code = "BAD_REQUEST"
        is_retryable = True
    elif isinstance(core_exception, AuthenticationError):
        error_msg = "Authentication failed: Please check your API key and credentials."
        error_code = "AUTH_ERROR"
        is_retryable = False
    elif isinstance(core_exception, PermissionDeniedError):
        error_msg = (
            f"Permission denied: {str(core_exception)}"
            "Ensure you have access to this model."
        )
        error_code = "PERMISSION_DENIED"
        is_retryable = False
    elif isinstance(core_exception, NotFoundError):
        error_msg = f"Resource not found: {str(core_exception)}"
        error_code = "NOT_FOUND"
        is_retryable = False
    elif isinstance(core_exception, UnprocessableEntityError):
        error_msg = "Unprocessable entity: The server couldn't process your request due to semantic errors."
        error_code = "UNPROCESSABLE_ENTITY"
        is_retryable = True
    elif isinstance(core_exception, RateLimitError):
        provider_name = (
            llm.info.model_provider
            if llm is not None and llm.info.model_provider
            else "The LLM provider"
        )
        upstream_detail: str | None = None
        message_attr = getattr(core_exception, "message", None)  # ods: ignore[getattr]
        if message_attr:
            upstream_detail = str(message_attr)
        elif hasattr(core_exception, "api_error"):
            api_error = core_exception.api_error
            if isinstance(api_error, dict):
                detail_value = (
                    api_error.get("message")
                    or api_error.get("detail")
                    or api_error.get("error")
                )
                if detail_value:
                    upstream_detail = str(detail_value)
        if not upstream_detail:
            upstream_detail = str(core_exception)
        upstream_detail = str(upstream_detail).strip()
        if ":" in upstream_detail and upstream_detail.lower().startswith(
            "ratelimiterror"
        ):
            upstream_detail = upstream_detail.split(":", 1)[1].strip()
        upstream_detail_lower = upstream_detail.lower()
        if (
            "insufficient_quota" in upstream_detail_lower
            or "exceeded your current quota" in upstream_detail_lower
        ):
            error_msg = (
                f"{provider_name} quota exceeded: {upstream_detail}"
                if upstream_detail
                else f"{provider_name} quota exceeded: Verify billing and quota for this API key."
            )
            error_code = "BUDGET_EXCEEDED"
            is_retryable = False
        else:
            error_msg = (
                f"{provider_name} rate limit: {upstream_detail}"
                if upstream_detail
                else f"{provider_name} rate limit exceeded: Please slow down your requests and try again later."
            )
            error_code = "RATE_LIMIT"
            is_retryable = True
    elif isinstance(core_exception, ServiceUnavailableError):
        provider_name = (
            llm.info.model_provider
            if llm is not None and llm.info.model_provider
            else "The LLM provider"
        )
        # Check if this is specifically the Bedrock "Too many connections" error
        if "Too many connections" in error_msg or "BedrockException" in error_msg:
            error_msg = (
                f"{provider_name} is experiencing high connection volume and cannot process your request right now. "
                "This typically happens when there are too many simultaneous requests to the AI model. "
                "Please wait a moment and try again. If this persists, contact your system administrator "
                "to review connection limits and retry configurations."
            )
        else:
            # Generic 503 Service Unavailable
            error_msg = f"{provider_name} service error: {str(core_exception)}"
        error_code = "SERVICE_UNAVAILABLE"
        is_retryable = True
    elif isinstance(core_exception, APIConnectionError):
        error_msg = "API connection error: Failed to connect to the API. Please check your internet connection."
        error_code = "CONNECTION_ERROR"
        is_retryable = True
    elif isinstance(core_exception, BudgetExceededError):
        error_msg = (
            "Budget exceeded: You've exceeded your allocated budget for API usage."
        )
        error_code = "BUDGET_EXCEEDED"
        is_retryable = False
    elif isinstance(core_exception, Timeout):
        error_msg = "Request timed out: The operation took too long to complete. Please try again."
        error_code = "CONNECTION_ERROR"
        is_retryable = True
    elif str(
        getattr(core_exception, "status_code", "")  # ods: ignore[getattr]
    ) == "413" or (
        "413" in error_msg and "request entity too large" in error_msg.lower()
    ):
        # Upstream proxy/gateway (e.g. nginx) rejected the request body as too large.
        error_msg = (
            "Request too large: The LLM endpoint rejected the request because it "
            "exceeded the maximum allowed size (HTTP 413). This commonly happens "
            "when sending images to a model behind a proxy/gateway. Increase the "
            "maximum request body size on the gateway in front of your LLM "
            "endpoint (e.g. nginx `client_max_body_size`)."
        )
        error_code = "REQUEST_TOO_LARGE"
        is_retryable = False
    elif isinstance(core_exception, APIError):
        error_msg = f"API error: An error occurred while communicating with the API. Details: {str(core_exception)}"
        error_code = "API_ERROR"
        is_retryable = True
    elif not fallback_to_error_msg:
        error_msg = "An unexpected error occurred while processing your request. Please try again later."
        error_code = "UNKNOWN_ERROR"
        is_retryable = True

    return error_msg, error_code, is_retryable


def litellm_exception_to_safe_error(
    e: Exception,
    llm: "LLM | None" = None,
    *,
    fallback_to_error_msg: bool = False,
    custom_error_msg_mappings: (
        dict[str, str] | None
    ) = LITELLM_CUSTOM_ERROR_MESSAGE_MAPPINGS,
    secrets: Iterable[str | None] = (),
) -> LLMErrorInfo:
    """Classify a LiteLLM exception and redact secrets from its message."""
    message, error_code, is_retryable = litellm_exception_to_error_msg(
        e,
        llm,
        fallback_to_error_msg=fallback_to_error_msg,
        custom_error_msg_mappings=custom_error_msg_mappings,
    )
    safe_message = scrub_sensitive_values(message, secrets)
    if llm is not None:
        safe_message = llm.redact_error(safe_message)
    return LLMErrorInfo(
        message=safe_message,
        error_code=error_code,
        is_retryable=is_retryable,
    )
