import copy
import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from pydantic import JsonValue
from sqlalchemy import select

from onyx.configs.app_configs import (
    MAX_TOKENS_FOR_FULL_INCLUSION,
    SEND_USER_METADATA_TO_LLM_PROVIDER,
    USE_CHUNK_SUMMARY,
    USE_DOCUMENT_SUMMARY,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import LLMModelFlowType
from onyx.db.models import LLMProvider, ModelConfiguration
from onyx.llm.exceptions import litellm_exception_to_safe_error
from onyx.llm.interfaces import LLM, GenerationContext, LLMUserIdentity
from onyx.llm.model_capabilities import (
    catalog_model_supports_image_input,
    get_max_input_tokens,
    model_identity_names,
)
from onyx.llm.models import GenerationOptions, GenerationRequest, UserMessage
from onyx.prompts.contextual_retrieval import (
    CONTEXTUAL_RAG_TOKEN_ESTIMATE,
    DOCUMENT_SUMMARY_TOKEN_ESTIMATE,
)
from onyx.tracing.flows import LLMFlow
from onyx.utils.logger import setup_logger
from shared_configs.configs import DOC_EMBEDDING_CONTEXT_SIZE

if TYPE_CHECKING:
    from onyx.server.manage.llm.models import LLMProviderView


logger = setup_logger()

# An admin watches a spinner while this runs, and test_llm makes two attempts.
LLM_PROBE_TIMEOUT_S = 10

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
    model_kwargs: dict[str, JsonValue],
    user_identity: LLMUserIdentity | None,
) -> dict[str, JsonValue]:
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
        metadata: dict[str, JsonValue] | None
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


# Credential-bearing custom configuration keys used for response and error masking.
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


def test_llm(llm: LLM, total_timeout_s: float = LLM_PROBE_TIMEOUT_S) -> str | None:
    """Probe a model and return either `None` (success) or a sanitized error.

    The returned message is intended to be safe to surface to admin callers:
    raw upstream exception text is *not* echoed verbatim. Known LiteLLM
    exception types are mapped to friendly messages via
    `litellm_exception_to_error_msg`, and the result is then scrubbed of any
    provider credentials and common header/JSON credential patterns.

    The full raw error is still logged at WARNING for ops debugging.
    """
    error_msg: str | None = None
    # Two attempts, so the caller waits at most 2 * total_timeout_s.
    for _ in range(2):
        try:
            llm.invoke(
                GenerationRequest(
                    messages=[UserMessage(content="Do not respond")],
                    options=GenerationOptions(max_tokens=50),
                ),
                context=GenerationContext(
                    flow=LLMFlow.MODEL_VALIDATION, total_timeout_s=total_timeout_s
                ),
            )
            return None
        except Exception as e:
            logger.warning("Failed to call LLM with the following error: %s", e)
            error_msg = litellm_exception_to_safe_error(e, llm).message

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
    2. Look up in the vendored model catalog
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
        catalog_model_supports_image_input(name, model_provider)
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
