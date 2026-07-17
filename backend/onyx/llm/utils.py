import copy
import re
from collections.abc import Callable
from collections.abc import Iterable
from typing import Any
from typing import TYPE_CHECKING

from sqlalchemy import select

from onyx.configs.app_configs import LITELLM_CUSTOM_ERROR_MESSAGE_MAPPINGS
from onyx.configs.app_configs import MAX_TOKENS_FOR_FULL_INCLUSION
from onyx.configs.app_configs import SEND_USER_METADATA_TO_LLM_PROVIDER
from onyx.configs.app_configs import USE_CHUNK_SUMMARY
from onyx.configs.app_configs import USE_DOCUMENT_SUMMARY
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import LLMModelFlowType
from onyx.db.models import LLMProvider
from onyx.db.models import ModelConfiguration
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.model_capabilities import get_max_input_tokens
from onyx.llm.model_capabilities import litellm_thinks_model_supports_image_input
from onyx.llm.model_response import ModelResponse
from onyx.llm.models import UserMessage
from onyx.prompts.contextual_retrieval import CONTEXTUAL_RAG_TOKEN_ESTIMATE
from onyx.prompts.contextual_retrieval import DOCUMENT_SUMMARY_TOKEN_ESTIMATE
from onyx.utils.logger import setup_logger
from shared_configs.configs import DOC_EMBEDDING_CONTEXT_SIZE

if TYPE_CHECKING:
    from onyx.server.manage.llm.models import LLMProviderView


logger = setup_logger()

MAX_CONTEXT_TOKENS = 100
ONE_MILLION = 1_000_000
CHUNKS_PER_DOC_ESTIMATE = 5
MAX_LITELLM_USER_ID_LENGTH = 64


def truncate_litellm_user_id(user_id: str) -> str:
    """Truncate the LiteLLM `user` field maximum length."""
    if len(user_id) <= MAX_LITELLM_USER_ID_LENGTH:
        return user_id
    logger.warning(
        "User's ID exceeds %d chars (len=%d); truncating for Litellm logging compatibility.",
        MAX_LITELLM_USER_ID_LENGTH,
        len(user_id),
    )
    return user_id[:MAX_LITELLM_USER_ID_LENGTH]


def build_litellm_passthrough_kwargs(
    model_kwargs: dict[str, Any],
    user_identity: LLMUserIdentity | None,
) -> dict[str, Any]:
    """Build kwargs passed through directly to LiteLLM.

    Returns `model_kwargs` unchanged unless we need to add user/session metadata,
    in which case a copy is returned to avoid cross-request mutation.
    """

    if not (SEND_USER_METADATA_TO_LLM_PROVIDER and user_identity):
        return model_kwargs

    passthrough_kwargs = copy.deepcopy(model_kwargs)

    if user_identity.user_id:
        passthrough_kwargs["user"] = truncate_litellm_user_id(user_identity.user_id)

    if user_identity.session_id:
        existing_metadata = passthrough_kwargs.get("metadata")
        metadata: dict[str, Any] | None
        if existing_metadata is None:
            metadata = {}
        elif isinstance(existing_metadata, dict):
            metadata = copy.deepcopy(existing_metadata)
        else:
            metadata = None

        if metadata is not None:
            metadata["session_id"] = user_identity.session_id
            passthrough_kwargs["metadata"] = metadata

    return passthrough_kwargs


def _unwrap_nested_exception(error: Exception) -> Exception:
    """
    Traverse common exception wrappers to surface the underlying LiteLLM error.
    """
    visited: set[int] = set()
    current = error
    for _ in range(100):
        visited.add(id(current))
        candidate: Exception | None = None
        cause = getattr(current, "__cause__", None)
        if isinstance(cause, Exception):
            candidate = cause
        elif (
            hasattr(current, "args")
            and len(getattr(current, "args")) == 1
            and isinstance(current.args[0], Exception)
        ):
            candidate = current.args[0]
        if candidate is None or id(candidate) in visited:
            break
        current = candidate
    return current


