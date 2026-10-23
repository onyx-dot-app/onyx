import json
import os
from collections.abc import Mapping

from shared_configs.configs import DEFAULT_DOCUMENT_ENCODER_MODEL
from shared_configs.embedding_models import find_embedding_model_spec

#####
# Embedding/Reranking Model Configs
#####
# Important considerations when choosing models
# Max tokens count needs to be high considering use case (at least 512)
# Models used must be MIT or Apache license
# Inference/Indexing speed
# https://huggingface.co/DOCUMENT_ENCODER_MODEL
# The useable models configured as below must be SentenceTransformer compatible
# NOTE: DO NOT CHANGE SET THESE UNLESS YOU KNOW WHAT YOU ARE DOING
# IDEALLY, YOU SHOULD CHANGE EMBEDDING MODELS VIA THE UI
DOCUMENT_ENCODER_MODEL = (
    os.environ.get("DOCUMENT_ENCODER_MODEL") or DEFAULT_DOCUMENT_ENCODER_MODEL
)
# The settings below only seed the first search settings row of a fresh DB
# (alembic dbaa756c2ccf). Defaults come from the registry spec of
# DOCUMENT_ENCODER_MODEL (the old literals for other models). Their env vars
# count only with DOCUMENT_ENCODER_MODEL set, so an env file written for nomic
# cannot give the default model nomic's dimension or prefixes.
_MODEL_ENV: Mapping[str, str] = (
    os.environ if os.environ.get("DOCUMENT_ENCODER_MODEL") else {}
)
_DOCUMENT_ENCODER_SPEC = find_embedding_model_spec(None, DOCUMENT_ENCODER_MODEL)

DOC_EMBEDDING_DIM = int(
    _MODEL_ENV.get("DOC_EMBEDDING_DIM")
    or (_DOCUMENT_ENCODER_SPEC.model_dim if _DOCUMENT_ENCODER_SPEC else 768)
)
_NORMALIZE_EMBEDDINGS_DEFAULT = (
    _DOCUMENT_ENCODER_SPEC.normalize if _DOCUMENT_ENCODER_SPEC else True
)
NORMALIZE_EMBEDDINGS = (
    _MODEL_ENV.get("NORMALIZE_EMBEDDINGS")
    or ("true" if _NORMALIZE_EMBEDDINGS_DEFAULT else "false")
).lower() == "true"

# The default self-hosted model before granite.
PREVIOUS_DEFAULT_DOCUMENT_ENCODER_MODEL = "nomic-ai/nomic-embed-text-v1"

# Tokenizer for chat token counting and for the fallback when a model's own
# tokenizer can't load: env DOCUMENT_ENCODER_MODEL, else nomic (baked into the
# API image), so token counts do not depend on the default embedding model.
DEFAULT_TOKENIZER_MODEL = (
    os.environ.get("DOCUMENT_ENCODER_MODEL") or PREVIOUS_DEFAULT_DOCUMENT_ENCODER_MODEL
)

# Old default model settings, which are needed for an automatic easy upgrade
OLD_DEFAULT_DOCUMENT_ENCODER_MODEL = "thenlper/gte-small"
OLD_DEFAULT_MODEL_DOC_EMBEDDING_DIM = 384
OLD_DEFAULT_MODEL_NORMALIZE_EMBEDDINGS = False

# These are only used if reranking is turned off, to normalize the direct retrieval scores for display
# Currently unused
SIM_SCORE_RANGE_LOW = float(os.environ.get("SIM_SCORE_RANGE_LOW") or 0.0)
SIM_SCORE_RANGE_HIGH = float(os.environ.get("SIM_SCORE_RANGE_HIGH") or 1.0)
# Certain models like e5, BGE, etc use a prefix for asymmetric retrievals (query generally shorter than docs)
# An env var set to "" stays "" (no fallback to the default).
ASYM_QUERY_PREFIX = _MODEL_ENV.get(
    "ASYM_QUERY_PREFIX",
    _DOCUMENT_ENCODER_SPEC.query_prefix if _DOCUMENT_ENCODER_SPEC else "search_query: ",
)
ASYM_PASSAGE_PREFIX = _MODEL_ENV.get(
    "ASYM_PASSAGE_PREFIX",
    (
        _DOCUMENT_ENCODER_SPEC.passage_prefix
        if _DOCUMENT_ENCODER_SPEC
        else "search_document: "
    ),
)
# Purely an optimization, memory limitation consideration

# User's set embedding batch size overrides the default encoding batch sizes
EMBEDDING_BATCH_SIZE = int(os.environ.get("EMBEDDING_BATCH_SIZE") or 0) or None

BATCH_SIZE_ENCODE_CHUNKS = EMBEDDING_BATCH_SIZE or 8
# don't send over too many chunks at once, as sending too many could cause timeouts
BATCH_SIZE_ENCODE_CHUNKS_FOR_API_EMBEDDING_SERVICES = EMBEDDING_BATCH_SIZE or 512


