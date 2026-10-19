from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import LLMModelFlowType
from onyx.db.llm import (
    clear_decision_model,
    fetch_default_model,
    fetch_existing_llm_provider_by_id,
    fetch_model_configurations_page,
    remove_llm_provider,
    sync_model_configurations,
    update_default_contextual_model,
    update_default_model,
    upsert_llm_provider,
)
from onyx.db.models import Base, ModelConfiguration
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    LLMProviderView,
    ModelConfigurationUpsertRequest,
    SyncModelEntry,
)
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    engine = SqlEngine.get_engine()
    schema_name = f"decision_model_test_{uuid4().hex}"
    scoped_engine = engine.execution_options(schema_translate_map={None: schema_name})
    with scoped_engine.begin() as connection:
        connection.execute(CreateSchema(schema_name))
        connection.execute(text(f'SET LOCAL search_path TO "{schema_name}", public'))
        Base.metadata.create_all(
            connection,
            tables=[
                Base.metadata.tables[name]
                for name in (
                    "llm_provider",
                    "model_configuration",
                    "llm_model_flow",
                    "image_generation_config",
                    "llm_provider__persona",
                    "llm_provider__user_group",
                    "persona",
                    "user_group",
                    "user",
                )
            ],
        )
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(schema_name)
    try:
        with Session(scoped_engine) as session:
            yield session
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        with engine.begin() as connection:
            connection.execute(DropSchema(schema_name, cascade=True))


@pytest.fixture
def decision_provider(db_session: Session) -> LLMProviderView:
    return upsert_llm_provider(
        LLMProviderUpsertRequest(
            name="TypeSafe decisions",
            provider="typesafe",
            model_configurations=[
                ModelConfigurationUpsertRequest(name="jev-latest", is_visible=False)
            ],
        ),
        db_session,
    )


def test_decision_model_requires_explicit_selection_and_can_be_cleared(
    db_session: Session, decision_provider: LLMProviderView
) -> None:
    stored = fetch_existing_llm_provider_by_id(decision_provider.id, db_session)
    assert stored is not None
    assert len(stored.model_configurations) == 1
    model = stored.model_configurations[0]
    assert (model.name, set(model.llm_model_flow_types)) == (
        "jev-latest",
        {LLMModelFlowType.DECISION},
    )
    assert fetch_default_model(db_session, LLMModelFlowType.DECISION) is None
    assert fetch_default_model(db_session, LLMModelFlowType.CHAT) is None

    update_default_model(
        db_session, decision_provider.id, "jev-latest", LLMModelFlowType.DECISION
    )
    db_session.expire_all()
    selected = fetch_default_model(db_session, LLMModelFlowType.DECISION)
    assert selected is not None
    assert (selected.llm_provider_id, selected.name, selected.is_visible) == (
        decision_provider.id,
        "jev-latest",
        False,
    )

    clear_decision_model(db_session)
    clear_decision_model(db_session)
    db_session.expire_all()
    assert fetch_default_model(db_session, LLMModelFlowType.DECISION) is None
    assert set(model.llm_model_flow_types) == {LLMModelFlowType.DECISION}


def test_chat_model_cannot_replace_selected_decision_model(
    db_session: Session, decision_provider: LLMProviderView
) -> None:
    chat_provider = upsert_llm_provider(
        LLMProviderUpsertRequest(
            name="Chat",
            provider="openai",
            model_configurations=[
                ModelConfigurationUpsertRequest(name="gpt-5-mini", is_visible=True)
            ],
        ),
        db_session,
    )
    update_default_model(
        db_session, decision_provider.id, "jev-latest", LLMModelFlowType.DECISION
    )
    with pytest.raises(ValueError, match="is not a valid model"):
        update_default_model(
            db_session, chat_provider.id, "gpt-5-mini", LLMModelFlowType.DECISION
        )
    db_session.rollback()
    selected = fetch_default_model(db_session, LLMModelFlowType.DECISION)
    assert selected is not None
    assert (selected.llm_provider_id, selected.name) == (
        decision_provider.id,
        "jev-latest",
    )
    chat = db_session.scalar(
        select(ModelConfiguration).where(
            ModelConfiguration.llm_provider_id == chat_provider.id
        )
    )
    assert chat is not None
    assert LLMModelFlowType.CHAT in chat.llm_model_flow_types
    assert LLMModelFlowType.DECISION not in chat.llm_model_flow_types


