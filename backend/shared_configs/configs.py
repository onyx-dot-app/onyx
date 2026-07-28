"""Facade over SharedSettings (shared_configs/settings.py).

Constants keep their historical names so the hundreds of
``from shared_configs.configs import X`` call sites are unaffected. The
settings instance is constructed at module scope on purpose: reloading this
module re-reads the environment (the seam ``monkeypatch.setenv`` +
``importlib.reload`` tests rely on), while the TOML document itself stays
memoized per path in settings_base.
"""

from typing import Any, List
from urllib.parse import urlparse

from shared_configs.settings import SharedSettings

# Used for logging
SLACK_CHANNEL_ID = "channel_id"

_settings = SharedSettings()

# Skip model warmup at startup
SKIP_WARM_UP = _settings.skip_warm_up

# If the model server is disabled, hosts are the "disabled" sentinel so
# downstream clients skip it (resolved inside SharedSettings).
DISABLE_MODEL_SERVER = _settings.disable_model_server
MODEL_SERVER_HOST = _settings.model_server_host
MODEL_SERVER_ALLOWED_HOST = _settings.model_server_allowed_host
INDEXING_MODEL_SERVER_HOST = _settings.indexing_model_server_host

MODEL_SERVER_PORT = _settings.model_server_port
# Model server for indexing should use a separate one to not allow indexing to
# introduce delay for inference
INDEXING_MODEL_SERVER_PORT = _settings.indexing_model_server_port

# Onyx custom Deep Learning Models
CONNECTOR_CLASSIFIER_MODEL_REPO = "Danswer/filter-extraction-model"
CONNECTOR_CLASSIFIER_MODEL_TAG = "1.0.0"
INTENT_MODEL_VERSION = "onyx-dot-app/hybrid-intent-token-classifier"
# INTENT_MODEL_TAG = "v1.0.3"
INTENT_MODEL_TAG: str | None = None
# Bi-Encoder, other details
DOC_EMBEDDING_CONTEXT_SIZE = 512

# Used to distinguish alternative indices
ALT_INDEX_SUFFIX = "__danswer_alt_index"

# Used for loading defaults for automatic deployments and dev flows
# For local, use: mixedbread-ai/mxbai-rerank-xsmall-v1
DEFAULT_CROSS_ENCODER_MODEL_NAME = _settings.default_cross_encoder_model_name
DEFAULT_CROSS_ENCODER_API_KEY = _settings.default_cross_encoder_api_key
DEFAULT_CROSS_ENCODER_PROVIDER_TYPE = _settings.default_cross_encoder_provider_type
DISABLE_RERANK_FOR_STREAMING = _settings.disable_rerank_for_streaming

# This controls the minimum number of pytorch "threads" to allocate to the
# embedding model. If torch finds more threads on its own, this value is not
# used.
MIN_THREADS_ML_MODELS = _settings.min_threads_ml_models

# Model server that has indexing only set will throw exception if used for
# reranking or intent classification
INDEXING_ONLY = _settings.indexing_only

# The process needs to have this for the log file to write to
# otherwise, it will not create additional log files
# This should just be the filename base without extension or path.
LOG_FILE_NAME = _settings.log_file_name

# Enable generating persistent log files for local dev environments
DEV_LOGGING_ENABLED = _settings.dev_logging_enabled
# File logging is on by default. Set LOG_TO_FILE=false to disable it for a
# given pod/process — it then logs to stdout only (e.g. read-only-root
# containers where /var/log/onyx isn't writable).
LOG_TO_FILE = _settings.log_to_file
# notset, debug, info, notice, warning, error, or critical
LOG_LEVEL = _settings.log_level

# Log output format: "plain" (human-readable text, default) or "json"
# (structured single-line JSON, suitable for container log aggregators). When
# "json", context such as tenant/request/task ids are emitted as discrete
# fields rather than being prefixed into the message string.
LOG_FORMAT = _settings.log_format
JSON_LOGGING = LOG_FORMAT == "json"

# Timeout for API-based embedding models
# NOTE: does not apply for Google VertexAI, since the python client doesn't
# allow us to specify a custom timeout
API_BASED_EMBEDDING_TIMEOUT = _settings.api_based_embedding_timeout

# Timeouts for requests to the self-hosted model server (embedding / rerank /
# intent). The connect timeout fails fast on an unreachable server; the read
# timeout bounds silent hangs — without one, a model-server pod restarting
# mid-request leaves the calling worker thread blocked forever inside
# requests.post (observed wedging every docprocessing thread for hours during
# an upgrade). Reads are generous because CPU embedding of large batches can
# legitimately take minutes.
MODEL_SERVER_CONNECT_TIMEOUT = _settings.model_server_connect_timeout
MODEL_SERVER_READ_TIMEOUT = _settings.model_server_read_timeout

# Local batch size for VertexAI embedding models currently calibrated for item
# size of 512 tokens
# NOTE: increasing this value may lead to API errors due to token limit
# exhaustion per call.
VERTEXAI_EMBEDDING_LOCAL_BATCH_SIZE = _settings.vertexai_embedding_local_batch_size

# Only used for OpenAI
OPENAI_EMBEDDING_TIMEOUT = _settings.openai_embedding_timeout

# Whether or not to strictly enforce token limit for chunking.
STRICT_CHUNK_TOKEN_LIMIT = _settings.strict_chunk_token_limit