#####
# Generative AI Model Configs
#####

# NOTE: the 2 below should only be used for dev.
GEN_AI_API_KEY = os.environ.get("GEN_AI_API_KEY")
GEN_AI_MODEL_VERSION = os.environ.get("GEN_AI_MODEL_VERSION")

# Fallback OpenAI model when no recommended or configured default exists.
DEFAULT_OPENAI_MODEL = "gpt-6-luna"

# Override the auto-detection of LLM max context length
GEN_AI_MAX_TOKENS = int(os.environ.get("GEN_AI_MAX_TOKENS") or 0) or None

# Set this to be enough for an answer + quotes. Also used for Chat
# This is the minimum token context we will leave for the LLM to generate an answer
GEN_AI_NUM_RESERVED_OUTPUT_TOKENS = int(
    os.environ.get("GEN_AI_NUM_RESERVED_OUTPUT_TOKENS") or 1024
)

# Fallback token limit for models where the max context is unknown
# Set conservatively at 32K to handle most modern models
GEN_AI_MODEL_FALLBACK_MAX_TOKENS = int(
    os.environ.get("GEN_AI_MODEL_FALLBACK_MAX_TOKENS") or 32000
)

# Fraction of max_input_tokens to hold back when fitting history: headroom for
# tiktoken undercounting the provider's tokenizer and overflowing the context.
GEN_AI_INPUT_TOKEN_SAFETY_MARGIN = float(
    os.environ.get("GEN_AI_INPUT_TOKEN_SAFETY_MARGIN") or 0.05
)
# Must be in [0, 1): >= 1 zeroes available_tokens; negative inflates the budget
# past the real limit.
if not 0.0 <= GEN_AI_INPUT_TOKEN_SAFETY_MARGIN < 1.0:
    raise ValueError(
        "GEN_AI_INPUT_TOKEN_SAFETY_MARGIN must be in [0, 1), got "
        f"{GEN_AI_INPUT_TOKEN_SAFETY_MARGIN}"
    )

GEN_AI_TEMPERATURE = float(os.environ.get("GEN_AI_TEMPERATURE") or 0)

# should be used if you are using a custom LLM inference provider that doesn't support
# streaming format AND you are still using the langchain/litellm LLM class
DISABLE_LITELLM_STREAMING = (
    os.environ.get("DISABLE_LITELLM_STREAMING") or "false"
).lower() == "true"

# extra headers to pass to LiteLLM
LITELLM_EXTRA_HEADERS: dict[str, str] | None = None
_LITELLM_EXTRA_HEADERS_RAW = os.environ.get("LITELLM_EXTRA_HEADERS")
if _LITELLM_EXTRA_HEADERS_RAW:
    try:
        LITELLM_EXTRA_HEADERS = json.loads(_LITELLM_EXTRA_HEADERS_RAW)
    except Exception:
        # need to import here to avoid circular imports
        from onyx.utils.logger import setup_logger

        logger = setup_logger()
        logger.error(
            "Failed to parse LITELLM_EXTRA_HEADERS, must be a valid JSON object"
        )

# if specified, will pass through request headers to the call to the LLM
LITELLM_PASS_THROUGH_HEADERS: list[str] | None = None
_LITELLM_PASS_THROUGH_HEADERS_RAW = os.environ.get("LITELLM_PASS_THROUGH_HEADERS")
if _LITELLM_PASS_THROUGH_HEADERS_RAW:
    try:
        LITELLM_PASS_THROUGH_HEADERS = json.loads(_LITELLM_PASS_THROUGH_HEADERS_RAW)
    except Exception:
        # need to import here to avoid circular imports
        from onyx.utils.logger import setup_logger

        logger = setup_logger()
        logger.error(
            "Failed to parse LITELLM_PASS_THROUGH_HEADERS, must be a valid JSON object"
        )


# if specified, will merge the specified JSON with the existing body of the
# request before sending it to the LLM
LITELLM_EXTRA_BODY: dict | None = None
_LITELLM_EXTRA_BODY_RAW = os.environ.get("LITELLM_EXTRA_BODY")
if _LITELLM_EXTRA_BODY_RAW:
    try:
        LITELLM_EXTRA_BODY = json.loads(_LITELLM_EXTRA_BODY_RAW)
    except Exception:
        pass

#####
# Prompt Caching Configs
#####
# Enable prompt caching framework
ENABLE_PROMPT_CACHING = (
    os.environ.get("ENABLE_PROMPT_CACHING", "true").lower() != "false"
)

# Cache TTL multiplier - store caches slightly longer than provider TTL
# This allows for some clock skew and ensures we don't lose cache metadata prematurely
PROMPT_CACHE_REDIS_TTL_MULTIPLIER = float(
    os.environ.get("PROMPT_CACHE_REDIS_TTL_MULTIPLIER") or 1.2
)