def test_provider_edit_preserves_hidden_decision_selection(
    db_session: Session, decision_provider: LLMProviderView
) -> None:
    update_default_model(
        db_session, decision_provider.id, "jev-latest", LLMModelFlowType.DECISION
    )
    upsert_llm_provider(
        LLMProviderUpsertRequest(
            id=decision_provider.id,
            name="Updated TypeSafe",
            provider="typesafe",
            api_key="test-rotated-key",
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name="jev-latest",
                    is_visible=False,
                    custom_display_name="Decision classifier",
                )
            ],
        ),
        db_session,
    )
    db_session.expire_all()
    selected = fetch_default_model(db_session, LLMModelFlowType.DECISION)
    assert selected is not None
    assert (
        selected.llm_provider_id,
        selected.name,
        selected.is_visible,
        selected.custom_display_name,
        set(selected.llm_model_flow_types),
    ) == (
        decision_provider.id,
        "jev-latest",
        False,
        "Decision classifier",
        {LLMModelFlowType.DECISION},
    )


def test_selected_model_can_only_be_removed_after_clearing(
    db_session: Session, decision_provider: LLMProviderView
) -> None:
    update_default_model(
        db_session, decision_provider.id, "jev-latest", LLMModelFlowType.DECISION
    )
    request = LLMProviderUpsertRequest(
        id=decision_provider.id, provider="typesafe", model_configurations=[]
    )
    with pytest.raises(ValueError, match="Cannot remove the default model"):
        upsert_llm_provider(request, db_session)
    db_session.rollback()
    selected = fetch_default_model(db_session, LLMModelFlowType.DECISION)
    assert selected is not None and selected.name == "jev-latest"

    clear_decision_model(db_session)
    upsert_llm_provider(request, db_session)
    db_session.expire_all()
    stored = fetch_existing_llm_provider_by_id(decision_provider.id, db_session)
    assert stored is not None
    assert stored.model_configurations == []
    assert fetch_default_model(db_session, LLMModelFlowType.DECISION) is None


def test_deleting_provider_clears_selected_decision_model(
    db_session: Session, decision_provider: LLMProviderView
) -> None:
    update_default_model(
        db_session, decision_provider.id, "jev-latest", LLMModelFlowType.DECISION
    )
    selected = fetch_default_model(db_session, LLMModelFlowType.DECISION)
    assert selected is not None and selected.name == "jev-latest"

    remove_llm_provider(db_session, decision_provider.id)
    db_session.expire_all()
    assert fetch_default_model(db_session, LLMModelFlowType.DECISION) is None
    assert fetch_existing_llm_provider_by_id(decision_provider.id, db_session) is None


def test_discovered_typesafe_model_survives_save_and_refresh_without_reselection(
    db_session: Session, decision_provider: LLMProviderView
) -> None:
    discovered = SyncModelEntry(
        name="jev-future",
        display_name="Jev Future",
        supports_chat=False,
        supports_decisions=True,
    )
    sync_model_configurations(db_session, decision_provider.id, [discovered])
    update_default_model(
        db_session, decision_provider.id, "jev-future", LLMModelFlowType.DECISION
    )
    upsert_llm_provider(
        LLMProviderUpsertRequest(
            id=decision_provider.id,
            provider="typesafe",
            keep_existing_models=True,
            model_configurations=[
                ModelConfigurationUpsertRequest(name="jev-future", is_visible=False)
            ],
        ),
        db_session,
    )
    selected = fetch_default_model(db_session, LLMModelFlowType.DECISION)
    assert selected is not None
    assert selected.name == "jev-future"
    assert set(selected.llm_model_flow_types) == {LLMModelFlowType.DECISION}
    clear_decision_model(db_session)
    sync_model_configurations(db_session, decision_provider.id, [discovered])
    assert fetch_default_model(db_session, LLMModelFlowType.DECISION) is None


def test_decision_model_cannot_become_contextual_rag_default(
    db_session: Session, decision_provider: LLMProviderView
) -> None:
    from onyx.error_handling.exceptions import OnyxError
    from onyx.server.manage.search_settings import validate_contextual_rag_model

    model_id = decision_provider.model_configurations[0].id
    with pytest.raises(ValueError, match="requires a chat model"):
        update_default_contextual_model(db_session, True, model_id)
    with pytest.raises(OnyxError, match="requires a chat model"):
        validate_contextual_rag_model(model_id, db_session, True)
    assert fetch_default_model(db_session, LLMModelFlowType.CONTEXTUAL_RAG) is None


