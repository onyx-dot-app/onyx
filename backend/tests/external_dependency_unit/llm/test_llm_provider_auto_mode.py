"""Tests for LLM provider auto-update.

Auto-update adds models a lab releases and removes models it retires. It
never changes the admin's selection or the global defaults.
"""

from collections.abc import Generator
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import LLMModelFlowType
from onyx.db.llm import (
    fetch_default_model,
    fetch_existing_llm_provider,
    insert_new_model_configuration__no_commit,
    remove_llm_provider,
    sync_auto_mode_models,
    update_default_model,
    update_default_vision_provider,
)
from onyx.db.models import LLMProvider as LLMProviderModel
from onyx.llm.constants import LlmProviderNames
from onyx.llm.well_known_providers.auto_update_service import (
    reset_seen_catalog,
    sync_auto_update_providers,
)
from onyx.server.manage.llm.api import put_llm_provider
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    ModelConfigurationUpsertRequest,
)


def _cleanup_provider(db_session: Session, name: str) -> None:
    provider = fetch_existing_llm_provider(name=name, db_session=db_session)
    if provider:
        reset_seen_catalog(provider.id)
        remove_llm_provider(db_session, provider.id)


def _create_provider(
    db_session: Session,
    name: str,
    provider: str,
    is_auto_mode: bool,
    models: dict[str, bool],
) -> LLMProviderModel:
    put_llm_provider(
        llm_provider_upsert_request=LLMProviderUpsertRequest(
            name=name,
            provider=provider,
            api_key="sk-test-key-00000000000000000000000000000000000",
            api_key_changed=True,
            is_auto_mode=is_auto_mode,
            model_configurations=[
                ModelConfigurationUpsertRequest(name=model, is_visible=visible)
                for model, visible in models.items()
            ],
        ),
        is_creation=True,
        user=MagicMock(),
        db_session=db_session,
    )
    db_session.expire_all()
    created = fetch_existing_llm_provider(name=name, db_session=db_session)
    assert created is not None
    return created


def _flows(db_session: Session, name: str) -> dict[str, set[LLMModelFlowType]]:
    db_session.expire_all()
    provider = fetch_existing_llm_provider(name=name, db_session=db_session)
    assert provider is not None
    return {
        mc.name: set(mc.llm_model_flow_types) for mc in provider.model_configurations
    }


def _visibility(db_session: Session, name: str) -> dict[str, bool]:
    db_session.expire_all()
    provider = fetch_existing_llm_provider(name=name, db_session=db_session)
    assert provider is not None
    return {mc.name: mc.is_visible for mc in provider.model_configurations}


@pytest.fixture
def provider_name(db_session: Session) -> Generator[str, None, None]:
    name = f"test-auto-provider-{uuid4().hex[:8]}"
    yield name
    db_session.rollback()
    _cleanup_provider(db_session, name)


_CATALOG_PATH = "onyx.llm.well_known_providers.llm_provider_options.fetch_latest_models_for_provider"


def _sync_with_catalog(db_session: Session, catalog: list[str]) -> dict[str, int]:
    with patch(_CATALOG_PATH, return_value=catalog):
        return sync_auto_update_providers(db_session)


def test_sync_applies_releases_and_retirements_after_setup(
    db_session: Session, provider_name: str
) -> None:
    provider = _create_provider(
        db_session,
        provider_name,
        LlmProviderNames.OPENAI,
        is_auto_mode=True,
        models={"gpt-a": True, "gpt-b": False, "gpt-old": True, "my-finetune": True},
    )

    # The first sync only records the catalog the admin set up against.
    _sync_with_catalog(db_session, ["gpt-a", "gpt-b", "gpt-old", "gpt-unpicked"])
    assert _visibility(db_session, provider_name) == {
        "gpt-a": True,
        "gpt-b": False,
        "gpt-old": True,
        "my-finetune": True,
    }

    catalog = ["gpt-a", "gpt-b", "gpt-unpicked", "gpt-new"]
    results = _sync_with_catalog(db_session, catalog)

    assert results[str(provider.id)] == 2
    assert _visibility(db_session, provider_name) == {
        "gpt-a": True,
        "gpt-b": False,
        "gpt-new": True,
        "my-finetune": True,
    }
    assert str(provider.id) not in _sync_with_catalog(db_session, catalog)


