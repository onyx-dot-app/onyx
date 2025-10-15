import os
from typing import Any
from typing import List
from urllib.parse import urlparse

# Used for logging
SLACK_CHANNEL_ID = "channel_id"

# Skip model warmup at startup
# Default to True (skip warmup) if not set, otherwise respect the value
SKIP_WARM_UP = os.environ.get("SKIP_WARM_UP", "true").lower() == "true"

MODEL_SERVER_HOST = os.environ.get("MODEL_SERVER_HOST") or "localhost"
MODEL_SERVER_ALLOWED_HOST = os.environ.get("MODEL_SERVER_HOST") or "0.0.0.0"
MODEL_SERVER_PORT = int(os.environ.get("MODEL_SERVER_PORT") or "9000")
# Model server for indexing should use a separate one to not allow indexing to introduce delay
# for inference
INDEXING_MODEL_SERVER_HOST = (
    os.environ.get("INDEXING_MODEL_SERVER_HOST") or MODEL_SERVER_HOST
)
INDEXING_MODEL_SERVER_PORT = int(
    os.environ.get("INDEXING_MODEL_SERVER_PORT") or MODEL_SERVER_PORT
)

# Onyx custom Deep Learning Models
CONNECTOR_CLASSIFIER_MODEL_REPO = "Danswer/filter-extraction-model"
CONNECTOR_CLASSIFIER_MODEL_TAG = "1.0.0"
INTENT_MODEL_VERSION = "onyx-dot-app/hybrid-intent-token-classifier"
# INTENT_MODEL_TAG = "v1.0.3"
INTENT_MODEL_TAG: str | None = None
INFORMATION_CONTENT_MODEL_VERSION = "onyx-dot-app/information-content-model"
INFORMATION_CONTENT_MODEL_TAG: str | None = None

# Bi-Encoder, other details
DOC_EMBEDDING_CONTEXT_SIZE = 512

# Used to distinguish alternative indices
ALT_INDEX_SUFFIX = "__danswer_alt_index"

# Used for loading defaults for automatic deployments and dev flows
# For local, use: mixedbread-ai/mxbai-rerank-xsmall-v1
DEFAULT_CROSS_ENCODER_MODEL_NAME = (
    os.environ.get("DEFAULT_CROSS_ENCODER_MODEL_NAME") or None
)
DEFAULT_CROSS_ENCODER_API_KEY = os.environ.get("DEFAULT_CROSS_ENCODER_API_KEY") or None
DEFAULT_CROSS_ENCODER_PROVIDER_TYPE = (
    os.environ.get("DEFAULT_CROSS_ENCODER_PROVIDER_TYPE") or None
)
DISABLE_RERANK_FOR_STREAMING = (
    os.environ.get("DISABLE_RERANK_FOR_STREAMING", "").lower() == "true"
)

# This controls the minimum number of pytorch "threads" to allocate to the embedding
# model. If torch finds more threads on its own, this value is not used.
MIN_THREADS_ML_MODELS = int(os.environ.get("MIN_THREADS_ML_MODELS") or 1)

# Model server that has indexing only set will throw exception if used for reranking
# or intent classification
INDEXING_ONLY = os.environ.get("INDEXING_ONLY", "").lower() == "true"

# The process needs to have this for the log file to write to
# otherwise, it will not create additional log files
# This should just be the filename base without extension or path.
LOG_FILE_NAME = os.environ.get("LOG_FILE_NAME") or "onyx"

# Enable generating persistent log files for local dev environments
DEV_LOGGING_ENABLED = os.environ.get("DEV_LOGGING_ENABLED", "").lower() == "true"
# notset, debug, info, notice, warning, error, or critical
LOG_LEVEL = os.environ.get("LOG_LEVEL") or "info"

# Timeout for API-based embedding models
# NOTE: does not apply for Google VertexAI, since the python client doesn't
# allow us to specify a custom timeout
API_BASED_EMBEDDING_TIMEOUT = int(os.environ.get("API_BASED_EMBEDDING_TIMEOUT", "600"))

# Local batch size for VertexAI embedding models currently calibrated for item size of 512 tokens
# NOTE: increasing this value may lead to API errors due to token limit exhaustion per call.
VERTEXAI_EMBEDDING_LOCAL_BATCH_SIZE = int(
    os.environ.get("VERTEXAI_EMBEDDING_LOCAL_BATCH_SIZE", "25")
)

# Only used for OpenAI
OPENAI_EMBEDDING_TIMEOUT = int(
    os.environ.get("OPENAI_EMBEDDING_TIMEOUT", API_BASED_EMBEDDING_TIMEOUT)
)

