import traceback

from onyx.agents.models import RunFailure
from onyx.agents.runtime import RunFailed
from onyx.configs.app_configs import DEV_MODE
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.constants import LlmProviderNames
from onyx.llm.exceptions import ClassifiedLLMError, litellm_exception_to_safe_error
from onyx.llm.interfaces import LLM
from onyx.llm.model_capabilities import is_true_openai_model
from onyx.llm.models import AssistantMessage, ToolChoiceOptions
from onyx.server.query_and_chat.streaming_models import StreamingError


class EmptyLLMResponseError(ClassifiedLLMError):
    """Raised when the streamed LLM response completes without a usable answer."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        tool_choice: ToolChoiceOptions,
        client_error_msg: str,
        error_code: str = "EMPTY_LLM_RESPONSE",
        is_retryable: bool = True,
        finish_reason: str | None = None,
    ) -> None:
        super().__init__(
            client_error_msg=client_error_msg,
            error_code=error_code,
            is_retryable=is_retryable,
            tool_choice=tool_choice,
            finish_reason=finish_reason,
        )
        self.provider = provider
        self.model = model


# LiteLLM maps these native policy blocks to content_filter, but gateways may
# forward the provider value unchanged.
_REFUSAL_FINISH_REASONS = {
    "BLOCKLIST",
    "CONTENT_BLOCKED",
    "ERROR_TOXIC",
    "IMAGE_OTHER",
    "IMAGE_PROHIBITED_CONTENT",
    "IMAGE_RECITATION",
    "IMAGE_SAFETY",
    "LANGUAGE",
    "MODEL_ARMOR",
    "OTHER",
    "PROHIBITED_CONTENT",
    "RECITATION",
    "SAFETY",
    "SPII",
    "content_filter",
    "content_filtered",
    "guardrail_intervened",
    "refusal",
    "sensitive",
}


def build_empty_llm_response_error(
    llm: LLM,
    message: AssistantMessage,
    tool_choice: ToolChoiceOptions,
) -> EmptyLLMResponseError:
    provider = llm.config.model_provider
    model = llm.config.model_name
    finish_reason = message.stop_reason

    # A refusal/content-filter stop is a deliberate model decision (HTTP 200
    # with no content), not a transport failure — retrying the same request
    # against the same model will not help.
    if finish_reason in _REFUSAL_FINISH_REASONS:
        model_suggestion = (
            " (e.g. Claude Opus 4.8)" if provider == LlmProviderNames.ANTHROPIC else ""
        )
        return EmptyLLMResponseError(
            provider=provider,
            model=model,
            tool_choice=tool_choice,
            client_error_msg=(
                "The selected model declined to respond to this request and "
                f"returned no content (finish_reason={finish_reason}). Try "
                "rephrasing the request or switching to a different model"
                f"{model_suggestion}."
            ),
            error_code="MODEL_REFUSAL",
            is_retryable=False,
            finish_reason=finish_reason,
        )

    # OpenAI quota exhaustion has reached us as a streamed "stop" with zero content.
    # When the stream is completely empty and there is no reasoning/tool output, surface
    # the likely account-level cause instead of a generic tool-calling error.
    if (
        not message.thinking
        and provider == LlmProviderNames.OPENAI
        and is_true_openai_model(provider, model)
    ):
        return EmptyLLMResponseError(
            provider=provider,
            model=model,
            tool_choice=tool_choice,
            client_error_msg=(
                "The selected OpenAI model returned an empty streamed response "
                "before producing any tokens. This commonly happens when the API "
                "key or project has no remaining quota or billing is not enabled. "
                "Verify quota and billing for this key and try again."
            ),
            error_code="BUDGET_EXCEEDED",
            is_retryable=False,
            finish_reason=finish_reason,
        )

    return EmptyLLMResponseError(
        provider=provider,
        model=model,
        tool_choice=tool_choice,
        client_error_msg=(
            "The selected model returned no final answer before the stream "
            "completed. No text or tool calls were received from the upstream "
            "provider."
        ),
        finish_reason=finish_reason,
    )


def chat_error(
    error: Exception | RunFailure,
    llm: LLM | None = None,
    model_index: int | None = None,
) -> StreamingError:
    """Project stored failures or classify exceptions for the public chat error payload."""
    details: dict[str, str | int | None] = {}
    if llm is not None:
        details.update(model=llm.config.model_name, provider=llm.config.model_provider)
    if model_index is not None:
        details["model_index"] = model_index
    stack = None
    if isinstance(error, RunFailed):
        error = error.failure
    if isinstance(error, RunFailure):
        info = error.llm_error
        if info is None:
            return StreamingError(
                error=error.message,
                error_code="AGENT_EXECUTION_FAILED",
                is_retryable=False,
                details=details,
            )
    elif isinstance(error, OnyxError):
        return StreamingError(
            error=error.detail,
            error_code=error.error_code.code,
            is_retryable=error.status_code >= 500,
            details=details,
        )
    elif isinstance(error, ValueError) and llm is None:
        return StreamingError(
            error=str(error),
            error_code="VALIDATION_ERROR",
            is_retryable=True,
            details=details,
        )
    elif llm is None:
        return StreamingError(
            error="Failed to initialize the chat. Please check your configuration and try again.",
            stack_trace="".join(traceback.format_exception(error))
            if DEV_MODE
            else None,
            error_code="INIT_FAILED",
            is_retryable=True,
            details=details,
        )
    else:
        info = litellm_exception_to_safe_error(error, llm, fallback_to_error_msg=False)
        if DEV_MODE:
            stack = llm.redact_error("".join(traceback.format_exception(error)))
    if info.tool_choice is not None:
        details.update(
            tool_choice=info.tool_choice.value, finish_reason=info.finish_reason
        )
    elif info.finish_reason is not None:
        details["finish_reason"] = info.finish_reason
    return StreamingError(
        error=info.message,
        stack_trace=stack,
        error_code=info.error_code,
        is_retryable=info.is_retryable,
        details=details,
    )
