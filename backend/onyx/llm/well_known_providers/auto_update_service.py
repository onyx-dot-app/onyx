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

from onyx.configs.app_configs import AUTO_LLM_CONFIG_URL
from onyx.db.llm import fetch_auto_mode_providers
from onyx.db.llm import sync_auto_mode_models
from onyx.llm.well_known_providers.auto_update_models import LLMRecommendations
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Redis key for caching the last updated timestamp (per-tenant)
_REDIS_KEY_LAST_UPDATED_AT = "auto_llm_update:last_updated_at"


def _get_cached_last_updated_at() -> datetime | None:
    """Get the cached last_updated_at timestamp from Redis."""
    try:
        redis_client = get_redis_client()
        value = redis_client.get(_REDIS_KEY_LAST_UPDATED_AT)
        if value and isinstance(value, bytes):
            # Value is bytes, decode to string then parse as ISO format
            return datetime.fromisoformat(value.decode("utf-8"))
    except Exception as e:
        logger.warning(f"Failed to get cached last_updated_at from Redis: {e}")
    return None


def _set_cached_last_updated_at(updated_at: datetime) -> None:
    """Set the cached last_updated_at timestamp in Redis."""
    try:
        redis_client = get_redis_client()
        # Store as ISO format string, with 24 hour expiration
        redis_client.set(
            _REDIS_KEY_LAST_UPDATED_AT,
            updated_at.isoformat(),
            ex=60 * 60 * 24,  # 24 hours
        )
    except Exception as e:
        logger.warning(f"Failed to set cached last_updated_at in Redis: {e}")


def fetch_llm_recommendations_from_github(
    timeout: float = 30.0,
) -> LLMRecommendations | None:
    """Fetch LLM configuration from GitHub.

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
        logger.error(f"Failed to fetch LLM config from GitHub: {e}")
        return None
    except Exception as e:
        logger.error(f"Error parsing LLM config: {e}")
        return None


def sync_llm_models_from_github(
    db_session: Session,
    config: LLMRecommendations,
    force: bool = False,
) -> dict[str, int]:
    """Sync models from GitHub config to database for all Auto mode providers.

    In Auto mode, EVERYTHING is controlled by GitHub config:
    - Model list
    - Model visibility (is_visible)
    - Default model
    - Fast default model

    Args:
        db_session: Database session
        config: GitHub LLM configuration
        force: If True, skip the updated_at check and force sync

    Returns:
        Dict of provider_name -> number of changes made.
    """
    # Skip if we've already processed this version (unless forced)
    last_updated_at = _get_cached_last_updated_at()
    if not force and last_updated_at and config.updated_at <= last_updated_at:
        logger.debug("GitHub config unchanged, skipping sync")
        return {}

    results: dict[str, int] = {}

    # Get all providers in Auto mode
    auto_providers = fetch_auto_mode_providers(db_session)

    if not auto_providers:
        logger.debug("No providers in Auto mode found")
        _set_cached_last_updated_at(config.updated_at)
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

    _set_cached_last_updated_at(config.updated_at)
    return results


def reset_cache() -> None:
    """Reset the cache timestamp in Redis. Useful for testing."""
    try:
        redis_client = get_redis_client()
        redis_client.delete(_REDIS_KEY_LAST_UPDATED_AT)
    except Exception as e:
        logger.warning(f"Failed to reset cache in Redis: {e}")
