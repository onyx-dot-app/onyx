"""Typed schema for the config surface shared by the backend and the model
server. The facade that preserves the legacy constant names lives in
``shared_configs/configs.py``.

Must stay importable by ``model_server``: stdlib and pydantic only, never
``onyx.*``.
"""

from pydantic import model_validator

from shared_configs.settings_base import (
    LegacyEnvBool,
    LegacyEnvBoolUnlessFalse,
    OnyxBaseSettings,
    onyx_field,
)

# Sentinel host that tells model-server clients to skip the call entirely.
MODEL_SERVER_DISABLED_HOST = "disabled"


class SharedSettings(OnyxBaseSettings):
    # --- model server ---
    skip_warm_up: LegacyEnvBool = onyx_field(
        default=True,
        toml="model_server.skip_warm_up",
        description="Skip ML model warmup at startup.",
        # Legacy default was the string "true", so a blank value read as False
        # rather than falling back to the default.
        blank_is_falsy=True,
    )
    disable_model_server: LegacyEnvBool = onyx_field(
        default=False,
        toml="model_server.disable",
        description="Disable the model server entirely; hosts become 'disabled'.",
    )
    model_server_host: str = onyx_field(
        default="localhost",
        toml="model_server.host",
        description="Hostname of the inference model server.",
    )
    model_server_allowed_host: str = onyx_field(
        default="0.0.0.0",  # noqa: S104 — intentional bind default for containers
        # Legacy reads MODEL_SERVER_HOST for this too, with a different
        # default. Deliberately NOT also exposing MODEL_SERVER_ALLOWED_HOST:
        # separating the bind address from the client-facing host is a real
        # improvement, but it is a new operator knob and belongs in its own
        # change, not smuggled in by a config refactor.
        env=("MODEL_SERVER_HOST",),
        toml="model_server.allowed_host",
        description="Host or interface the model server binds to.",
    )
    indexing_model_server_host: str = onyx_field(
        default_factory=lambda data: data["model_server_host"],
        toml="model_server.indexing_host",
        description="Hostname of the dedicated indexing model server; defaults "
        "to the inference model server host.",
    )
    model_server_port: int = onyx_field(
        default=9000,
        toml="model_server.port",
        description="Port of the inference model server.",
    )
    indexing_model_server_port: int = onyx_field(
        default_factory=lambda data: data["model_server_port"],
        toml="model_server.indexing_port",
        description="Port of the dedicated indexing model server; defaults to "
        "the inference model server port.",
    )
    min_threads_ml_models: int = onyx_field(
        default=1,
        toml="model_server.min_threads_ml_models",
        description="Minimum number of torch threads for embedding models.",
    )
    indexing_only: LegacyEnvBool = onyx_field(
        default=False,
        toml="model_server.indexing_only",
        description="Model server serves indexing requests only.",
    )
    model_server_connect_timeout: int = onyx_field(
        default=30,
        toml="model_server.connect_timeout",
        description="Connect timeout in seconds for model server requests.",
    )
    model_server_read_timeout: int = onyx_field(
        default=600,
        toml="model_server.read_timeout",
        description="Read timeout in seconds for model server requests.",
    )

    # --- reranking ---
    default_cross_encoder_model_name: str | None = onyx_field(
        default=None,
        toml="rerank.default_model_name",
        description="Default cross-encoder model for automatic deployments.",
    )
    default_cross_encoder_api_key: str | None = onyx_field(
        default=None,
        toml="rerank.default_api_key",
        description="API key for the default cross-encoder provider.",
        secret=True,
    )
    default_cross_encoder_provider_type: str | None = onyx_field(
        default=None,
        toml="rerank.default_provider_type",
        description="Provider type for the default cross-encoder.",
    )
    disable_rerank_for_streaming: LegacyEnvBool = onyx_field(
        default=False,
        toml="rerank.disable_for_streaming",
        description="Skip reranking in streaming flows.",
    )

    # --- logging ---
    log_file_name: str = onyx_field(
        default="onyx",
        toml="logging.file_name",
        description="Base filename, no extension or path, for log files.",
    )
    dev_logging_enabled: LegacyEnvBool = onyx_field(
        default=False,
        toml="logging.dev_logging_enabled",
        description="Generate persistent log files for local dev environments.",
    )
    log_to_file: LegacyEnvBoolUnlessFalse = onyx_field(
        default=True,
        toml="logging.to_file",
        description="Write log files; disable for read-only-root containers.",
    )
    log_level: str = onyx_field(
        default="info",
        toml="logging.level",
        description="Log level: notset, debug, info, notice, warning, error, "
        "or critical.",
    )
    log_third_party_debug: LegacyEnvBool = onyx_field(
        default=False,
        toml="logging.third_party_debug",
        description="Let chatty third-party libraries log at LOG_LEVEL instead "
        "of being capped at INFO.",
    )
    log_format: str = onyx_field(
        default="plain",
        toml="logging.format",
        description='Log output format: "plain" or "json".',
    )

    # --- embedding ---
    api_based_embedding_timeout: int = onyx_field(
        default=600,
        toml="embedding.api_timeout",
        description="Timeout in seconds for API-based embedding models.",
    )
    openai_embedding_timeout: int = onyx_field(
        default_factory=lambda data: data["api_based_embedding_timeout"],
        toml="embedding.openai_timeout",
        description="Timeout in seconds for OpenAI embedding calls; defaults "
        "to the API-based embedding timeout.",
    )
    vertexai_embedding_local_batch_size: int = onyx_field(
        default=50,
        toml="embedding.vertexai_local_batch_size",
        description="Local batch size for VertexAI embedding models.",
    )
    strict_chunk_token_limit: LegacyEnvBool = onyx_field(
        default=False,
        toml="embedding.strict_chunk_token_limit",
        description="Strictly enforce the token limit when chunking.",
    )

    # --- sentry ---
    sentry_dsn: str | None = onyx_field(
        default=None,
        toml="sentry.dsn",
        description="Sentry DSN for error reporting.",
        secret=True,
        # Legacy was a bare os.environ.get, so blank stayed "" rather than
        # becoming None. Both are falsy, but keeping "" makes the migration
        # byte-identical instead of merely equivalent.
        blank_is_falsy=True,
    )
    sentry_traces_sample_rate: float = onyx_field(
        default=0.01,
        toml="sentry.traces_sample_rate",
        description="Sentry trace sample rate for web and API requests.",
    )
    sentry_celery_traces_sample_rate: float = onyx_field(
        default=0.0,
        toml="sentry.celery_traces_sample_rate",
        description="Sentry trace sample rate for Celery tasks.",
    )

    # --- CORS ---
    # Raw comma-separated origin list. Parsing and validation stay in the
    # facade's parse_cors_allowed_origins, which treats empty as "allow all".
    cors_allowed_origin: str = onyx_field(
        default="",
        toml="cors.allowed_origins",
        description="Comma-separated allowed CORS origins; empty allows all.",
    )

    # --- multi-tenancy ---
    multi_tenant: LegacyEnvBool = onyx_field(
        default=False,
        toml="tenancy.multi_tenant",
        description="Run in multi-tenant (cloud) mode.",
    )
    postgres_default_schema: str = onyx_field(
        default="public",
        toml="tenancy.postgres_default_schema",
        description="Default Postgres schema for single-tenant deployments.",
    )
    default_redis_prefix: str = onyx_field(
        default="default",
        toml="tenancy.default_redis_prefix",
        description="Redis key prefix for the default tenant.",
    )
    # Both stay raw strings: the facade splits them into the *_TENANT_LIST
    # exports. blank_is_falsy keeps a blank as "" rather than None, matching
    # the legacy bare os.environ.get exactly.
    disallowed_slack_bot_tenant_ids: str | None = onyx_field(
        default=None,
        toml="tenancy.disallowed_slack_bot_tenant_ids",
        description="Comma-separated tenant ids excluded from the Slack bot.",
        blank_is_falsy=True,
    )
    ignored_syncing_tenant_ids: str | None = onyx_field(
        default=None,
        toml="tenancy.ignored_syncing_tenant_ids",
        description="Comma-separated tenant ids excluded from syncing.",
        blank_is_falsy=True,
    )

    # --- usage limits (cloud; off by default for self-hosted) ---
    usage_limits_enabled: LegacyEnvBool = onyx_field(
        # Enabled on cloud, disabled for self-hosted, unless set explicitly.
        default_factory=lambda data: data["multi_tenant"],
        toml="usage_limits.enabled",
        description="Enforce usage limits; defaults to the multi-tenant flag.",
        # Legacy branched on `is not None`, so a blank value read as False
        # rather than falling back to the multi_tenant default.
        blank_is_falsy=True,
    )
    usage_limit_window_seconds: int = onyx_field(
        default=604_800,
        toml="usage_limits.window_seconds",
        description="Usage limit window in seconds; default is one week.",
    )
    usage_limit_llm_cost_cents_trial: int = onyx_field(
        default=3200,
        toml="usage_limits.llm_cost_cents_trial",
        description="Per-window LLM cost limit in cents for trial users.",
    )
    usage_limit_llm_cost_cents_paid: int = onyx_field(
        default=6400,
        toml="usage_limits.llm_cost_cents_paid",
        description="Per-window LLM cost limit in cents for paid users.",
    )
    usage_limit_chunks_indexed_trial: int = onyx_field(
        default=400_000,
        toml="usage_limits.chunks_indexed_trial",
        description="Per-window chunks-indexed limit for trial users.",
    )
    usage_limit_chunks_indexed_paid: int = onyx_field(
        default=4_000_000,
        toml="usage_limits.chunks_indexed_paid",
        description="Per-window chunks-indexed limit for paid users.",
    )
    usage_limit_api_calls_trial: int = onyx_field(
        default=0,
        toml="usage_limits.api_calls_trial",
        description="Per-window API-key or PAT call limit for trial users.",
    )
    usage_limit_api_calls_paid: int = onyx_field(
        default=40_000,
        toml="usage_limits.api_calls_paid",
        description="Per-window API-key or PAT call limit for paid users.",
    )
    usage_limit_non_streaming_calls_trial: int = onyx_field(
        default=0,
        toml="usage_limits.non_streaming_calls_trial",
        description="Per-window non-streaming API call limit for trial users.",
    )
    usage_limit_non_streaming_calls_paid: int = onyx_field(
        default=160,
        toml="usage_limits.non_streaming_calls_paid",
        description="Per-window non-streaming API call limit for paid users.",
    )

    @model_validator(mode="after")
    def _normalize(self) -> "SharedSettings":
        self.log_format = self.log_format.lower()
        # Disabling the model server overrides every host to the sentinel so
        # downstream clients skip it.
        if self.disable_model_server:
            self.model_server_host = MODEL_SERVER_DISABLED_HOST
            self.model_server_allowed_host = MODEL_SERVER_DISABLED_HOST
            self.indexing_model_server_host = MODEL_SERVER_DISABLED_HOST
        return self
