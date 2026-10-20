from collections.abc import Generator
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import LLMModelFlowType
from onyx.db.llm import (
    clear_decision_model,
    fetch_default_model,
    update_default_model,
    upsert_llm_provider,
)
from onyx.db.models import LLMProvider, ModelConfiguration, VoiceProvider
from onyx.db.voice import delete_voice_provider, upsert_voice_provider
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    ModelConfigurationUpsertRequest,
)


@pytest.fixture
def transaction(db_session: Session) -> Generator[Session, None, None]:
    with patch.object(db_session, "commit", side_effect=db_session.flush):
        try:
            yield db_session
        finally:
            db_session.rollback()


def test_decision_scope_preserves_shared_chat_model_and_default(
    transaction: Session,
) -> None:
    name = "test/dual"
    provider = upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=f"decision-scope-{uuid4().hex}",
            provider="openrouter",
            api_key="test-key",
            is_public=False,
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name=name,
                    is_visible=True,
                    max_input_tokens=7654,
                    custom_display_name="Chat model",
                    temperature_default=0.4,
                    supports_image_input=True,
                )
            ],
        ),
        transaction,
        discovered_decision_models={name: True},
    )
    update_default_model(transaction, provider.id, name, LLMModelFlowType.CHAT)
    model = transaction.scalar(
        select(ModelConfiguration).where(
            ModelConfiguration.llm_provider_id == provider.id
        )
    )
    assert model is not None
    model_id = model.id

    upsert_llm_provider(
        LLMProviderUpsertRequest(
            id=provider.id,
            provider="openrouter",
            api_key="test-key",
            model_configuration_scope="decision",
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name=name,
                    is_visible=False,
                    max_input_tokens=1,
                    custom_display_name="Must not overwrite",
                    temperature_default=1.8,
                    supports_image_input=False,
                )
            ],
        ),
        transaction,
        discovered_decision_models={name: True},
    )
    transaction.expire_all()
    model = transaction.get(ModelConfiguration, model_id)
    assert model is not None
    assert model.is_visible is True
    assert model.max_input_tokens == 7654
    assert model.custom_display_name == "Chat model"
    assert model.temperature_default == 0.4
    assert LLMModelFlowType.VISION in model.llm_model_flow_types

    upsert_llm_provider(
        LLMProviderUpsertRequest(
            id=provider.id,
            provider="openrouter",
            api_key="test-key",
            model_configuration_scope="decision",
            model_configurations=[],
        ),
        transaction,
    )
    transaction.expire_all()
    model = transaction.get(ModelConfiguration, model_id)
    assert model is not None
    assert model.is_visible is True
    assert model.max_input_tokens == 7654
    assert model.custom_display_name == "Chat model"
    assert model.temperature_default == 0.4
    assert set(model.llm_model_flow_types) == {
        LLMModelFlowType.CHAT,
        LLMModelFlowType.VISION,
    }
    default = fetch_default_model(transaction, LLMModelFlowType.CHAT)
    assert default is not None and default.id == model_id
    saved = transaction.get(LLMProvider, provider.id)
    assert saved is not None and saved.is_public is False


def test_provider_setup_does_not_select_decision_model_or_enable_chat(
    transaction: Session,
) -> None:
    clear_decision_model(transaction)
    provider = upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=f"decision-unset-{uuid4().hex}",
            provider="openrouter",
            model_configuration_scope="decision",
            api_key="test-key",
            model_configurations=[
                ModelConfigurationUpsertRequest(name="test/dual", is_visible=True)
            ],
        ),
        transaction,
        discovered_decision_models={"test/dual": True},
    )
    assert fetch_default_model(transaction, LLMModelFlowType.DECISION) is None
    model = transaction.scalar(
        select(ModelConfiguration).where(
            ModelConfiguration.llm_provider_id == provider.id
        )
    )
    assert model is not None and model.is_visible is False
    assert set(model.llm_model_flow_types) == {
        LLMModelFlowType.CHAT,
        LLMModelFlowType.DECISION,
    }


def test_linked_voice_provider_cannot_be_deleted(transaction: Session) -> None:
    voice = upsert_voice_provider(
        db_session=transaction,
        provider_id=None,
        name=f"zoom-link-{uuid4().hex}",
        provider_type="zoom",
        api_key="key",
        api_key_changed=True,
        api_secret="secret",
        api_secret_changed=True,
    )
    provider = upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=f"zoom-decisions-{uuid4().hex}",
            provider="zoom_ai",
            zoom_voice_provider_id=voice.id,
            model_configuration_scope="decision",
            model_configurations=[
                ModelConfigurationUpsertRequest(name="zoom-decisions", is_visible=True)
            ],
        ),
        transaction,
    )
    saved = transaction.get(LLMProvider, provider.id)
    assert saved is not None
    assert saved.zoom_voice_provider_id == voice.id
    assert saved.api_key is None
    assert saved.custom_config is None
    with pytest.raises(OnyxError) as error:
        delete_voice_provider(transaction, voice.id)
    assert error.value.error_code == OnyxErrorCode.CONFLICT
    assert "Decision Models" in error.value.detail
    assert transaction.get(VoiceProvider, voice.id) is not None


def test_scope_rejects_unverified_decision_flag(transaction: Session) -> None:
    with pytest.raises(ValueError, match="does not support decisions"):
        upsert_llm_provider(
            LLMProviderUpsertRequest(
                name=f"invalid-decision-{uuid4().hex}",
                provider="openai",
                model_configuration_scope="decision",
                model_configurations=[
                    ModelConfigurationUpsertRequest(
                        name="gpt-4o", is_visible=True, supports_decisions=True
                    )
                ],
            ),
            transaction,
        )
