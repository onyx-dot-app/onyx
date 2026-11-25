from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import LLMModelFlowType, ModelRole
from onyx.db.llm import (
    clear_role,
    fetch_existing_llm_provider_by_id,
    fetch_role_model,
    fetch_roles_by_model_id,
    remove_llm_provider,
    set_role_model,
    sync_auto_mode_models,
    sync_model_configurations,
    upsert_llm_provider,
)
from onyx.db.models import Base
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    LLMProviderView,
    ModelConfigurationUpsertRequest,
    SyncModelEntry,
)
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


@pytest.fixture
def db_session(test_schema_engine: Engine) -> Generator[Session, None, None]:
    with Session(test_schema_engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture(scope="module")
def test_schema_engine() -> Generator[Engine, None, None]:
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    engine = SqlEngine.get_engine()
    schema_name = f"task_defaults_test_{uuid4().hex}"
    scoped_engine = engine.execution_options(schema_translate_map={None: schema_name})
    with scoped_engine.begin() as connection:
        connection.execute(CreateSchema(schema_name))
        connection.execute(text(f'SET LOCAL search_path TO "{schema_name}", public'))
        Base.metadata.create_all(
            connection,
            tables=[
                Base.metadata.tables[table_name]
                for table_name in (
                    "voice_provider",
                    "llm_provider",
                    "model_configuration",
                    "llm_model_flow",
                    "model_role",
                    "image_generation_config",
                    "llm_provider__persona",
                    "llm_provider__user_group",
                    "persona",
                    "embedding_provider",
                    "search_settings",
                    "user_group",
                    "user",
                    "user_preferences",
                )
            ],
        )
    tenant_token = CURRENT_TENANT_ID_CONTEXTVAR.set(schema_name)
    try:
        yield scoped_engine
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(tenant_token)
        with engine.begin() as connection:
            connection.execute(DropSchema(schema_name, cascade=True))


@pytest.fixture
def provider(db_session: Session) -> Generator[LLMProviderView, None, None]:
    saved = upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=f"test-naming-{uuid4().hex}",
            provider="openai",
            model_configurations=[
                ModelConfigurationUpsertRequest(name="gpt-6-luna", is_visible=True),
                ModelConfigurationUpsertRequest(name="gpt-6-sol", is_visible=False),
            ],
        ),
        db_session,
    )
    try:
        yield saved
    finally:
        db_session.rollback()
        remove_llm_provider(db_session, saved.id)


def test_typesafe_credentials_persist_without_chat_models(db_session: Session) -> None:
    saved = upsert_llm_provider(
        LLMProviderUpsertRequest(
            provider="typesafe",
            api_key="typesafe-test-key",
            is_auto_mode=True,
        ),
        db_session,
    )
    try:
        stored = fetch_existing_llm_provider_by_id(saved.id, db_session)
        assert stored is not None
        assert stored.api_key is not None
        assert stored.api_key.get_value(apply_mask=False) == "typesafe-test-key"
        assert stored.model_configurations == []
        assert stored.is_auto_mode is False
        for role in (ModelRole.CHAT, ModelRole.CRAFT):
            with pytest.raises(ValueError, match="not a valid model"):
                set_role_model(db_session, role, saved.id, "jev-latest")
            db_session.rollback()
        with pytest.raises(ValueError, match="chat model discovery"):
            sync_model_configurations(
                db_session,
                saved.id,
                [SyncModelEntry(name="jev-latest", display_name="Jev")],
            )
        db_session.rollback()
    finally:
        remove_llm_provider(db_session, saved.id)


def _update_provider(
    db_session: Session,
    provider: LLMProviderView,
    *,
    mini_visible: bool = True,
    nano_visible: bool = False,
) -> None:
    upsert_llm_provider(
        LLMProviderUpsertRequest(
            id=provider.id,
            name=provider.name,
            provider="openai",
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name="gpt-6-luna", is_visible=mini_visible
                ),
                ModelConfigurationUpsertRequest(
                    name="gpt-6-sol", is_visible=nano_visible
                ),
            ],
        ),
        db_session,
    )


