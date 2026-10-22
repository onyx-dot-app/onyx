from collections.abc import Generator
from typing import Literal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import LLMModelFlowType
from onyx.db.llm import (
    clear_decision_model,
    fetch_default_model,
    update_default_model,
    upsert_decision_provider,
    upsert_llm_provider,
)
from onyx.db.models import LLMProvider, ModelConfiguration, VoiceProvider
from onyx.db.voice import delete_voice_provider, upsert_voice_provider
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.llm.api import _validate_zoom_decision_connection
from onyx.server.manage.llm.models import (
    DecisionProviderUpsertRequest,
    LLMProviderUpsertRequest,
    ModelConfigurationUpsertRequest,
)
from onyx.server.manage.voice.api import upsert_voice_provider_endpoint
from onyx.server.manage.voice.models import VoiceProviderUpsertRequest


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
            is_auto_mode=True,
            deployment_name="shared-chat-deployment",
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
    )
    update_default_model(transaction, provider.id, name, LLMModelFlowType.CHAT)
    model = transaction.scalar(
        select(ModelConfiguration).where(
            ModelConfiguration.llm_provider_id == provider.id
        )
    )
    assert model is not None
    model_id = model.id

    upsert_decision_provider(
        DecisionProviderUpsertRequest(
            id=provider.id,
            provider="openrouter",
            api_key="test-key",
            selected_model_names=[name],
        ),
        transaction,
        discovered_models={name: True},
    )
    transaction.expire_all()
    model = transaction.get(ModelConfiguration, model_id)
    assert model is not None
    assert model.is_visible is True
    assert model.max_input_tokens == 7654
    assert model.custom_display_name == "Chat model"
    assert model.temperature_default == 0.4
    assert LLMModelFlowType.VISION in model.llm_model_flow_types

    upsert_decision_provider(
        DecisionProviderUpsertRequest(
            id=provider.id,
            provider="openrouter",
            api_key="test-key",
            selected_model_names=[],
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
    assert saved.is_auto_mode is True
    assert saved.deployment_name == "shared-chat-deployment"


def test_provider_setup_does_not_select_decision_model_or_enable_chat(
    transaction: Session,
) -> None:
    clear_decision_model(transaction)
    provider = upsert_decision_provider(
        DecisionProviderUpsertRequest(
            name=f"decision-unset-{uuid4().hex}",
            provider="openrouter",
            api_key="test-key",
            selected_model_names=["test/dual"],
        ),
        transaction,
        discovered_models={"test/dual": True},
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


def test_selected_shared_zoom_connection_cannot_be_deleted(
    transaction: Session,
) -> None:
    voice = upsert_voice_provider(
        db_session=transaction,
        provider_id=None,
        name=f"zoom-link-{uuid4().hex}",
        provider_type="zoom",
        api_key="key",
        api_key_changed=True,
        api_secret="secret",
        api_secret_changed=True,
        link_decision_provider=True,
    )
    provider = transaction.scalar(
        select(LLMProvider).where(LLMProvider.zoom_voice_provider_id == voice.id)
    )
    assert provider is not None
    saved = transaction.get(LLMProvider, provider.id)
    assert saved is not None
    assert saved.zoom_voice_provider_id == voice.id
    assert saved.api_key is None
    assert saved.custom_config is None
    update_default_model(
        transaction, provider.id, "zoom-decisions", LLMModelFlowType.DECISION
    )
    with pytest.raises(OnyxError) as error:
        delete_voice_provider(transaction, voice.id)
    assert error.value.error_code == OnyxErrorCode.RESOURCE_IN_USE
    assert "selected decision model" in error.value.detail
    assert transaction.get(VoiceProvider, voice.id) is not None


def test_shared_zoom_setup_rotation_and_deletion(transaction: Session) -> None:
    clear_decision_model(transaction)
    name = f"zoom-shared-{uuid4().hex}"
    voice = upsert_voice_provider(
        db_session=transaction,
        provider_id=None,
        name=name,
        provider_type="zoom",
        api_key="first-key",
        api_key_changed=True,
        api_secret="first-secret",
        api_secret_changed=True,
        link_decision_provider=True,
    )
    voice_id = voice.id
    linked = transaction.scalar(
        select(LLMProvider).where(LLMProvider.zoom_voice_provider_id == voice.id)
    )
    assert linked is not None
    linked_id = linked.id
    models = transaction.scalars(
        select(ModelConfiguration).where(
            ModelConfiguration.llm_provider_id == linked.id
        )
    ).all()
    assert {model.name for model in models} == {"zoom-decisions", "zoom-decisions-pro"}
    assert all(
        not model.is_visible
        and model.llm_model_flow_types == [LLMModelFlowType.DECISION]
        for model in models
    )
    assert fetch_default_model(transaction, LLMModelFlowType.DECISION) is None
    assert not voice.is_default_stt and not voice.is_default_tts
    upsert_voice_provider(
        db_session=transaction,
        provider_id=voice_id,
        name=name,
        provider_type="zoom",
        api_key="rotated-key",
        api_key_changed=True,
        api_secret="rotated-secret",
        api_secret_changed=True,
    )
    transaction.expire_all()
    assert (
        len(
            transaction.scalars(
                select(LLMProvider).where(
                    LLMProvider.zoom_voice_provider_id == voice_id
                )
            ).all()
        )
        == 1
    )
    saved = transaction.get(VoiceProvider, voice_id)
    assert (
        saved is not None and saved.api_key is not None and saved.api_secret is not None
    )
    assert saved.api_key.get_value(apply_mask=False) == "rotated-key"
    assert saved.api_secret.get_value(apply_mask=False) == "rotated-secret"
    delete_voice_provider(transaction, voice_id)
    transaction.expire_all()
    assert transaction.get(VoiceProvider, voice_id) is None
    assert transaction.get(LLMProvider, linked_id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["voice", "decision"])
async def test_only_decision_setup_links_zoom_decisions(
    transaction: Session, mode: Literal["voice", "decision"]
) -> None:
    clear_decision_model(transaction)
    with (
        patch(
            "onyx.voice.providers.zoom.ZoomVoiceProvider.validate_credentials",
            new_callable=AsyncMock,
        ) as scribe,
        patch(
            "onyx.server.manage.voice.api._validate_decision_credentials",
            new_callable=AsyncMock,
        ) as decisions,
        patch("onyx.server.manage.voice.api.invalidate_provider_listing_cache"),
    ):
        saved = await upsert_voice_provider_endpoint(
            VoiceProviderUpsertRequest(
                name=f"zoom-{mode}-{uuid4().hex}",
                provider_type="zoom",
                validation_mode=mode,
                api_key="key",
                api_secret="secret",
            ),
            MagicMock(),
            transaction,
        )
    assert scribe.await_count == int(mode == "voice")
    assert decisions.await_count == int(mode == "decision")
    assert not saved.is_default_stt and not saved.is_default_tts
    linked = transaction.scalar(
        select(LLMProvider.id).where(LLMProvider.zoom_voice_provider_id == saved.id)
    )
    assert (linked is not None) is (mode == "decision")
    assert fetch_default_model(transaction, LLMModelFlowType.DECISION) is None


@pytest.mark.asyncio
async def test_failed_decision_validation_rolls_back_both_records(
    transaction: Session,
) -> None:
    name = f"zoom-failure-{uuid4().hex}"
    with patch(
        "onyx.server.manage.voice.api._validate_decision_credentials",
        new_callable=AsyncMock,
        side_effect=RuntimeError("failure"),
    ):
        with pytest.raises(OnyxError, match="Connection test failed"):
            await upsert_voice_provider_endpoint(
                VoiceProviderUpsertRequest(
                    name=name,
                    provider_type="zoom",
                    validation_mode="decision",
                    api_key="key",
                    api_secret="secret",
                ),
                MagicMock(),
                transaction,
            )
    assert (
        transaction.scalar(select(VoiceProvider.id).where(VoiceProvider.name == name))
        is None
    )
    assert (
        transaction.scalar(select(LLMProvider.id).where(LLMProvider.name == name))
        is None
    )


def test_zoom_link_validation_rejects_relink_and_duplicate_link(
    transaction: Session,
) -> None:
    voices = [
        upsert_voice_provider(
            db_session=transaction,
            provider_id=None,
            name=f"zoom-relink-{uuid4().hex}",
            provider_type="zoom",
            api_key="key",
            api_key_changed=True,
            api_secret="secret",
            api_secret_changed=True,
            link_decision_provider=True,
        )
        for _ in range(2)
    ]
    linked = transaction.scalar(
        select(LLMProvider).where(LLMProvider.zoom_voice_provider_id == voices[0].id)
    )
    assert linked is not None

    def validate(voice_id: int | None, existing: LLMProvider | None) -> None:
        _validate_zoom_decision_connection(
            provider="zoom_ai",
            zoom_voice_provider_id=voice_id,
            existing_provider=existing,
            api_key=None,
            api_base=None,
            custom_config=None,
            user=MagicMock(),
            db_session=transaction,
        )

    with patch("onyx.server.manage.llm.api.has_global_permission", return_value=True):
        validate(voices[0].id, linked)
        for voice_id in (None, voices[1].id):
            with pytest.raises(OnyxError, match="cannot change"):
                validate(voice_id, linked)
        with pytest.raises(OnyxError, match="requires a Zoom connection"):
            validate(None, None)
        with pytest.raises(OnyxError) as error:
            validate(voices[0].id, None)
    assert error.value.error_code == OnyxErrorCode.CONFLICT


def test_scope_rejects_unverified_decision_flag(transaction: Session) -> None:
    with pytest.raises(ValueError, match="does not support decisions"):
        upsert_decision_provider(
            DecisionProviderUpsertRequest(
                name=f"invalid-decision-{uuid4().hex}",
                provider="openai",
                selected_model_names=["gpt-4o"],
            ),
            transaction,
        )


def test_decision_update_cannot_remove_selected_default(transaction: Session) -> None:
    provider = upsert_decision_provider(
        DecisionProviderUpsertRequest(
            provider="openai", selected_model_names=["gpt-6-luna"]
        ),
        transaction,
    )
    update_default_model(
        transaction, provider.id, "gpt-6-luna", LLMModelFlowType.DECISION
    )
    with pytest.raises(ValueError, match="Clear the selected decision model"):
        upsert_decision_provider(
            DecisionProviderUpsertRequest(
                id=provider.id, provider="openai", selected_model_names=[]
            ),
            transaction,
        )
    selected = fetch_default_model(transaction, LLMModelFlowType.DECISION)
    assert selected is not None and selected.name == "gpt-6-luna"


def test_general_save_does_not_select_catalog_decision_models(
    transaction: Session,
) -> None:
    provider = upsert_llm_provider(
        LLMProviderUpsertRequest(
            provider="openai",
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name="gpt-6-luna", is_visible=True, supports_decisions=True
                ),
            ],
        ),
        transaction,
    )
    assert provider.model_configurations[0].supports_decisions is False
    assert provider.model_configurations[0].supports_chat is True
