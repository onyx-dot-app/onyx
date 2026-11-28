"""Auto-update for LLM providers from model labs.

A provider with auto-update on gets the models its lab releases after setup,
and loses the models the lab retires. The admin's selection and the global
defaults are never changed. See ``AUTO_UPDATE_PROVIDERS``.
"""

import httpx
from sqlalchemy.orm import Session

from onyx.configs.app_configs import AUTO_LLM_CONFIG_URL
from onyx.db.enums import LLMModelFlowType
from onyx.db.llm import (
    fetch_auto_mode_providers,
    fetch_default_model,
    set_model_visibility,
    sync_auto_mode_models,
    update_default_model,
)
from onyx.db.models import LLMProvider
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.llm.constants import AUTO_UPDATE_PROVIDERS
from onyx.llm.playground_models import (
    is_offered_on_playground,
    playground_default_model,
)
from onyx.llm.well_known_providers.auto_update_models import LLMRecommendations
from onyx.utils.logger import setup_logger
from shared_configs.configs import IS_PLAYGROUND, ONYX_AIRGAPPED

logger = setup_logger()

_SEEN_CATALOG_KEY_PREFIX = "llm_auto_update_seen_models_"


def _seen_catalog_key(provider_id: int) -> str:
    return f"{_SEEN_CATALOG_KEY_PREFIX}{provider_id}"


def reset_seen_catalog(provider_id: int) -> None:
    """Make the next sync record a new baseline instead of applying the
    releases since auto-update was last on."""
    try:
        get_kv_store().delete(_seen_catalog_key(provider_id))
    except KvKeyNotFoundError:
        pass


def _load_seen_catalog(provider: LLMProvider) -> set[str] | None:
    try:
        seen = get_kv_store().load(_seen_catalog_key(provider.id), refresh_cache=True)
    except KvKeyNotFoundError:
        return None
    if not isinstance(seen, list) or not all(isinstance(name, str) for name in seen):
        raise ValueError(f"Invalid seen catalog for provider {provider.id}")
    return {name for name in seen if isinstance(name, str)}


def fetch_llm_recommendations_from_github(
    timeout: float = 30.0,
) -> LLMRecommendations | None:
    """Fetch the recommended models from GitHub. Returns None on error."""
    if ONYX_AIRGAPPED:
        logger.debug("ONYX_AIRGAPPED set, skipping LLM config fetch")
        return None
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


def sync_auto_update_providers(db_session: Session) -> dict[str, int]:
    """Sync every auto-update provider with its lab's model catalog.

    Returns a dict of provider id -> number of changes made.
    """
    from onyx.llm.well_known_providers.llm_provider_options import (
        fetch_latest_models_for_provider,
        get_recommendations,
    )

    providers = [
        provider
        for provider in fetch_auto_mode_providers(db_session)
        if provider.provider in AUTO_UPDATE_PROVIDERS
    ]
    if not providers:
        return {}

    recommendations = get_recommendations()
    results: dict[str, int] = {}
    for provider in providers:
        changes = _sync_catalog(
            db_session,
            provider,
            recommendations,
            fetch_latest_models_for_provider(provider.provider),
        )
        if IS_PLAYGROUND:
            changes += _apply_playground_rule(db_session, provider, recommendations)
        if changes:
            results[str(provider.id)] = changes
            logger.info(
                "Applied %s model changes to provider '%s'",
                changes,
                provider.name or provider.provider,
            )
    return results


def _sync_catalog(
    db_session: Session,
    provider: LLMProvider,
    recommendations: LLMRecommendations,
    catalog: list[str] | None,
) -> int:
    """Add the models the lab released since the last sync and remove the ones
    it retired. Returns the number of changes."""
    if catalog is None:
        return 0
    try:
        seen = _load_seen_catalog(provider)
    except ValueError:
        # Keep the stored value for inspection; never overwrite it.
        logger.exception("Skipping auto-update for provider %s", provider.id)
        return 0
    kv_store = get_kv_store()
    # The first sync records the catalog the admin set up against.
    if seen is None:
        kv_store.store(_seen_catalog_key(provider.id), catalog)
        return 0

    display_names = {
        model.name: model.display_name
        for model in recommendations.get_visible_models(provider.provider)
        if model.display_name
    }
    changes = sync_auto_mode_models(
        db_session=db_session,
        provider=provider,
        released_model_names=[name for name in catalog if name not in seen],
        retired_model_names=seen - set(catalog),
        display_names=display_names,
    )
    kv_store.store(_seen_catalog_key(provider.id), catalog)
    return changes


def _apply_playground_rule(
    db_session: Session,
    provider: LLMProvider,
    recommendations: LLMRecommendations,
) -> int:
    """On the playground, show exactly the models the price rule offers. The
    rule owns visibility there, since playground admins cannot change models.
    Rechecked on every sync, so a model hidden on release appears once the
    recommended list includes it, and a model that stops qualifying is hidden.

    If the tenant's chat default is on this provider and no longer offered, it
    is first replaced by the provider's playground default, so chat keeps
    working. The old model is then hidden like any other unoffered model.
    Returns the number of changes."""
    offered = {
        model.name
        for model in provider.model_configurations
        if is_offered_on_playground(provider.provider, model.name, recommendations)
    }
    changes = 0
    chat_default = fetch_default_model(db_session, LLMModelFlowType.CHAT)
    if (
        chat_default is not None
        and chat_default.llm_provider_id == provider.id
        and chat_default.name not in offered
    ):
        replacement = playground_default_model(
            provider.provider, recommendations, offered
        )
        if replacement is not None and replacement in offered:
            update_default_model(
                db_session=db_session,
                provider_id=provider.id,
                model=replacement,
                flow_type=LLMModelFlowType.CHAT,
            )
            changes += 1
        else:
            logger.error(
                "Chat default %s is not offered on the playground and provider "
                "'%s' has no replacement",
                chat_default.name,
                provider.name or provider.provider,
            )
    return changes + set_model_visibility(db_session, provider, offered)