@pytest.mark.parametrize(
    "model_name,is_visible", [("gpt-6-luna", True), ("gpt-6-sol", False)]
)
def test_setting_chat_naming_is_idempotent_and_preserves_visibility(
    db_session: Session,
    provider: LLMProviderView,
    model_name: str,
    is_visible: bool,
) -> None:
    set_role_model(
        db_session=db_session,
        role=ModelRole.CHAT_NAMING,
        provider_id=provider.id,
        model_name=model_name,
    )
    set_role_model(
        db_session=db_session,
        role=ModelRole.CHAT_NAMING,
        provider_id=provider.id,
        model_name=model_name,
    )

    default = fetch_role_model(db_session, ModelRole.CHAT_NAMING)
    assert default is not None
    assert (default.llm_provider_id, default.name, default.is_visible) == (
        provider.id,
        model_name,
        is_visible,
    )
    assert LLMModelFlowType.CHAT in default.llm_model_flow_types


def test_search_selection_persists_hidden_model_and_resets_independently(
    db_session: Session, provider: LLMProviderView
) -> None:
    set_role_model(
        db_session=db_session,
        role=ModelRole.CHAT_NAMING,
        provider_id=provider.id,
        model_name="gpt-6-luna",
    )
    set_role_model(
        db_session=db_session,
        role=ModelRole.SEARCH_SELECTION,
        provider_id=provider.id,
        model_name="gpt-6-sol",
    )
    set_role_model(
        db_session=db_session,
        role=ModelRole.SEARCH_SELECTION,
        provider_id=provider.id,
        model_name="gpt-6-sol",
    )
    db_session.expire_all()

    selection = fetch_role_model(db_session, ModelRole.SEARCH_SELECTION)
    assert selection is not None
    assert (selection.name, selection.is_visible) == ("gpt-6-sol", False)

    clear_role(db_session, ModelRole.CHAT_NAMING)
    assert fetch_role_model(db_session, ModelRole.CHAT_NAMING) is None
    assert fetch_role_model(db_session, ModelRole.SEARCH_SELECTION) is selection
    set_role_model(
        db_session=db_session,
        role=ModelRole.CHAT_NAMING,
        provider_id=provider.id,
        model_name="gpt-6-luna",
    )
    clear_role(db_session, ModelRole.SEARCH_SELECTION)
    clear_role(db_session, ModelRole.SEARCH_SELECTION)
    assert fetch_role_model(db_session, ModelRole.SEARCH_SELECTION) is None
    naming = fetch_role_model(db_session, ModelRole.CHAT_NAMING)
    assert naming is not None and naming.name == "gpt-6-luna"


def test_search_selection_survives_edit_discovery_and_auto_sync(
    db_session: Session, provider: LLMProviderView
) -> None:
    set_role_model(
        db_session=db_session,
        role=ModelRole.SEARCH_SELECTION,
        provider_id=provider.id,
        model_name="gpt-6-sol",
    )
    _update_provider(db_session, provider)
    sync_model_configurations(
        db_session,
        provider.id,
        [
            SyncModelEntry(
                name="gpt-6-sol", display_name="GPT 5 nano", supports_reasoning=True
            )
        ],
    )
    stored = fetch_existing_llm_provider_by_id(provider.id, db_session)
    assert stored is not None
    sync_auto_mode_models(
        db_session,
        stored,
        released_model_names=["gpt-6-luna"],
        retired_model_names={"gpt-6-sol"},
    )
    selection = fetch_role_model(db_session, ModelRole.SEARCH_SELECTION)
    assert selection is not None
    assert (selection.name, selection.is_visible) == ("gpt-6-sol", False)
    assert LLMModelFlowType.REASONING in selection.llm_model_flow_types


def test_search_selection_can_be_hidden_but_not_removed(
    db_session: Session, provider: LLMProviderView
) -> None:
    set_role_model(
        db_session=db_session,
        role=ModelRole.SEARCH_SELECTION,
        provider_id=provider.id,
        model_name="gpt-6-luna",
    )
    _update_provider(db_session, provider, mini_visible=False)
    selection = fetch_role_model(db_session, ModelRole.SEARCH_SELECTION)
    assert selection is not None and not selection.is_visible
    with pytest.raises(ValueError, match="Cannot remove the default model"):
        upsert_llm_provider(
            LLMProviderUpsertRequest(
                id=provider.id, provider="openai", model_configurations=[]
            ),
            db_session,
        )


