"""Resolve the effective tracing-provider config: a DB row (if present) wins per
provider, else env-var fallback. Env-only under MULTI_TENANT (UI config is
unsupported on cloud)."""

from __future__ import annotations

from dataclasses import dataclass

from onyx.configs.app_configs import BRAINTRUST_API_KEY
from onyx.configs.app_configs import BRAINTRUST_API_URL
from onyx.configs.app_configs import BRAINTRUST_PROJECT
from onyx.configs.app_configs import LANGFUSE_HOST
from onyx.configs.app_configs import LANGFUSE_PUBLIC_KEY
from onyx.configs.app_configs import LANGFUSE_SECRET_KEY
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import TracingProviderConfig
from onyx.db.tracing import fetch_all_tracing_providers
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.enums import TracingProviderType

logger = setup_logger()


@dataclass(frozen=True)
class BraintrustConfig:
    api_key: str
    project: str
    # Optional custom API URL for self-hosted / non-default Braintrust deployments.
    api_url: str | None = None


@dataclass(frozen=True)
class LangfuseConfig:
    secret_key: str
    public_key: str
    host: str | None


@dataclass(frozen=True)
class EffectiveTracingConfig:
    braintrust: BraintrustConfig | None = None
    langfuse: LangfuseConfig | None = None

    def active_provider_names(self) -> list[str]:
        names: list[str] = []
        if self.braintrust:
            names.append(TracingProviderType.BRAINTRUST.value)
        if self.langfuse:
            names.append(TracingProviderType.LANGFUSE.value)
        return names

    def fingerprint(self) -> tuple[object, object]:
        """A hashable identity used to detect config changes (in-memory only)."""
        braintrust_fp = (
            (
                self.braintrust.api_key,
                self.braintrust.project,
                self.braintrust.api_url,
            )
            if self.braintrust
            else None
        )
        langfuse_fp = (
            (self.langfuse.secret_key, self.langfuse.public_key, self.langfuse.host)
            if self.langfuse
            else None
        )
        return (braintrust_fp, langfuse_fp)


def _env_braintrust() -> BraintrustConfig | None:
    if BRAINTRUST_API_KEY:
        return BraintrustConfig(
            api_key=BRAINTRUST_API_KEY,
            project=BRAINTRUST_PROJECT,
            api_url=BRAINTRUST_API_URL or None,
        )
    return None


def _env_langfuse() -> LangfuseConfig | None:
    if LANGFUSE_SECRET_KEY and LANGFUSE_PUBLIC_KEY:
        return LangfuseConfig(
            secret_key=LANGFUSE_SECRET_KEY,
            public_key=LANGFUSE_PUBLIC_KEY,
            host=LANGFUSE_HOST or None,
        )
    return None


def _braintrust_from_row(row: TracingProviderConfig) -> BraintrustConfig | None:
    if not row.enabled:
        return None
    api_key = row.api_key.get_value(apply_mask=False) if row.api_key else None
    if not api_key:
        return None
    config = row.config or {}
    return BraintrustConfig(
        api_key=api_key,
        project=config.get("project") or BRAINTRUST_PROJECT,
        api_url=config.get("api_url") or BRAINTRUST_API_URL or None,
    )


def _langfuse_from_row(row: TracingProviderConfig) -> LangfuseConfig | None:
    if not row.enabled:
        return None
    secret_key = row.api_key.get_value(apply_mask=False) if row.api_key else None
    config = row.config or {}
    public_key = config.get("public_key")
    if not secret_key or not public_key:
        return None
    return LangfuseConfig(
        secret_key=secret_key,
        public_key=public_key,
        host=config.get("host") or None,
    )


def resolve_effective_tracing_config() -> EffectiveTracingConfig:
    # In multi-tenant (cloud) the UI feature is unsupported — env vars only.
    if MULTI_TENANT:
        return EffectiveTracingConfig(
            braintrust=_env_braintrust(), langfuse=_env_langfuse()
        )

    braintrust = _env_braintrust()
    langfuse = _env_langfuse()
    try:
        with get_session_with_current_tenant() as db_session:
            for row in fetch_all_tracing_providers(db_session):
                if row.provider_type == TracingProviderType.BRAINTRUST.value:
                    braintrust = _braintrust_from_row(row)
                elif row.provider_type == TracingProviderType.LANGFUSE.value:
                    langfuse = _langfuse_from_row(row)
    except Exception as e:
        logger.warning(
            "Failed to read tracing config from DB; falling back to env vars: %s", e
        )

    return EffectiveTracingConfig(braintrust=braintrust, langfuse=langfuse)