# Whether or not to strictly enforce token limit for chunking.
STRICT_CHUNK_TOKEN_LIMIT = (
    os.environ.get("STRICT_CHUNK_TOKEN_LIMIT", "").lower() == "true"
)

# Set up Sentry integration (for error logging)
SENTRY_DSN = os.environ.get("SENTRY_DSN")


# Fields which should only be set on new search setting
PRESERVED_SEARCH_FIELDS = [
    "id",
    "provider_type",
    "api_key",
    "model_name",
    "api_url",
    "index_name",
    "multipass_indexing",
    "enable_contextual_rag",
    "model_dim",
    "normalize",
    "passage_prefix",
    "query_prefix",
]


def validate_cors_origin(origin: str) -> None:
    parsed = urlparse(origin)
    if parsed.scheme not in ["http", "https"] or not parsed.netloc:
        raise ValueError(f"Invalid CORS origin: '{origin}'")


# Examples of valid values for the environment variable:
# - "" (allow all origins)
# - "http://example.com" (single origin)
# - "http://example.com,https://example.org" (multiple origins)
# - "*" (allow all origins)
CORS_ALLOWED_ORIGIN_ENV = os.environ.get("CORS_ALLOWED_ORIGIN", "")

# Explicitly declare the type of CORS_ALLOWED_ORIGIN
CORS_ALLOWED_ORIGIN: List[str]

if CORS_ALLOWED_ORIGIN_ENV:
    # Split the environment variable into a list of origins
    CORS_ALLOWED_ORIGIN = [
        origin.strip()
        for origin in CORS_ALLOWED_ORIGIN_ENV.split(",")
        if origin.strip()
    ]
    # Validate each origin in the list
    for origin in CORS_ALLOWED_ORIGIN:
        validate_cors_origin(origin)
else:
    # If the environment variable is empty, allow all origins
    CORS_ALLOWED_ORIGIN = ["*"]


# Multi-tenancy configuration
MULTI_TENANT = os.environ.get("MULTI_TENANT", "").lower() == "true"

# Outside this file, should almost always use `POSTGRES_DEFAULT_SCHEMA` unless you
# have a very good reason
POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE = "public"
POSTGRES_DEFAULT_SCHEMA = (
    os.environ.get("POSTGRES_DEFAULT_SCHEMA") or POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
)
DEFAULT_REDIS_PREFIX = os.environ.get("DEFAULT_REDIS_PREFIX") or "default"


async def async_return_default_schema(*args: Any, **kwargs: Any) -> str:
    return POSTGRES_DEFAULT_SCHEMA


# Prefix used for all tenant ids
TENANT_ID_PREFIX = "tenant_"

DISALLOWED_SLACK_BOT_TENANT_IDS = os.environ.get("DISALLOWED_SLACK_BOT_TENANT_IDS")
DISALLOWED_SLACK_BOT_TENANT_LIST = (
    [tenant.strip() for tenant in DISALLOWED_SLACK_BOT_TENANT_IDS.split(",")]
    if DISALLOWED_SLACK_BOT_TENANT_IDS
    else None
)

IGNORED_SYNCING_TENANT_IDS = os.environ.get("IGNORED_SYNCING_TENANT_IDS")
IGNORED_SYNCING_TENANT_LIST = (
    [tenant.strip() for tenant in IGNORED_SYNCING_TENANT_IDS.split(",")]
    if IGNORED_SYNCING_TENANT_IDS
    else None
)

# Maximum (least severe) downgrade factor for chunks above the cutoff
INDEXING_INFORMATION_CONTENT_CLASSIFICATION_MAX = float(
    os.environ.get("INDEXING_INFORMATION_CONTENT_CLASSIFICATION_MAX") or 1.0
)
# Minimum (most severe) downgrade factor for short chunks below the cutoff if no content
INDEXING_INFORMATION_CONTENT_CLASSIFICATION_MIN = float(
    os.environ.get("INDEXING_INFORMATION_CONTENT_CLASSIFICATION_MIN") or 0.7
)
# Temperature for the information content classification model
INDEXING_INFORMATION_CONTENT_CLASSIFICATION_TEMPERATURE = float(
    os.environ.get("INDEXING_INFORMATION_CONTENT_CLASSIFICATION_TEMPERATURE") or 4.0
)
# Cutoff below which we start using the information content classification model
# (cutoff length number itself is still considered 'short'))
INDEXING_INFORMATION_CONTENT_CLASSIFICATION_CUTOFF_LENGTH = int(
    os.environ.get("INDEXING_INFORMATION_CONTENT_CLASSIFICATION_CUTOFF_LENGTH") or 10
)

ENVIRONMENT = os.environ.get("ENVIRONMENT") or "not_explicitly_set"