def test_sync_does_not_change_the_global_default(
    db_session: Session, provider_name: str
) -> None:
    provider = _create_provider(
        db_session,
        provider_name,
        LlmProviderNames.OPENAI,
        is_auto_mode=True,
        models={"gpt-a": True, "gpt-old": True},
    )
    update_default_model(
        db_session=db_session,
        provider_id=provider.id,
        model="gpt-old",
        flow_type=LLMModelFlowType.CHAT,
    )

    sync_auto_mode_models(
        db_session=db_session,
        provider=provider,
        released_model_names=["gpt-new"],
        retired_model_names={"gpt-old"},
    )

    default_model = fetch_default_model(db_session, LLMModelFlowType.CHAT)
    assert default_model is not None
    assert default_model.llm_provider_id == provider.id
    assert default_model.name == "gpt-old"
    assert _visibility(db_session, provider_name) == {
        "gpt-a": True,
        "gpt-old": True,
        "gpt-new": True,
    }


def test_turning_auto_update_on_records_a_new_baseline(
    db_session: Session, provider_name: str
) -> None:
    provider = _create_provider(
        db_session,
        provider_name,
        LlmProviderNames.OPENAI,
        is_auto_mode=True,
        models={"gpt-a": True},
    )
    _sync_with_catalog(db_session, ["gpt-a"])

    for is_auto_mode in (False, True):
        put_llm_provider(
            llm_provider_upsert_request=LLMProviderUpsertRequest(
                id=provider.id,
                name=provider_name,
                provider=LlmProviderNames.OPENAI,
                is_auto_mode=is_auto_mode,
                model_configurations=[
                    ModelConfigurationUpsertRequest(name="gpt-a", is_visible=True)
                ],
            ),
            is_creation=False,
            user=MagicMock(),
            db_session=db_session,
        )

    # Released while auto-update was off, so the admin has already seen it.
    _sync_with_catalog(db_session, ["gpt-a", "gpt-while-off"])
    _sync_with_catalog(db_session, ["gpt-a", "gpt-while-off"])
    assert _visibility(db_session, provider_name) == {"gpt-a": True}


def test_toggling_auto_update_keeps_the_saved_models(
    db_session: Session, provider_name: str
) -> None:
    provider = _create_provider(
        db_session,
        provider_name,
        LlmProviderNames.OPENAI,
        is_auto_mode=False,
        models={"gpt-a": True, "gpt-b": False, "my-finetune": True},
    )

    put_llm_provider(
        llm_provider_upsert_request=LLMProviderUpsertRequest(
            id=provider.id,
            name=provider_name,
            provider=LlmProviderNames.OPENAI,
            is_auto_mode=True,
            model_configurations=[
                ModelConfigurationUpsertRequest(name=mc.name, is_visible=mc.is_visible)
                for mc in provider.model_configurations
            ],
        ),
        is_creation=False,
        user=MagicMock(),
        db_session=db_session,
    )

    db_session.expire_all()
    updated = fetch_existing_llm_provider(name=provider_name, db_session=db_session)
    assert updated is not None
    assert updated.is_auto_mode is True
    assert _visibility(db_session, provider_name) == {
        "gpt-a": True,
        "gpt-b": False,
        "my-finetune": True,
    }


def test_auto_update_request_without_models_keeps_the_saved_models(
    db_session: Session, provider_name: str
) -> None:
    provider = _create_provider(
        db_session,
        provider_name,
        LlmProviderNames.OPENAI,
        is_auto_mode=False,
        models={"gpt-a": True, "gpt-b": False},
    )

    put_llm_provider(
        llm_provider_upsert_request=LLMProviderUpsertRequest(
            id=provider.id,
            name=provider_name,
            provider=LlmProviderNames.OPENAI,
            is_auto_mode=True,
            model_configurations=[],
        ),
        is_creation=False,
        user=MagicMock(),
        db_session=db_session,
    )

    assert _visibility(db_session, provider_name) == {"gpt-a": True, "gpt-b": False}