def test_invalid_search_selection_preserves_existing_defaults(
    db_session: Session, provider: LLMProviderView
) -> None:
    set_role_model(
        db_session=db_session,
        role=ModelRole.CHAT_NAMING,
        provider_id=provider.id,
        model_name="gpt-6-luna",
    )
    set_role_model(
        db_session=db_session,
        role=ModelRole.SEARCH_SELECTION,
        provider_id=provider.id,
        model_name="gpt-6-sol",
    )
    with pytest.raises(ValueError, match="is not a valid model"):
        set_role_model(
            db_session=db_session,
            role=ModelRole.SEARCH_SELECTION,
            provider_id=provider.id,
            model_name="missing-model",
        )
    selection = fetch_role_model(db_session, ModelRole.SEARCH_SELECTION)
    naming = fetch_role_model(db_session, ModelRole.CHAT_NAMING)
    assert selection is not None and selection.name == "gpt-6-sol"
    assert naming is not None and naming.name == "gpt-6-luna"


def test_search_selection_shared_with_chat_cannot_be_hidden(
    db_session: Session, provider: LLMProviderView
) -> None:
    set_role_model(
        db_session=db_session,
        role=ModelRole.SEARCH_SELECTION,
        provider_id=provider.id,
        model_name="gpt-6-luna",
    )
    set_role_model(
        db_session=db_session,
        role=ModelRole.CHAT,
        provider_id=provider.id,
        model_name="gpt-6-luna",
    )
    with pytest.raises(ValueError, match="Cannot hide the default model"):
        _update_provider(db_session, provider, mini_visible=False)


def test_replacing_and_clearing_chat_naming_preserves_chat_and_search_selection(
    db_session: Session, provider: LLMProviderView
) -> None:
    set_role_model(
        db_session=db_session,
        role=ModelRole.CHAT,
        provider_id=provider.id,
        model_name="gpt-6-luna",
    )
    set_role_model(
        db_session=db_session,
        role=ModelRole.SEARCH_SELECTION,
        provider_id=provider.id,
        model_name="gpt-6-luna",
    )
    set_role_model(
        db_session=db_session,
        role=ModelRole.CHAT_NAMING,
        provider_id=provider.id,
        model_name="gpt-6-luna",
    )
    set_role_model(
        db_session=db_session,
        role=ModelRole.CHAT_NAMING,
        provider_id=provider.id,
        model_name="gpt-6-sol",
    )

    default = fetch_role_model(db_session, ModelRole.CHAT_NAMING)
    assert default is not None
    assert (default.name, default.is_visible) == ("gpt-6-sol", False)
    assert (
        sum(
            ModelRole.CHAT_NAMING in roles
            for roles in fetch_roles_by_model_id(db_session).values()
        )
        == 1
    )

    clear_role(db_session, ModelRole.CHAT_NAMING)
    clear_role(db_session, ModelRole.CHAT_NAMING)

    assert fetch_role_model(db_session, ModelRole.CHAT_NAMING) is None
    for model in [
        fetch_role_model(db_session, ModelRole.CHAT),
        fetch_role_model(db_session, ModelRole.SEARCH_SELECTION),
    ]:
        assert model is not None
        assert (model.llm_provider_id, model.name, model.is_visible) == (
            provider.id,
            "gpt-6-luna",
            True,
        )


def test_hidden_chat_naming_default_survives_provider_edit_and_discovery(
    db_session: Session, provider: LLMProviderView
) -> None:
    set_role_model(
        db_session=db_session,
        role=ModelRole.CHAT_NAMING,
        provider_id=provider.id,
        model_name="gpt-6-sol",
    )

    _update_provider(db_session, provider)
    sync_model_configurations(
        db_session,
        provider.id,
        [
            SyncModelEntry(
                name="gpt-6-sol", display_name="GPT 5 nano", supports_reasoning=True
            )
        ],
    )

    default = fetch_role_model(db_session, ModelRole.CHAT_NAMING)
    assert default is not None
    assert (default.name, default.is_visible) == ("gpt-6-sol", False)
    assert {LLMModelFlowType.CHAT, LLMModelFlowType.REASONING} <= set(
        default.llm_model_flow_types
    )


def test_chat_naming_only_default_can_be_hidden_but_shared_chat_default_cannot(
    db_session: Session, provider: LLMProviderView
) -> None:
    set_role_model(
        db_session=db_session,
        role=ModelRole.CHAT_NAMING,
        provider_id=provider.id,
        model_name="gpt-6-luna",
    )
    _update_provider(db_session, provider, mini_visible=False)
    default = fetch_role_model(db_session, ModelRole.CHAT_NAMING)
    assert default is not None
    assert (default.name, default.is_visible) == ("gpt-6-luna", False)

    set_role_model(
        db_session=db_session,
        role=ModelRole.CHAT,
        provider_id=provider.id,
        model_name="gpt-6-luna",
    )
    with pytest.raises(ValueError, match="Cannot hide the default model"):
        _update_provider(db_session, provider, mini_visible=False)