# Set up Sentry integration (for error logging)
SENTRY_DSN = _settings.sentry_dsn

# Celery task spans dominate ingestion volume (~94%), so default celery
# tracing to 0. Web/API traces stay at a small non-zero rate so http.server
# traces remain available. Both are env-tunable without a code change.
SENTRY_TRACES_SAMPLE_RATE = _settings.sentry_traces_sample_rate
SENTRY_CELERY_TRACES_SAMPLE_RATE = _settings.sentry_celery_traces_sample_rate


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
    # Immutable per settings id; server-controlled, never set via update.
    "use_port_flow",
]


def validate_cors_origin(origin: str) -> None:
    parsed = urlparse(origin)
    if parsed.scheme not in ["http", "https"] or not parsed.netloc:
        raise ValueError(f"Invalid CORS origin: '{origin}'")


# Examples of valid values for the environment variable:
# - "" (allow all origins, credentials disabled)
# - "http://example.com" (single origin)
# - "http://example.com,https://example.org" (multiple origins)
# - "*" (allow all origins, credentials disabled)
CORS_ALLOWED_ORIGIN_ENV = _settings.cors_allowed_origin


def parse_cors_allowed_origins(env_value: str) -> List[str]:
    origins = [origin.strip() for origin in env_value.split(",") if origin.strip()]
    if not origins:
        # If the environment variable is empty, allow all origins
        return ["*"]
    for origin in origins:
        if origin != "*":
            validate_cors_origin(origin)
    return origins


def cors_allow_credentials(allowed_origins: List[str]) -> bool:
    # A wildcard origin must never be paired with allow_credentials=True:
    # browsers reject "Access-Control-Allow-Origin: *" on credentialed
    # responses, and Starlette compensates by echoing arbitrary request
    # Origins on preflights, which would let any site make credentialed
    # (cookie-authenticated) cross-origin requests.
    return "*" not in allowed_origins


CORS_ALLOWED_ORIGIN: List[str] = parse_cors_allowed_origins(CORS_ALLOWED_ORIGIN_ENV)
CORS_ALLOW_CREDENTIALS: bool = cors_allow_credentials(CORS_ALLOWED_ORIGIN)


# Multi-tenancy configuration
MULTI_TENANT = _settings.multi_tenant

# Outside this file, should almost always use `POSTGRES_DEFAULT_SCHEMA` unless
# you have a very good reason
POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE = "public"
POSTGRES_DEFAULT_SCHEMA = _settings.postgres_default_schema
DEFAULT_REDIS_PREFIX = _settings.default_redis_prefix


async def async_return_default_schema(
    *args: Any,  # noqa: ARG001
    **kwargs: Any,  # noqa: ARG001
) -> str:
    return POSTGRES_DEFAULT_SCHEMA


# Prefix used for all tenant ids
TENANT_ID_PREFIX = "tenant_"

DISALLOWED_SLACK_BOT_TENANT_IDS = _settings.disallowed_slack_bot_tenant_ids
DISALLOWED_SLACK_BOT_TENANT_LIST = (
    [
        tenant.strip()
        for tenant in DISALLOWED_SLACK_BOT_TENANT_IDS.split(",")
        if tenant.strip()
    ]
    if DISALLOWED_SLACK_BOT_TENANT_IDS
    else None
)

IGNORED_SYNCING_TENANT_IDS = _settings.ignored_syncing_tenant_ids
IGNORED_SYNCING_TENANT_LIST = (
    [
        tenant.strip()
        for tenant in IGNORED_SYNCING_TENANT_IDS.split(",")
        if tenant.strip()
    ]
    if IGNORED_SYNCING_TENANT_IDS
    else None
)

ENVIRONMENT = _settings.environment


#####
# Usage Limits Configuration (meant for cloud, off by default for self-hosted)
#####
# Whether usage limits are enforced (defaults to MULTI_TENANT value)
USAGE_LIMITS_ENABLED = _settings.usage_limits_enabled

# Usage limit window in seconds (default: 1 week = 604800 seconds)
USAGE_LIMIT_WINDOW_SECONDS = _settings.usage_limit_window_seconds

# Per-week LLM usage cost limits in cents (e.g., 1000 = $10.00)
# Trial users get lower limits than paid users
USAGE_LIMIT_LLM_COST_CENTS_TRIAL = _settings.usage_limit_llm_cost_cents_trial
USAGE_LIMIT_LLM_COST_CENTS_PAID = _settings.usage_limit_llm_cost_cents_paid

# Per-week chunks indexed limits
USAGE_LIMIT_CHUNKS_INDEXED_TRIAL = _settings.usage_limit_chunks_indexed_trial
USAGE_LIMIT_CHUNKS_INDEXED_PAID = _settings.usage_limit_chunks_indexed_paid

# Per-week API calls using API keys or Personal Access Tokens
USAGE_LIMIT_API_CALLS_TRIAL = _settings.usage_limit_api_calls_trial
USAGE_LIMIT_API_CALLS_PAID = _settings.usage_limit_api_calls_paid

# Per-week non-streaming API calls (more expensive, so lower limits)
USAGE_LIMIT_NON_STREAMING_CALLS_TRIAL = _settings.usage_limit_non_streaming_calls_trial
USAGE_LIMIT_NON_STREAMING_CALLS_PAID = _settings.usage_limit_non_streaming_calls_paid
