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
# Model should be chosen with 512 context size, ideally don't change this
# If multipass_indexing is enabled, the max context size would be set to
# DOC_EMBEDDING_CONTEXT_SIZE * LARGE_CHUNK_RATIO
DOC_EMBEDDING_CONTEXT_SIZE = 512
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
BATCH_SIZE_ENCODE_CHUNKS = 8
# don't send over too many chunks at once, as sending too many could cause timeouts
BATCH_SIZE_ENCODE_CHUNKS_FOR_API_EMBEDDING_SERVICES = 512
# For score display purposes, only way is to know the expected ranges
CROSS_ENCODER_RANGE_MAX = 1
CROSS_ENCODER_RANGE_MIN = 0


#####
# Generative AI Model Configs
#####

# If changing GEN_AI_MODEL_PROVIDER or GEN_AI_MODEL_VERSION from the default,
# be sure to use one that is LiteLLM compatible:
# https://litellm.vercel.app/docs/providers/azure#completion---using-env-variables
# The provider is the prefix before / in the model argument

# Additionally Danswer supports GPT4All and custom request library based models
# Set GEN_AI_MODEL_PROVIDER to "custom" to use the custom requests approach
# Set GEN_AI_MODEL_PROVIDER to "gpt4all" to use gpt4all models running locally
GEN_AI_MODEL_PROVIDER = os.environ.get("GEN_AI_MODEL_PROVIDER") or "openai"
# If using Azure, it's the engine name, for example: Danswer
GEN_AI_MODEL_VERSION = os.environ.get("GEN_AI_MODEL_VERSION")

# For secondary flows like extracting filters or deciding if a chunk is useful, we don't need
# as powerful of a model as say GPT-4 so we can use an alternative that is faster and cheaper
FAST_GEN_AI_MODEL_VERSION = os.environ.get("FAST_GEN_AI_MODEL_VERSION")

# If the Generative AI model requires an API key for access, otherwise can leave blank
GEN_AI_API_KEY = (
    os.environ.get("GEN_AI_API_KEY", os.environ.get("OPENAI_API_KEY")) or None
)

# API Base, such as (for Azure): https://danswer.openai.azure.com/
GEN_AI_API_ENDPOINT = os.environ.get("GEN_AI_API_ENDPOINT") or None
# API Version, such as (for Azure): 2023-09-15-preview
GEN_AI_API_VERSION = os.environ.get("GEN_AI_API_VERSION") or None
# LiteLLM custom_llm_provider
GEN_AI_LLM_PROVIDER_TYPE = os.environ.get("GEN_AI_LLM_PROVIDER_TYPE") or None
# Override the auto-detection of LLM max context length
GEN_AI_MAX_TOKENS = int(os.environ.get("GEN_AI_MAX_TOKENS") or 0) or None
# Set this to be enough for an answer + quotes. Also used for Chat
GEN_AI_MAX_OUTPUT_TOKENS = int(os.environ.get("GEN_AI_MAX_OUTPUT_TOKENS") or 1024)

# Typically, GenAI models nowadays are at least 4K tokens
GEN_AI_MODEL_DEFAULT_MAX_TOKENS = 4096
# Number of tokens from chat history to include at maximum
# 3000 should be enough context regardless of use, no need to include as much as possible
# as this drives up the cost unnecessarily
GEN_AI_HISTORY_CUTOFF = 3000
# This is used when computing how much context space is available for documents
# ahead of time in order to let the user know if they can "select" more documents
# It represents a maximum "expected" number of input tokens from the latest user
# message. At query time, we don't actually enforce this - we will only throw an
# error if the total # of tokens exceeds the max input tokens.
GEN_AI_SINGLE_USER_MESSAGE_EXPECTED_MAX_TOKENS = 512
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
        from danswer.utils.logger import setup_logger

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
        from danswer.utils.logger import setup_logger

        logger = setup_logger()
        logger.error(
            "Failed to parse LITELLM_PASS_THROUGH_HEADERS, must be a valid JSON object"
        )