def test_custom_chat_model_can_be_created_and_edited_as_default(
    db_session: Session,
) -> None:
    provider = upsert_llm_provider(
        LLMProviderUpsertRequest(
            name="Local chat",
            provider="ollama",
            model_configurations=[
                ModelConfigurationUpsertRequest(name="instructor-chat", is_visible=True)
            ],
        ),
        db_session,
    )
    update_default_model(
        db_session, provider.id, "instructor-chat", LLMModelFlowType.CHAT
    )
    upsert_llm_provider(
        LLMProviderUpsertRequest(
            id=provider.id,
            provider="ollama",
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name="instructor-chat",
                    is_visible=True,
                    custom_display_name="Team chat",
                )
            ],
        ),
        db_session,
    )
    db_session.expire_all()
    selected = fetch_default_model(db_session, LLMModelFlowType.CHAT)
    assert selected is not None
    assert (selected.name, selected.custom_display_name) == (
        "instructor-chat",
        "Team chat",
    )


def test_discovery_can_upgrade_decision_only_model_to_dual_capability(
    db_session: Session,
) -> None:
    provider = upsert_llm_provider(
        LLMProviderUpsertRequest(
            name="Router", provider="openrouter", model_configurations=[]
        ),
        db_session,
    )
    sync_model_configurations(
        db_session,
        provider.id,
        [
            SyncModelEntry(
                name="vendor/dual",
                display_name="Dual",
                supports_chat=False,
                supports_decisions=True,
            )
        ],
    )
    db_session.expire_all()
    sync_model_configurations(
        db_session,
        provider.id,
        [
            SyncModelEntry(
                name="vendor/dual",
                display_name="Dual",
                supports_chat=True,
                supports_decisions=True,
            )
        ],
    )
    db_session.expire_all()
    stored = fetch_existing_llm_provider_by_id(provider.id, db_session)
    assert stored is not None
    assert set(stored.model_configurations[0].llm_model_flow_types) == {
        LLMModelFlowType.CHAT,
        LLMModelFlowType.DECISION,
    }
    assert fetch_default_model(db_session, LLMModelFlowType.DECISION) is None


def test_chat_pagination_filters_before_ranking_and_keeps_admin_catalog(
    db_session: Session,
) -> None:
    from onyx.server.manage.llm.api import _page_model_windows

    provider = upsert_llm_provider(
        LLMProviderUpsertRequest(
            name="Router", provider="openrouter", model_configurations=[]
        ),
        db_session,
    )
    sync_model_configurations(
        db_session,
        provider.id,
        [
            SyncModelEntry(
                name=f"a-decision-{index:03}",
                display_name=f"Decision {index}",
                supports_chat=False,
                supports_decisions=True,
            )
            for index in range(60)
        ]
        + [
            SyncModelEntry(name=f"z-chat-{index:03}", display_name=f"Chat {index}")
            for index in range(55)
        ],
    )
    first = fetch_model_configurations_page(
        db_session, [provider.id], flow_type=LLMModelFlowType.CHAT
    )[provider.id]
    assert [model.name for model in first.model_configurations] == [
        f"z-chat-{index:03}" for index in range(50)
    ]
    assert first.next_offset == 50
    second = fetch_model_configurations_page(
        db_session, [provider.id], offset=50, flow_type=LLMModelFlowType.CHAT
    )[provider.id]
    assert [model.name for model in second.model_configurations] == [
        f"z-chat-{index:03}" for index in range(50, 55)
    ]
    assert second.next_offset is None
    admin_page = fetch_model_configurations_page(db_session, [provider.id])[provider.id]
    assert [model.name for model in admin_page.model_configurations] == [
        f"a-decision-{index:03}" for index in range(50)
    ]
    assert admin_page.next_offset == 50
    search_page = fetch_model_configurations_page(
        db_session, [provider.id], name_query="054", flow_type=LLMModelFlowType.CHAT
    )[provider.id]
    assert [model.name for model in search_page.model_configurations] == ["z-chat-054"]
    assert search_page.next_offset is None
    stored = fetch_existing_llm_provider_by_id(provider.id, db_session)
    assert stored is not None
    pinned = _page_model_windows(
        db_session,
        [stored],
        [search_page.model_configurations[0], admin_page.model_configurations[0]],
        flow_type=LLMModelFlowType.CHAT,
    )[provider.id]
    assert [model.name for model in pinned.model_configurations] == [
        *[f"z-chat-{index:03}" for index in range(50)],
        "z-chat-054",
    ]
    assert pinned.next_offset == 50
