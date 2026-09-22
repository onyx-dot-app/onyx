import re
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from sqlalchemy import select

from onyx.configs.app_configs import (
    LLM_CUSTOM_ERROR_MESSAGE_MAPPINGS,
    MAX_TOKENS_FOR_FULL_INCLUSION,
    USE_CHUNK_SUMMARY,
    USE_DOCUMENT_SUMMARY,
)
from onyx.configs.model_configs import ENABLE_PROMPT_CACHING
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import LLMModelFlowType
from onyx.db.models import LLMProvider, ModelConfiguration
from onyx.llm.exceptions import ClassifiedLLMError
from onyx.llm.interfaces import LLM, LLMConfig
from onyx.llm.model_capabilities import (
    catalog_supports_image_input,
    get_max_input_tokens,
    model_identity_names,
)
from onyx.llm.model_response import ModelResponse
from onyx.llm.models import LLMErrorInfo, UserMessage
from onyx.prompts.contextual_retrieval import (
    CONTEXTUAL_RAG_TOKEN_ESTIMATE,
    DOCUMENT_SUMMARY_TOKEN_ESTIMATE,
)
from onyx.utils.logger import setup_logger
from onyx.utils.redaction import scrub_sensitive_values
from shared_configs.configs import DOC_EMBEDDING_CONTEXT_SIZE

if TYPE_CHECKING:
    from onyx.server.manage.llm.models import LLMProviderView


logger = setup_logger()

MAX_CONTEXT_TOKENS = 100
ONE_MILLION = 1_000_000
CHUNKS_PER_DOC_ESTIMATE = 5


def supports_explicit_cache(config: LLMConfig) -> bool:
    """Enable user-content cache points on supported Anthropic routes."""
    return ENABLE_PROMPT_CACHING and (
        config.model_provider == "anthropic"
        or (config.model_provider == "bedrock" and "anthropic." in config.model_name)
        or (
            config.model_provider == "openrouter"
            and config.model_name.startswith("anthropic/")
        )
    )


