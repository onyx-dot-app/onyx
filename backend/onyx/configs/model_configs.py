import json
import os

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
DEFAULT_DOCUMENT_ENCODER_MODEL = "nomic-ai/nomic-embed-text-v1"
DOCUMENT_ENCODER_MODEL = (
    os.environ.get("DOCUMENT_ENCODER_MODEL") or DEFAULT_DOCUMENT_ENCODER_MODEL
)
# If the below is changed, Vespa deployment must also be changed
DOC_EMBEDDING_DIM = int(os.environ.get("DOC_EMBEDDING_DIM") or 768)
NORMALIZE_EMBEDDINGS = (
    os.environ.get("NORMALIZE_EMBEDDINGS") or "true"
).lower() == "true"

# Old default model settings, which are needed for an automatic easy upgrade
OLD_DEFAULT_DOCUMENT_ENCODER_MODEL = "thenlper/gte-small"
OLD_DEFAULT_MODEL_DOC_EMBEDDING_DIM = 384
OLD_DEFAULT_MODEL_NORMALIZE_EMBEDDINGS = False

# These are only used if reranking is turned off, to normalize the direct retrieval scores for display
# Currently unused
SIM_SCORE_RANGE_LOW = float(os.environ.get("SIM_SCORE_RANGE_LOW") or 0.0)
SIM_SCORE_RANGE_HIGH = float(os.environ.get("SIM_SCORE_RANGE_HIGH") or 1.0)
# Certain models like e5, BGE, etc use a prefix for asymmetric retrievals (query generally shorter than docs)
ASYM_QUERY_PREFIX = os.environ.get("ASYM_QUERY_PREFIX", "search_query: ")
ASYM_PASSAGE_PREFIX = os.environ.get("ASYM_PASSAGE_PREFIX", "search_document: ")
# Purely an optimization, memory limitation consideration

# User's set embedding batch size overrides the default encoding batch sizes
EMBEDDING_BATCH_SIZE = int(os.environ.get("EMBEDDING_BATCH_SIZE") or 0) or None

BATCH_SIZE_ENCODE_CHUNKS = EMBEDDING_BATCH_SIZE or 8
# don't send over too many chunks at once, as sending too many could cause timeouts
BATCH_SIZE_ENCODE_CHUNKS_FOR_API_EMBEDDING_SERVICES = EMBEDDING_BATCH_SIZE or 512
# For score display purposes, only way is to know the expected ranges
CROSS_ENCODER_RANGE_MAX = 1
CROSS_ENCODER_RANGE_MIN = 0


#####
# Generative AI Model Configs
#####

# NOTE: the 2 below should only be used for dev.
GEN_AI_API_KEY = os.environ.get("GEN_AI_API_KEY")
GEN_AI_MODEL_VERSION = os.environ.get("GEN_AI_MODEL_VERSION")

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

# This is used when computing how much context space is available for documents
# ahead of time in order to let the user know if they can "select" more documents
# It represents a maximum "expected" number of input tokens from the latest user
# message. At query time, we don't actually enforce this - we will only throw an
# error if the total # of tokens exceeds the max input tokens.
GEN_AI_SINGLE_USER_MESSAGE_EXPECTED_MAX_TOKENS = 512
GEN_AI_TEMPERATURE = float(os.environ.get("GEN_AI_TEMPERATURE") or 0)

# Reasoning models use effort to control the amount of reasoning
# before tool calling or answer generation.
DEFAULT_REASONING_EFFORT = os.environ.get("DEFAULT_REASONING_EFFORT") or "low"

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