def test_chat_naming_default_cannot_be_removed_during_provider_edit(
    db_session: Session, provider: LLMProviderView
) -> None:
    set_role_model(
        db_session=db_session,
        role=ModelRole.CHAT_NAMING,
        provider_id=provider.id,
        model_name="gpt-6-sol",
    )
    with pytest.raises(ValueError, match="Cannot remove the default model"):
        upsert_llm_provider(
            LLMProviderUpsertRequest(
                id=provider.id,
                provider="openai",
                model_configurations=[
                    ModelConfigurationUpsertRequest(name="gpt-6-luna", is_visible=True)
                ],
            ),
            db_session,
        )


def test_auto_sync_does_not_restore_hidden_chat_naming_only_default(
    db_session: Session, provider: LLMProviderView
) -> None:
    set_role_model(
        db_session=db_session,
        role=ModelRole.CHAT_NAMING,
        provider_id=provider.id,
        model_name="gpt-6-sol",
    )
    stored_provider = fetch_existing_llm_provider_by_id(provider.id, db_session)
    assert stored_provider is not None

    sync_auto_mode_models(
        db_session,
        stored_provider,
        released_model_names=["gpt-6-luna"],
        retired_model_names={"gpt-6-sol"},
    )

    default = fetch_role_model(db_session, ModelRole.CHAT_NAMING)
    assert default is not None
    assert (default.name, default.is_visible) == ("gpt-6-sol", False)


@pytest.mark.parametrize("model_name", ["missing-model", ""])
def test_invalid_selection_preserves_existing_chat_naming_default(
    db_session: Session, provider: LLMProviderView, model_name: str
) -> None:
    set_role_model(
        db_session=db_session,
        role=ModelRole.CHAT_NAMING,
        provider_id=provider.id,
        model_name="gpt-6-sol",
    )
    with pytest.raises(ValueError, match="is not a valid model"):
        set_role_model(
            db_session=db_session,
            role=ModelRole.CHAT_NAMING,
            provider_id=provider.id,
            model_name=model_name,
        )

    default = fetch_role_model(db_session, ModelRole.CHAT_NAMING)
    assert default is not None
    assert (default.llm_provider_id, default.name, default.is_visible) == (
        provider.id,
        "gpt-6-sol",
        False,
    )


@pytest.mark.parametrize("model_name", ["gpt-6-luna", "gpt-6-sol"])
def test_setting_craft_is_idempotent_and_makes_model_visible(
    db_session: Session, provider: LLMProviderView, model_name: str
) -> None:
    assert fetch_role_model(db_session, ModelRole.CRAFT) is None

    set_role_model(
        db_session=db_session,
        role=ModelRole.CRAFT,
        provider_id=provider.id,
        model_name=model_name,
    )
    set_role_model(
        db_session=db_session,
        role=ModelRole.CRAFT,
        provider_id=provider.id,
        model_name=model_name,
    )
    db_session.rollback()

    default = fetch_role_model(db_session, ModelRole.CRAFT)
    assert default is not None
    assert (default.llm_provider_id, default.name, default.is_visible) == (
        provider.id,
        model_name,
        True,
    )
    assert LLMModelFlowType.CHAT in default.llm_model_flow_types


@pytest.mark.parametrize("model_name", ["missing-model", ""])
def test_invalid_selection_preserves_existing_craft_default(
    db_session: Session, provider: LLMProviderView, model_name: str
) -> None:
    set_role_model(
        db_session=db_session,
        role=ModelRole.CRAFT,
        provider_id=provider.id,
        model_name="gpt-6-sol",
    )
    with pytest.raises(ValueError) as exc_info:
        set_role_model(
            db_session=db_session,
            role=ModelRole.CRAFT,
            provider_id=provider.id,
            model_name=model_name,
        )

    assert str(exc_info.value) == (
        f"Model '{model_name}' is not a valid model for provider_id={provider.id}"
    )
    default = fetch_role_model(db_session, ModelRole.CRAFT)
    assert default is not None
    assert (default.llm_provider_id, default.name, default.is_visible) == (
        provider.id,
        "gpt-6-sol",
        True,
    )
