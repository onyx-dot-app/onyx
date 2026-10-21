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
    upsert_decision_provider,
    upsert_llm_provider,
)
from onyx.db.models import LLMProvider, ModelConfiguration
from onyx.server.manage.llm.models import (
    DecisionProviderUpsertRequest,
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