def _unwrap_nested_exception(error: Exception) -> Exception:
    """
    Traverse common exception wrappers to surface the underlying provider error.
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


def llm_exception_to_error_msg(
    e: Exception,
    llm: LLM | None,
    fallback_to_error_msg: bool = False,
    custom_error_msg_mappings: (
        dict[str, str] | None
    ) = LLM_CUSTOM_ERROR_MESSAGE_MAPPINGS,
) -> tuple[str, str, bool]:
    """Convert a provider exception to a user-friendly error message with classification.

    Returns:
        tuple: (error_message, error_code, is_retryable)
            - error_message: User-friendly error description
            - error_code: Categorized error code for frontend display
            - is_retryable: Whether the user should try again
    """
    import anthropic
    import httpx
    import httpx2
    import openai
    from botocore.exceptions import ClientError
    from google.genai.errors import APIError as GoogleAPIError
    from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded

    core_exception = _unwrap_nested_exception(e)
    error_msg = str(core_exception)
    error_code = "UNKNOWN_ERROR"
    is_retryable = True

    # This is raised by us in cases where we already have computed the stuff we
    # normally pull out of provider errors. Just send it through.
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

    status: int | None = None
    if isinstance(
        core_exception,
        (ModelHTTPError, openai.APIStatusError, anthropic.APIStatusError),
    ):
        status = core_exception.status_code
    elif isinstance(core_exception, GoogleAPIError):
        status = core_exception.code
    elif isinstance(core_exception, ClientError):
        status = core_exception.response.get("ResponseMetadata", {}).get(
            "HTTPStatusCode"
        )
        aws_code = core_exception.response.get("Error", {}).get("Code", "")
        if aws_code in {"ThrottlingException", "TooManyRequestsException"}:
            status = 429
        elif aws_code in {"AccessDeniedException", "UnrecognizedClientException"}:
            status = 403
    detail = error_msg.lower()
    if any(
        term in detail
        for term in (
            "context_length_exceeded",
            "context window",
            "maximum context length",
            "prompt is too long",
        )
    ):
        return (
            "Context window exceeded: Your input is too long for the model to process.",
            "CONTEXT_TOO_LONG",
            False,
        )
    if any(
        term in detail
        for term in ("content_policy_violation", "content_filter", "content policy")
    ):
        return (
            "Content policy violation: Please revise your input.",
            "CONTENT_POLICY",
            False,
        )
    if isinstance(core_exception, UsageLimitExceeded) or any(
        term in detail for term in ("insufficient_quota", "exceeded your current quota")
    ):
        return (
            "Budget exceeded: Verify your billing and API quota.",
            "BUDGET_EXCEEDED",
            False,
        )
    if status == 401:
        return (
            "Authentication failed: Please check your API key and credentials.",
            "AUTH_ERROR",
            False,
        )
    if status == 403:
        return (
            "Permission denied: Ensure you have access to this model.",
            "PERMISSION_DENIED",
            False,
        )
    if status == 404:
        return (
            "Resource not found: Check the configured model and endpoint.",
            "NOT_FOUND",
            False,
        )
    if status == 413 or ("413" in detail and "request entity too large" in detail):
        return (
            "Request too large (HTTP 413): The LLM endpoint rejected the request body. Check the gateway request size limit (nginx client_max_body_size).",
            "REQUEST_TOO_LARGE",
            False,
        )
    if status == 429:
        provider_name = llm.config.model_provider if llm is not None else "Provider"
        return f"{provider_name} rate limit: {error_msg}", "RATE_LIMIT", True
    if status == 422:
        return (
            "The provider could not process this request.",
            "UNPROCESSABLE_ENTITY",
            True,
        )
    if status == 400:
        return f"Bad request: {error_msg}", "BAD_REQUEST", True
    if status is not None and status >= 500:
        return f"Provider service error: {error_msg}", "SERVICE_UNAVAILABLE", True
    if isinstance(
        core_exception,
        (
            TimeoutError,
            httpx.TimeoutException,
            httpx.TransportError,
            httpx2.TimeoutException,
            httpx2.TransportError,
            openai.APIConnectionError,
            anthropic.APIConnectionError,
        ),
    ):
        return (
            "Connection failed or timed out. Please try again.",
            "CONNECTION_ERROR",
            True,
        )
    if status is not None:
        return f"Provider API error: {error_msg}", "API_ERROR", True
    if not fallback_to_error_msg:
        error_msg = "An unexpected error occurred while processing your request. Please try again later."

    return error_msg, error_code, is_retryable


def llm_response_to_string(message: ModelResponse) -> str:
    if not isinstance(message.choice.message.content, str):
        raise RuntimeError("LLM message not in expected format.")

    return message.choice.message.content


def check_number_of_tokens(
    text: str, encode_fn: Callable[[str], list] | None = None
) -> int:
    """Gets the number of tokens in the provided text, using the provided encoding
    function. If none is provided, default to the tiktoken encoder used by GPT-3.5
    and GPT-4.
    """
    import tiktoken

    if encode_fn is None:
        encode_fn = tiktoken.get_encoding("cl100k_base").encode

    return len(encode_fn(text))


# Substrings that mark a `custom_config` key as containing credential material.
# Source of truth shared by:
#   - response masking in `onyx.server.manage.llm.api`
#   - error-message scrubbing in `scrub_sensitive_values` (below)
SENSITIVE_CUSTOM_CONFIG_KEY_FRAGMENTS: frozenset[str] = frozenset(
    {
        "vertex_credentials",
        "aws_secret_access_key",
        "aws_access_key_id",
        "aws_bearer_token_bedrock",
        "private_key",
        "api_key",
        "secret",
        "password",
        "token",
        "credential",
    }
)


def is_sensitive_custom_config_key(key: str) -> bool:
    """True when `key` looks like a credential-bearing custom_config field."""
    key_lower = key.lower()
    return any(
        fragment in key_lower for fragment in SENSITIVE_CUSTOM_CONFIG_KEY_FRAGMENTS
    )


def collect_credential_values(
    api_key: str | None, custom_config: dict[str, str] | None
) -> list[str]:
    """Collect credential-bearing values from a provider configuration."""
    credential_values = [api_key] if api_key else []
    for key, value in (custom_config or {}).items():
        if value and is_sensitive_custom_config_key(key):
            credential_values.append(value)
    return credential_values


def llm_exception_to_safe_error(
    e: Exception,
    llm: LLM | None = None,
    *,
    fallback_to_error_msg: bool = False,
    custom_error_msg_mappings: (
        dict[str, str] | None
    ) = LLM_CUSTOM_ERROR_MESSAGE_MAPPINGS,
    secrets: Iterable[str | None] = (),
) -> LLMErrorInfo:
    """Classify a provider exception and redact secrets from its message."""
    message, error_code, is_retryable = llm_exception_to_error_msg(
        e,
        llm,
        fallback_to_error_msg=fallback_to_error_msg,
        custom_error_msg_mappings=custom_error_msg_mappings,
    )
    llm_secrets = (
        collect_credential_values(llm.config.api_key, llm.config.custom_config)
        if llm is not None
        else []
    )
    safe_message = scrub_sensitive_values(message, [*llm_secrets, *secrets])
    return LLMErrorInfo(
        message=safe_message,
        error_code=error_code,
        is_retryable=is_retryable,
    )


def test_llm(llm: LLM) -> str | None:
    """Probe an LLM and return either `None` (success) or a sanitized error.

    The returned message is intended to be safe to surface to admin callers:
    raw upstream exception text is *not* echoed verbatim. Known provider
    exception types are mapped to friendly messages via
    `llm_exception_to_error_msg`, and the result is then scrubbed of any
    credential values pulled from `llm.config` plus common header/JSON
    credential patterns.

    The full raw error is still logged at WARNING for ops debugging.
    """
    error_msg: str | None = None
    # try for up to 2 timeouts (e.g. 10 seconds in total)
    for _ in range(2):
        try:
            llm.invoke(UserMessage(content="Do not respond"), max_tokens=50)
            return None
        except Exception as e:
            logger.warning("Failed to call LLM with the following error: %s", e)
            error_msg = llm_exception_to_safe_error(e, llm).message

    return error_msg


def get_llm_contextual_cost(
    llm: LLM,
) -> float:
    """
    Approximate the cost of using the given LLM for indexing with Contextual RAG.

    We use a precomputed estimate for the number of tokens in the contextualizing prompts,
    and we assume that every chunk is maximized in terms of content and context.
    We also assume that every document is maximized in terms of content, as currently if
    a document is longer than a certain length, its summary is used instead of the full content.

    We expect that the first assumption will overestimate more than the second one
    underestimates, so this should be a fairly conservative price estimate. Also,
    this does not account for the cost of documents that fit within a single chunk
    which do not get contextualized.
    """

    # calculate input costs
    num_tokens = ONE_MILLION
    num_input_chunks = num_tokens // DOC_EMBEDDING_CONTEXT_SIZE

    # We assume that the documents are MAX_TOKENS_FOR_FULL_INCLUSION tokens long
    # on average.
    num_docs = num_tokens // MAX_TOKENS_FOR_FULL_INCLUSION

    num_input_tokens = 0
    num_output_tokens = 0

    if not USE_CHUNK_SUMMARY and not USE_DOCUMENT_SUMMARY:
        return 0

    if USE_CHUNK_SUMMARY:
        # Each per-chunk prompt includes:
        # - The prompt tokens
        # - the document tokens
        # - the chunk tokens

        # for each chunk, we prompt the LLM with the contextual RAG prompt
        # and the full document content (or the doc summary, so this is an overestimate)
        num_input_tokens += num_input_chunks * (
            CONTEXTUAL_RAG_TOKEN_ESTIMATE + MAX_TOKENS_FOR_FULL_INCLUSION
        )

        # in aggregate, each chunk content is used as a prompt input once
        # so the full input size is covered
        num_input_tokens += num_tokens

        # A single MAX_CONTEXT_TOKENS worth of output is generated per chunk
        num_output_tokens += num_input_chunks * MAX_CONTEXT_TOKENS

    # going over each doc once means all the tokens, plus the prompt tokens for
    # the summary prompt. This CAN happen even when USE_DOCUMENT_SUMMARY is false,
    # since doc summaries are used for longer documents when USE_CHUNK_SUMMARY is true.
    # So, we include this unconditionally to overestimate.
    num_input_tokens += num_tokens + num_docs * DOCUMENT_SUMMARY_TOKEN_ESTIMATE
    num_output_tokens += num_docs * MAX_CONTEXT_TOKENS

    try:
        from onyx.llm.cost import compute_cost_cents

        input_cents, output_cents = compute_cost_cents(
            llm.config.model_name,
            llm.config.model_provider,
            num_input_tokens,
            num_output_tokens,
        )
    except Exception:
        logger.exception(
            "An unexpected error occurred while calculating cost for model %s (potentially due to malformed name). Assuming cost is 0.",
            llm.config.model_name,
        )
        return 0

    # compute_cost_cents returns cents; contextual cost UI expects USD.
    return (input_cents + output_cents) / 100.0


def get_max_input_tokens_from_llm_provider(
    llm_provider: "LLMProviderView",
    model_name: str,
) -> int:
    """Get max input tokens for a model, with fallback chain.

    Fallback order:
    1. Use max_input_tokens from model_configuration (populated from source APIs
       like OpenRouter, Ollama, or our Bedrock mapping)
    2. Look up in model catalog
    3. Fall back to GEN_AI_MODEL_FALLBACK_MAX_TOKENS (32000)

    Most dynamic providers (OpenRouter, Ollama) provide context_length via their
    APIs. Bedrock doesn't expose this, so we parse from model ID suffix (:200k)
    or use BEDROCK_MODEL_TOKEN_LIMITS mapping. The 32000 fallback is only hit for
    unknown models not in any of these sources.
    """
    max_input_tokens = None
    for model_configuration in llm_provider.model_configurations:
        if model_configuration.name == model_name:
            max_input_tokens = model_configuration.max_input_tokens
    return max_input_tokens or get_max_input_tokens(
        model_provider=llm_provider.provider,
        model_name=model_name,
    )


def model_supports_image_input(
    model_name: str,
    model_provider: str,
    deployment_name: str | None = None,
) -> bool:
    # First, try to read an explicit configuration from the model_configuration
    # table, keyed by the admin's configured row name (not the deployment alias).
    try:
        with get_session_with_current_tenant() as db_session:
            model_config = db_session.scalar(
                select(ModelConfiguration)
                .join(
                    LLMProvider,
                    ModelConfiguration.llm_provider_id == LLMProvider.id,
                )
                .where(
                    ModelConfiguration.name == model_name,
                    LLMProvider.provider == model_provider,
                )
            )
            if (
                model_config
                and LLMModelFlowType.VISION in model_config.llm_model_flow_types
            ):
                return True
    except Exception as e:
        logger.warning(
            "Failed to query database for %s model %s image support: %s",
            model_provider,
            model_name,
            e,
        )

    # Fallback to looking up the model in the model catalog. A
    # custom provider (e.g. Azure AI Foundry) may carry the real model
    # identity only in the deployment alias.
    return any(
        catalog_supports_image_input(name, model_provider)
        for name in model_identity_names(model_name, deployment_name)
    )


def model_needs_formatting_reenabled(
    model_name: str, deployment_name: str | None = None
) -> bool:
    # See https://simonwillison.net/tags/markdown/ for context on why this is needed
    # for OpenAI reasoning models to have correct markdown generation

    # Models that need formatting re-enabled
    model_names = ["gpt-5.1", "gpt-5", "o3", "o1"]

    # Pattern matches if any of these model names appear with word boundaries
    # Word boundaries include: start/end of string, space, hyphen, or forward slash
    pattern = (
        r"(?:^|[\s\-/])("
        + "|".join(re.escape(name) for name in model_names)
        + r")(?:$|[\s\-/])"
    )

    return any(
        re.search(pattern, name)
        for name in model_identity_names(model_name, deployment_name)
    )
