"""Service for fetching and syncing LLM model configurations from GitHub.

This service manages Auto mode LLM providers, where models and configuration
are managed centrally via a GitHub-hosted JSON file. In Auto mode:
- Model list is controlled by GitHub config
- Model visibility is controlled by GitHub config
- Default model is controlled by GitHub config
- Admin only needs to provide API credentials
"""

from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.configs.app_configs import AUTO_LLM_CONFIG_URL
from onyx.db.llm import fetch_auto_mode_providers
from onyx.db.llm import sync_auto_mode_models
from onyx.db.models import LLMProvider as LLMProviderModel
from onyx.llm.well_known_providers.auto_update_models import LLMRecommendations
from onyx.utils.logger import setup_logger

logger = setup_logger()

_CACHE_KEY_LAST_UPDATED_AT = "auto_llm_update:last_updated_at"
_CACHE_TTL_SECONDS = 60 * 60 * 24  # 24 hours


def get_cached_last_updated_at(
    cache_backend: CacheBackend | None = None,
) -> datetime | None:
    try:
        backend = cache_backend or get_cache_backend()
        cached_value = backend.get(_CACHE_KEY_LAST_UPDATED_AT)
        if cached_value is not None:
            value = (
                cached_value.decode("utf-8")
                if isinstance(cached_value, bytes)
                else cached_value
            )
            return datetime.fromisoformat(value)
    except Exception as e:
        logger.warning(f"Failed to get cached last_updated_at: {e}")
    return None


def set_cached_last_updated_at(
    updated_at: datetime,
    cache_backend: CacheBackend | None = None,
) -> None:
    try:
        backend = cache_backend or get_cache_backend()
        backend.set(
            _CACHE_KEY_LAST_UPDATED_AT,
            updated_at.isoformat(),
            ex=_CACHE_TTL_SECONDS,
        )
    except Exception as e:
        logger.warning(f"Failed to set cached last_updated_at: {e}")


def fetch_llm_recommendations_from_github(
    timeout: float = 30.0,
    *,
    raise_on_error: bool = False,
) -> LLMRecommendations | None:
    """Fetch LLM configuration from GitHub.

    Args:
        timeout: HTTP timeout in seconds.
        raise_on_error: If True, re-raise fetch/parse failures instead of
            logging and returning None.

    Returns:
        GitHubLLMConfig if successful, None on error.
    """
    if not AUTO_LLM_CONFIG_URL:
        logger.debug("AUTO_LLM_CONFIG_URL not configured, skipping fetch")
        return None

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(AUTO_LLM_CONFIG_URL)
            response.raise_for_status()

            data = response.json()
            return LLMRecommendations.model_validate(data)
    except httpx.HTTPError as e:
        if raise_on_error:
            raise
        logger.error(f"Failed to fetch LLM config from GitHub: {e}")
        return None
    except Exception as e:
        if raise_on_error:
            raise
        logger.error(f"Error parsing LLM config: {e}")
        return None


def sync_llm_models_from_github(
    db_session: Session,
    force: bool = False,
    cache_backend: CacheBackend | None = None,
) -> dict[str, int]:
    """Sync models from GitHub config to database for all Auto mode providers.

    In Auto mode, EVERYTHING is controlled by GitHub config:
    - Model list
    - Model visibility (is_visible)
    - Default model
    - Fast default model

    Args:
        db_session: Database session
        force: If True, skip the updated_at check and force sync
        cache_backend: Optional cache backend override; defaults to the
            per-tenant backend returned by get_cache_backend().

    Returns:
        Dict of provider_name -> number of changes made.
    """
    auto_providers = fetch_auto_mode_providers(db_session)
    if not auto_providers:
        logger.debug("No providers in Auto mode found")
        return {}

    # Fetch config from GitHub
    config = fetch_llm_recommendations_from_github()
    if not config:
        logger.warning("Failed to fetch GitHub config")
        return {}

    return sync_llm_models(
        db_session=db_session,
        config=config,
        force=force,
        cache_backend=cache_backend,
        auto_providers=auto_providers,
    )


def sync_llm_models(
    db_session: Session,
    config: LLMRecommendations,
    force: bool = False,
    cache_backend: CacheBackend | None = None,
    auto_providers: list[LLMProviderModel] | None = None,
) -> dict[str, int]:
    """Sync a pre-fetched LLM config to Auto mode providers for one tenant.

    Args:
        db_session: Database session for the current tenant.
        config: The already-fetched recommendations to apply.
        force: If True, bypass the updated_at idempotency check.
        cache_backend: Optional cache backend override for the updated_at key.
        auto_providers: Pre-fetched Auto mode providers to avoid an extra DB
            query. If None, they are fetched from the database.

    Returns:
        Dict of provider name to number of model changes applied.
    """
    results: dict[str, int] = {}

    # Get all providers in Auto mode
    if auto_providers is None:
        auto_providers = fetch_auto_mode_providers(db_session)
    if not auto_providers:
        logger.debug("No providers in Auto mode found")
        return {}

    # Skip if we've already processed this version (unless forced)
    last_updated_at = get_cached_last_updated_at(cache_backend=cache_backend)
    if not force and last_updated_at and config.updated_at <= last_updated_at:
        logger.debug("GitHub config unchanged, skipping sync")
        set_cached_last_updated_at(last_updated_at, cache_backend=cache_backend)
        return {}

    for provider in auto_providers:
        provider_type = provider.provider  # e.g., "openai", "anthropic"

        if provider_type not in config.providers:
            logger.debug(
                f"No config for provider type '{provider_type}' in GitHub config"
            )
            continue

        # Sync models - this replaces the model list entirely for Auto mode
        changes = sync_auto_mode_models(
            db_session=db_session,
            provider=provider,
            llm_recommendations=config,
        )

        if changes > 0:
            results[provider.name] = changes
            logger.info(
                f"Applied {changes} model changes to provider '{provider.name}'"
            )

    set_cached_last_updated_at(config.updated_at, cache_backend=cache_backend)
    return results


def reset_cache() -> None:
    """Reset the cache timestamp. Useful for testing."""
    try:
        get_cache_backend().delete(_CACHE_KEY_LAST_UPDATED_AT)
    except Exception as e:
        logger.warning(f"Failed to reset cache: {e}")
