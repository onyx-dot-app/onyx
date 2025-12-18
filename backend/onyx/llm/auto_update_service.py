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
from onyx.llm.auto_update_models import GitHubLLMConfig
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Cache to avoid re-processing unchanged configs
_last_updated_at: datetime | None = None


def fetch_github_config() -> GitHubLLMConfig | None:
    """Fetch LLM configuration from GitHub.

    Returns:
        GitHubLLMConfig if successful, None on error.
    """
    if not AUTO_LLM_CONFIG_URL:
        logger.debug("AUTO_LLM_CONFIG_URL not configured, skipping fetch")
        return None

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(AUTO_LLM_CONFIG_URL)
            response.raise_for_status()

            data = response.json()
            return GitHubLLMConfig.model_validate(data)
    except httpx.HTTPError as e:
        logger.warning(f"Failed to fetch LLM config from GitHub: {e}")
        return None
    except Exception as e:
        logger.error(f"Error parsing LLM config: {e}")
        return None


def sync_llm_models_from_github(
    db_session: Session,
    config: GitHubLLMConfig,
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
    global _last_updated_at

    # Skip if we've already processed this version (unless forced)
    if not force and _last_updated_at and config.updated_at <= _last_updated_at:
        logger.debug("GitHub config unchanged, skipping sync")
        return {}

    results: dict[str, int] = {}

    # Get all providers in Auto mode
    auto_providers = fetch_auto_mode_providers(db_session)

    if not auto_providers:
        logger.debug("No providers in Auto mode found")
        _last_updated_at = config.updated_at
        return {}

    for provider in auto_providers:
        provider_type = provider.provider  # e.g., "openai", "anthropic"

        if provider_type not in config.providers:
            logger.debug(
                f"No config for provider type '{provider_type}' in GitHub config"
            )
            continue

        github_provider_config = config.providers[provider_type]

        # Sync models - this replaces the model list entirely for Auto mode
        changes = sync_auto_mode_models(
            db_session=db_session,
            provider=provider,
            github_config=github_provider_config,
        )

        if changes > 0:
            results[provider.name] = changes
            logger.info(
                f"Applied {changes} model changes to provider '{provider.name}'"
            )

    _last_updated_at = config.updated_at
    return results


def reset_cache() -> None:
    """Reset the cache timestamp. Useful for testing."""
    global _last_updated_at
    _last_updated_at = None
