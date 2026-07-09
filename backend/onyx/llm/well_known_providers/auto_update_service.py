"""Service for fetching and syncing LLM model configurations from GitHub.

This service manages Auto mode LLM providers, where models and configuration
are managed centrally via a GitHub-hosted JSON file. In Auto mode:
- The GitHub config decides which models are offered: new recommendations
  are added visible, models dropped from the config are hidden
- Admin choices win within that list: deselected models stay hidden, and
  models currently set as a default (chat, vision, ...) always stay visible
- The admin-chosen default model is never changed by a sync
- Admin only needs to provide API credentials
"""

import json
import pathlib
from datetime import datetime
from datetime import timezone

import httpx
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.configs.app_configs import AUTO_LLM_CONFIG_URL
from onyx.db.llm import fetch_auto_mode_providers
from onyx.db.llm import sync_auto_mode_models
from onyx.llm.well_known_providers.auto_update_models import LLMRecommendations
from onyx.utils.logger import setup_logger

logger = setup_logger()

_CACHE_KEY_LAST_UPDATED_AT = "auto_llm_update:last_updated_at"
_CACHE_TTL_SECONDS = 60 * 60 * 24  # 24 hours


def _get_cached_last_updated_at() -> datetime | None:
    try:
        value = get_cache_backend().get(_CACHE_KEY_LAST_UPDATED_AT)
        if value is not None:
            return datetime.fromisoformat(value.decode("utf-8"))
    except Exception as e:
        logger.warning("Failed to get cached last_updated_at: %s", e)
    return None


def _set_cached_last_updated_at(updated_at: datetime) -> None:
    try:
        get_cache_backend().set(
            _CACHE_KEY_LAST_UPDATED_AT,
            updated_at.isoformat(),
            ex=_CACHE_TTL_SECONDS,
        )
    except Exception as e:
        logger.warning("Failed to set cached last_updated_at: %s", e)


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
        logger.error("Failed to fetch LLM config from GitHub: %s", e)
        return None
    except Exception as e:
        logger.error("Error parsing LLM config: %s", e)
        return None


def load_bundled_recommendations() -> LLMRecommendations | None:
    """Load the recommended-models.json copy shipped with this release."""
    json_path = pathlib.Path(__file__).parent / "recommended-models.json"
    try:
        with open(json_path, "r") as f:
            return LLMRecommendations.model_validate(json.load(f))
    except Exception as e:
        logger.error("Failed to load bundled LLM recommendations: %s", e)
        return None


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def fetch_llm_recommendations(
    timeout: float = 30.0,
) -> LLMRecommendations | None:
    """Resolve the LLM recommendations config.

    Uses whichever of the GitHub-hosted config and the bundled copy has the
    newer `updated_at`: GitHub can push recommendations to running
    deployments without a release, while a fresh release isn't held back by
    a stale (or unreachable) remote file — e.g. air-gapped deployments still
    get the recommendations shipped with their version.
    """
    remote = fetch_llm_recommendations_from_github(timeout=timeout)
    bundled = load_bundled_recommendations()

    if remote and bundled:
        return (
            remote
            if _as_utc(remote.updated_at) >= _as_utc(bundled.updated_at)
            else bundled
        )
    return remote or bundled


def sync_llm_models_from_github(
    db_session: Session,
    force: bool = False,
) -> dict[str, int]:
    """Sync models from GitHub config to database for all Auto mode providers.

    In Auto mode, GitHub config controls which models are offered (new
    recommendations added visible, dropped models hidden), while admin
    choices win within that list: deselected models stay hidden, models set
    as a default for some flow always stay visible, and the admin-chosen
    default model is never changed.

    Args:
        db_session: Database session
        config: GitHub LLM configuration
        force: If True, skip the updated_at check and force sync

    Returns:
        Dict of provider_name -> number of changes made.
    """
    results: dict[str, int] = {}

    # Get all providers in Auto mode
    auto_providers = fetch_auto_mode_providers(db_session)
    if not auto_providers:
        logger.debug("No providers in Auto mode found")
        return {}

    # Resolve config (GitHub-hosted or the newer bundled copy)
    config = fetch_llm_recommendations()
    if not config:
        logger.warning("Failed to resolve LLM recommendations config")
        return {}

    # Skip if we've already processed this version (unless forced)
    last_updated_at = _get_cached_last_updated_at()
    if not force and last_updated_at and config.updated_at <= last_updated_at:
        logger.debug("GitHub config unchanged, skipping sync")
        _set_cached_last_updated_at(config.updated_at)
        return {}

    for provider in auto_providers:
        provider_type = provider.provider  # e.g., "openai", "anthropic"

        if provider_type not in config.providers:
            logger.debug(
                "No config for provider type '%s' in GitHub config", provider_type
            )
            continue

        # Sync models - this replaces the model list entirely for Auto mode
        changes = sync_auto_mode_models(
            db_session=db_session,
            provider=provider,
            llm_recommendations=config,
        )

        if changes > 0:
            results[str(provider.id)] = changes
            logger.info(
                "Applied %s model changes to provider '%s'",
                changes,
                provider.name or provider.provider,
            )

    _set_cached_last_updated_at(config.updated_at)
    return results


def reset_cache() -> None:
    """Reset the cache timestamp. Useful for testing."""
    try:
        get_cache_backend().delete(_CACHE_KEY_LAST_UPDATED_AT)
    except Exception as e:
        logger.warning("Failed to reset cache: %s", e)