def litellm_exception_to_error_msg(
    e: Exception,
    llm: LLM | None,
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
    from litellm.exceptions import APIConnectionError
    from litellm.exceptions import APIError
    from litellm.exceptions import AuthenticationError
    from litellm.exceptions import BadRequestError
    from litellm.exceptions import BudgetExceededError
    from litellm.exceptions import ContentPolicyViolationError
    from litellm.exceptions import ContextWindowExceededError
    from litellm.exceptions import NotFoundError
    from litellm.exceptions import PermissionDeniedError
    from litellm.exceptions import RateLimitError
    from litellm.exceptions import ServiceUnavailableError
    from litellm.exceptions import Timeout
    from litellm.exceptions import UnprocessableEntityError

    core_exception = _unwrap_nested_exception(e)
    error_msg = str(core_exception)
    error_code = "UNKNOWN_ERROR"
    is_retryable = True

    if custom_error_msg_mappings:
        for error_msg_pattern, custom_error_msg in custom_error_msg_mappings.items():
            if error_msg_pattern in error_msg:
                return custom_error_msg, "CUSTOM_ERROR", True

    # Both subclass BadRequestError, so they must precede the BadRequestError
    # branch or they'd be misclassified as BAD_REQUEST.
    if isinstance(core_exception, ContextWindowExceededError):
        error_msg = (
            "Context window exceeded: Your input is too long for the model to process."
        )
        if llm is not None:
            try:
                max_context = get_max_input_tokens(
                    model_name=llm.config.model_name,
                    model_provider=llm.config.model_provider,
                )
                error_msg += f" Your invoked model ({llm.config.model_name}) has a maximum context size of {max_context}."
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
            llm.config.model_provider
            if llm is not None and llm.config.model_provider
            else "The LLM provider"
        )
        upstream_detail: str | None = None
        message_attr = getattr(core_exception, "message", None)
        if message_attr:
            upstream_detail = str(message_attr)
        elif hasattr(core_exception, "api_error"):
            api_error = core_exception.api_error
            if isinstance(api_error, dict):
                upstream_detail = (
                    api_error.get("message")  # ty: ignore[invalid-argument-type]
                    or api_error.get("detail")  # ty: ignore[invalid-argument-type]
                    or api_error.get("error")  # ty: ignore[invalid-argument-type]
                )
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
            llm.config.model_provider
            if llm is not None and llm.config.model_provider
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
    elif str(getattr(core_exception, "status_code", "")) == "413" or (
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


_SCRUB_PLACEHOLDER = "[REDACTED]"


def scrub_sensitive_values(message: str, secrets: Iterable[str | None]) -> str:
    """Replace every literal secret in `message` with `[REDACTED]`.

    Defense in depth on top of `litellm_exception_to_error_msg` — that helper
    already maps known LiteLLM exception types to friendly messages and
    swallows unknown ones, but a few branches (`RateLimitError`, `APIError`,
    `ServiceUnavailableError`) still embed `str(core_exception)`. This pass
    strips any credential we already know about (typically the values pulled
    off `llm.config` via `collect_llm_credential_values`) before the message
    is surfaced to a client.

    Short / empty secrets are ignored so we don't accidentally eat common
    substrings.
    """
    if not message:
        return message

    scrubbed = message
    for secret in secrets:
        if not secret or len(secret) < 4:
            continue
        scrubbed = scrubbed.replace(secret, _SCRUB_PLACEHOLDER)

    return scrubbed


def collect_llm_credential_values(llm: LLM | None) -> list[str]:
    """Pull every credential-looking value out of an LLM's config.

    Used to build the `secrets` argument for `scrub_sensitive_values`.
    """
    if llm is None:
        return []
    config_secrets: list[str] = []
    if llm.config.api_key:
        config_secrets.append(llm.config.api_key)
    custom_config = llm.config.custom_config or {}
    for key, value in custom_config.items():
        if isinstance(value, str) and value and is_sensitive_custom_config_key(key):
            config_secrets.append(value)
    return config_secrets


def test_llm(llm: LLM) -> str | None:
    """Probe an LLM and return either `None` (success) or a sanitized error.

    The returned message is intended to be safe to surface to admin callers:
    raw upstream exception text is *not* echoed verbatim. Known LiteLLM
    exception types are mapped to friendly messages via
    `litellm_exception_to_error_msg`, and the result is then scrubbed of any
    credential values pulled from `llm.config` plus common header/JSON
    credential patterns.

    The full raw error is still logged at WARNING for ops debugging.
    """
    secrets = collect_llm_credential_values(llm)
    error_msg: str | None = None
    # try for up to 2 timeouts (e.g. 10 seconds in total)
    for _ in range(2):
        try:
            llm.invoke(UserMessage(content="Do not respond"), max_tokens=50)
            return None
        except Exception as e:
            logger.warning("Failed to call LLM with the following error: %s", e)
            safe_msg, _, _ = litellm_exception_to_error_msg(
                e, llm, fallback_to_error_msg=False
            )
            error_msg = scrub_sensitive_values(safe_msg, secrets)

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

    import litellm

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
        usd_per_prompt, usd_per_completion = litellm.cost_per_token(
            model=llm.config.model_name,
            prompt_tokens=num_input_tokens,
            completion_tokens=num_output_tokens,
        )
    except Exception:
        logger.exception(
            "An unexpected error occurred while calculating cost for model %s (potentially due to malformed name). Assuming cost is 0.",
            llm.config.model_name,
        )
        return 0

    # Costs are in USD dollars per million tokens
    return usd_per_prompt + usd_per_completion


def get_max_input_tokens_from_llm_provider(
    llm_provider: "LLMProviderView",
    model_name: str,
) -> int:
    """Get max input tokens for a model, with fallback chain.

    Fallback order:
    1. Use max_input_tokens from model_configuration (populated from source APIs
       like OpenRouter, Ollama, or our Bedrock mapping)
    2. Look up in litellm.model_cost dictionary
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
    return (
        max_input_tokens
        if max_input_tokens
        else get_max_input_tokens(
            model_provider=llm_provider.provider,
            model_name=model_name,
        )
    )


def model_supports_image_input(model_name: str, model_provider: str) -> bool:
    # First, try to read an explicit configuration from the model_configuration table
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

    # Fallback to looking up the model in the litellm model_cost dict
    return litellm_thinks_model_supports_image_input(model_name, model_provider)


def model_needs_formatting_reenabled(model_name: str) -> bool:
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

    if re.search(pattern, model_name):
        return True

    return False
