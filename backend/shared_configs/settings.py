"""Typed schema for the config surface shared across the backend and the
model server (facade: shared_configs/configs.py).

Must stay importable by ``model_server``: stdlib + pydantic only, never
``onyx.*``.
"""

from pydantic import AliasChoices, Field, model_validator

from shared_configs.settings_base import (
    LegacyEnvBool,
    LegacyEnvBoolUnlessFalse,
    OnyxBaseSettings,
)


class SharedSettings(OnyxBaseSettings):
    # Model server
    skip_warm_up: LegacyEnvBool = Field(
        default=True,
        json_schema_extra={"toml_path": "model_server.skip_warm_up"},
        description="Skip ML model warmup at startup.",
    )
    disable_model_server: LegacyEnvBool = Field(
        default=False,
        json_schema_extra={"toml_path": "model_server.disable"},
        description="Disable the model server entirely (hosts become 'disabled').",
    )
    model_server_host: str = Field(
        default="localhost",
        json_schema_extra={"toml_path": "model_server.host"},
        description="Hostname of the inference model server.",
    )
    model_server_allowed_host: str = Field(
        # Legacy env reads MODEL_SERVER_HOST for this too (with a different
        # default); an explicit MODEL_SERVER_ALLOWED_HOST wins over it.
        default="0.0.0.0",  # noqa: S104 — intentional bind-address default for containers
        validation_alias=AliasChoices("MODEL_SERVER_ALLOWED_HOST", "MODEL_SERVER_HOST"),
        json_schema_extra={"toml_path": "model_server.allowed_host"},
        description="Host/interface the model server binds to.",
    )
    indexing_model_server_host: str = Field(
        # data-aware default: inherits model_server_host when unset.
        default_factory=lambda data: data["model_server_host"],
        json_schema_extra={"toml_path": "model_server.indexing_host"},
        description="Hostname of the dedicated indexing model server "
        "(defaults to the inference model server host).",
    )
    model_server_port: int = Field(
        default=9000,
        json_schema_extra={"toml_path": "model_server.port"},
        description="Port of the inference model server.",
    )
    indexing_model_server_port: int = Field(
        default_factory=lambda data: data["model_server_port"],
        json_schema_extra={"toml_path": "model_server.indexing_port"},
        description="Port of the dedicated indexing model server "
        "(defaults to the inference model server port).",
    )
    min_threads_ml_models: int = Field(
        default=1,
        json_schema_extra={"toml_path": "model_server.min_threads_ml_models"},
        description="Minimum number of torch threads for embedding models.",
    )
    indexing_only: LegacyEnvBool = Field(
        default=False,
        json_schema_extra={"toml_path": "model_server.indexing_only"},
        description="Model server serves indexing requests only.",
    )
    model_server_connect_timeout: int = Field(
        default=30,
        json_schema_extra={"toml_path": "model_server.connect_timeout"},
        description="Connect timeout (s) for requests to the model server.",
    )
    model_server_read_timeout: int = Field(
        default=600,
        json_schema_extra={"toml_path": "model_server.read_timeout"},
        description="Read timeout (s) for requests to the model server.",
    )

    # Reranking
    default_cross_encoder_model_name: str | None = Field(
        default=None,
        json_schema_extra={"toml_path": "rerank.default_model_name"},
        description="Default cross-encoder model for automatic deployments.",
    )
    default_cross_encoder_api_key: str | None = Field(
        default=None,
        json_schema_extra={"toml_path": "rerank.default_api_key", "secret": True},
        description="API key for the default cross-encoder provider.",
    )
    default_cross_encoder_provider_type: str | None = Field(
        default=None,
        json_schema_extra={"toml_path": "rerank.default_provider_type"},
        description="Provider type for the default cross-encoder.",
    )
    disable_rerank_for_streaming: LegacyEnvBool = Field(
        default=False,
        json_schema_extra={"toml_path": "rerank.disable_for_streaming"},
        description="Skip reranking in streaming flows.",
    )

    # Logging
    log_file_name: str = Field(
        default="onyx",
        json_schema_extra={"toml_path": "logging.file_name"},
        description="Base filename (no extension/path) for log files.",
    )
    dev_logging_enabled: LegacyEnvBool = Field(
        default=False,
        json_schema_extra={"toml_path": "logging.dev_logging_enabled"},
        description="Generate persistent log files for local dev environments.",
    )
    log_to_file: LegacyEnvBoolUnlessFalse = Field(
        default=True,
        json_schema_extra={"toml_path": "logging.to_file"},
        description="Write log files (disable for read-only-root containers).",
    )
    log_level: str = Field(
        default="info",
        json_schema_extra={"toml_path": "logging.level"},
        description="Log level: notset, debug, info, notice, warning, error, critical.",
    )
    log_format: str = Field(
        default="plain",
        json_schema_extra={"toml_path": "logging.format"},
        description='Log output format: "plain" or "json".',
    )

    # Embedding
    api_based_embedding_timeout: int = Field(
        default=600,
        json_schema_extra={"toml_path": "embedding.api_timeout"},
        description="Timeout (s) for API-based embedding models.",
    )
    openai_embedding_timeout: int = Field(
        default_factory=lambda data: data["api_based_embedding_timeout"],
        json_schema_extra={"toml_path": "embedding.openai_timeout"},
        description="Timeout (s) for OpenAI embedding calls "
        "(defaults to the API-based embedding timeout).",
    )
    vertexai_embedding_local_batch_size: int = Field(
        default=50,
        json_schema_extra={"toml_path": "embedding.vertexai_local_batch_size"},
        description="Local batch size for VertexAI embedding models.",
    )
    strict_chunk_token_limit: LegacyEnvBool = Field(
        default=False,
        json_schema_extra={"toml_path": "embedding.strict_chunk_token_limit"},
        description="Strictly enforce the token limit when chunking.",
    )

    # Sentry
    sentry_dsn: str | None = Field(
        default=None,
        json_schema_extra={"toml_path": "sentry.dsn", "secret": True},
        description="Sentry DSN for error reporting.",
    )
    sentry_traces_sample_rate: float = Field(
        default=0.01,
        json_schema_extra={"toml_path": "sentry.traces_sample_rate"},
        description="Sentry trace sample rate for web/API requests.",
    )
    sentry_celery_traces_sample_rate: float = Field(
        default=0.0,
        json_schema_extra={"toml_path": "sentry.celery_traces_sample_rate"},
        description="Sentry trace sample rate for Celery tasks.",
    )

    # CORS — raw comma-separated origin list; parsing/validation stays in the
    # facade's parse_cors_allowed_origins (empty means allow all origins).
    cors_allowed_origin: str = Field(
        default="",
        json_schema_extra={"toml_path": "cors.allowed_origins"},
        description="Comma-separated allowed CORS origins; empty allows all.",
    )

    # Multi-tenancy
    multi_tenant: LegacyEnvBool = Field(
        default=False,
        json_schema_extra={"toml_path": "tenancy.multi_tenant"},
        description="Run in multi-tenant (cloud) mode.",
    )
    postgres_default_schema: str = Field(
        default="public",
        json_schema_extra={"toml_path": "tenancy.postgres_default_schema"},
        description="Default Postgres schema (single-tenant).",
    )
    default_redis_prefix: str = Field(
        default="default",
        json_schema_extra={"toml_path": "tenancy.default_redis_prefix"},
        description="Redis key prefix for the default tenant.",
    )
    disallowed_slack_bot_tenant_ids: str | None = Field(
        default=None,
        json_schema_extra={"toml_path": "tenancy.disallowed_slack_bot_tenant_ids"},
        description="Comma-separated tenant ids excluded from the Slack bot.",
    )
    ignored_syncing_tenant_ids: str | None = Field(
        default=None,
        json_schema_extra={"toml_path": "tenancy.ignored_syncing_tenant_ids"},
        description="Comma-separated tenant ids excluded from syncing.",
    )

    environment: str = Field(
        default="not_explicitly_set",
        json_schema_extra={"toml_path": "environment"},
        description="Deployment environment label.",
    )

    # Usage limits (cloud; off by default for self-hosted). The enabled flag
    # defaults to multi_tenant when not explicitly set — see the property.
    usage_limits_enabled_override: LegacyEnvBool | None = Field(
        default=None,
        validation_alias=AliasChoices("USAGE_LIMITS_ENABLED"),
        json_schema_extra={"toml_path": "usage_limits.enabled"},
        description="Enforce usage limits (defaults to the multi-tenant flag).",
    )
    usage_limit_window_seconds: int = Field(
        default=604_800,
        json_schema_extra={"toml_path": "usage_limits.window_seconds"},
        description="Usage limit window in seconds (default one week).",
    )
    usage_limit_llm_cost_cents_trial: int = Field(
        default=3200,
        json_schema_extra={"toml_path": "usage_limits.llm_cost_cents_trial"},
        description="Per-window LLM cost limit (cents) for trial users.",
    )
    usage_limit_llm_cost_cents_paid: int = Field(
        default=6400,
        json_schema_extra={"toml_path": "usage_limits.llm_cost_cents_paid"},
        description="Per-window LLM cost limit (cents) for paid users.",
    )
    usage_limit_chunks_indexed_trial: int = Field(
        default=400_000,
        json_schema_extra={"toml_path": "usage_limits.chunks_indexed_trial"},
        description="Per-window chunks-indexed limit for trial users.",
    )
    usage_limit_chunks_indexed_paid: int = Field(
        default=4_000_000,
        json_schema_extra={"toml_path": "usage_limits.chunks_indexed_paid"},
        description="Per-window chunks-indexed limit for paid users.",
    )
    usage_limit_api_calls_trial: int = Field(
        default=0,
        json_schema_extra={"toml_path": "usage_limits.api_calls_trial"},
        description="Per-window API-key/PAT call limit for trial users.",
    )
    usage_limit_api_calls_paid: int = Field(
        default=40_000,
        json_schema_extra={"toml_path": "usage_limits.api_calls_paid"},
        description="Per-window API-key/PAT call limit for paid users.",
    )
    usage_limit_non_streaming_calls_trial: int = Field(
        default=0,
        json_schema_extra={"toml_path": "usage_limits.non_streaming_calls_trial"},
        description="Per-window non-streaming API call limit for trial users.",
    )
    usage_limit_non_streaming_calls_paid: int = Field(
        default=160,
        json_schema_extra={"toml_path": "usage_limits.non_streaming_calls_paid"},
        description="Per-window non-streaming API call limit for paid users.",
    )

    @model_validator(mode="after")
    def _normalize(self) -> "SharedSettings":
        self.log_format = self.log_format.lower()
        # Disabling the model server overrides every host to the "disabled"
        # sentinel so downstream clients skip it.
        if self.disable_model_server:
            self.model_server_host = "disabled"
            self.model_server_allowed_host = "disabled"
            self.indexing_model_server_host = "disabled"
        return self

    @property
    def usage_limits_enabled(self) -> bool:
        if self.usage_limits_enabled_override is not None:
            return self.usage_limits_enabled_override
        # Default: enabled on cloud (multi-tenant), disabled for self-hosted.
        return self.multi_tenant