def test_aggregators_do_not_get_auto_update(
    db_session: Session, provider_name: str
) -> None:
    provider = _create_provider(
        db_session,
        provider_name,
        LlmProviderNames.OPENROUTER,
        is_auto_mode=True,
        models={"z-ai/glm-5.3": True},
    )
    assert provider.is_auto_mode is False

    # A provider saved with the flag before auto-update was limited to labs.
    provider.is_auto_mode = True
    db_session.commit()

    _sync_with_catalog(db_session, ["z-ai/glm-5.3"])
    results = _sync_with_catalog(db_session, ["other/model"])

    assert str(provider.id) not in results
    assert _visibility(db_session, provider_name) == {"z-ai/glm-5.3": True}


def test_sync_stores_image_support_for_released_models(
    db_session: Session, provider_name: str
) -> None:
    provider = _create_provider(
        db_session,
        provider_name,
        LlmProviderNames.OPENAI,
        is_auto_mode=True,
        models={"gpt-a": True},
    )

    sync_auto_mode_models(
        db_session=db_session,
        provider=provider,
        released_model_names=["gpt-4o", "gpt-3.5-turbo"],
        retired_model_names=set(),
    )
    db_session.commit()

    flows = _flows(db_session, provider_name)
    assert flows["gpt-4o"] == {LLMModelFlowType.CHAT, LLMModelFlowType.VISION}
    assert flows["gpt-3.5-turbo"] == {LLMModelFlowType.CHAT}

    update_default_vision_provider(provider.id, "gpt-4o", db_session)
    default_vision = fetch_default_model(db_session, LLMModelFlowType.VISION)
    assert default_vision is not None
    assert default_vision.name == "gpt-4o"


def test_vision_default_accepts_a_model_stored_without_image_support(
    db_session: Session, provider_name: str
) -> None:
    provider = _create_provider(
        db_session,
        provider_name,
        LlmProviderNames.OPENAI,
        is_auto_mode=True,
        models={"gpt-a": True},
    )
    # Earlier auto-update syncs stored released models with the chat flow only.
    for model_name in ("gpt-4o", "gpt-3.5-turbo"):
        insert_new_model_configuration__no_commit(
            db_session=db_session,
            llm_provider_id=provider.id,
            model_name=model_name,
            supported_flows=[LLMModelFlowType.CHAT],
            is_visible=True,
            max_input_tokens=None,
            display_name=None,
        )
    db_session.commit()

    update_default_vision_provider(provider.id, "gpt-4o", db_session)

    default_vision = fetch_default_model(db_session, LLMModelFlowType.VISION)
    assert default_vision is not None
    assert default_vision.name == "gpt-4o"
    assert default_vision.supports_image_input is True
    assert _flows(db_session, provider_name)["gpt-4o"] == {
        LLMModelFlowType.CHAT,
        LLMModelFlowType.VISION,
    }

    with pytest.raises(ValueError, match="does not support image input"):
        update_default_vision_provider(provider.id, "gpt-3.5-turbo", db_session)
    assert _flows(db_session, provider_name)["gpt-3.5-turbo"] == {LLMModelFlowType.CHAT}


def test_auto_update_provider_created_without_models_stores_image_support(
    db_session: Session, provider_name: str
) -> None:
    with patch(_CATALOG_PATH, return_value=["gpt-4o", "gpt-3.5-turbo"]):
        put_llm_provider(
            llm_provider_upsert_request=LLMProviderUpsertRequest(
                name=provider_name,
                provider=LlmProviderNames.OPENAI,
                api_key="sk-test-key-00000000000000000000000000000000000",
                api_key_changed=True,
                is_auto_mode=True,
                model_configurations=[],
            ),
            is_creation=True,
            user=MagicMock(),
            db_session=db_session,
        )

    flows = _flows(db_session, provider_name)
    assert LLMModelFlowType.VISION in flows["gpt-4o"]
    assert LLMModelFlowType.VISION not in flows["gpt-3.5-turbo"]
