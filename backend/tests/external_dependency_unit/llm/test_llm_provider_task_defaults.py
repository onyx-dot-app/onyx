from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import LLMModelFlowType
from onyx.db.llm import (
    fetch_default_chat_naming_model,
    fetch_default_craft_model,
    fetch_default_flows_by_model_id,
    fetch_default_llm_model,
    fetch_default_search_selection_model,
    fetch_existing_llm_provider_by_id,
    remove_llm_provider,
    sync_auto_mode_models,
    sync_model_configurations,
    update_default_chat_naming_provider,
    update_default_craft_provider,
    update_default_provider,
    update_default_search_selection_provider,
    update_no_default_chat_naming_provider,
    update_no_default_search_selection_provider,
    upsert_llm_provider,
)
from onyx.db.models import Base, LLMModelFlow, ModelConfiguration
from onyx.llm.well_known_providers.auto_update_models import (
    LLMProviderRecommendation,
    LLMRecommendations,
)
from onyx.llm.well_known_providers.models import SimpleKnownModel
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
                    "api_token",
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
                ModelConfigurationUpsertRequest(name="gpt-5-mini", is_visible=True),
                ModelConfigurationUpsertRequest(name="gpt-5-nano", is_visible=False),
            ],
        ),
        db_session,
    )
    try:
        yield saved
    finally:
        db_session.rollback()
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
                    name="gpt-5-mini", is_visible=mini_visible
                ),
                ModelConfigurationUpsertRequest(
                    name="gpt-5-nano", is_visible=nano_visible
                ),
            ],
        ),
        db_session,
    )


@pytest.mark.parametrize(
    "model_name,is_visible", [("gpt-5-mini", True), ("gpt-5-nano", False)]
)
def test_setting_chat_naming_creates_one_mapping_and_preserves_visibility(
    db_session: Session,
    provider: LLMProviderView,
    model_name: str,
    is_visible: bool,
) -> None:
    update_default_chat_naming_provider(provider.id, model_name, db_session)
    update_default_chat_naming_provider(provider.id, model_name, db_session)

    default = fetch_default_chat_naming_model(db_session)
    assert default is not None
    assert (default.llm_provider_id, default.name, default.is_visible) == (
        provider.id,
        model_name,
        is_visible,
    )
    mappings = db_session.scalars(
        select(LLMModelFlow).where(
            LLMModelFlow.model_configuration_id == default.id,
            LLMModelFlow.llm_model_flow_type == LLMModelFlowType.CHAT_NAMING,
        )
    ).all()
    assert len(mappings) == 1
    assert LLMModelFlowType.CHAT in default.llm_model_flow_types


def test_search_selection_persists_hidden_mapping_and_resets_independently(
    db_session: Session, provider: LLMProviderView
) -> None:
    update_default_chat_naming_provider(provider.id, "gpt-5-mini", db_session)
    update_default_search_selection_provider(provider.id, "gpt-5-nano", db_session)
    update_default_search_selection_provider(provider.id, "gpt-5-nano", db_session)
    db_session.expire_all()

    selection = fetch_default_search_selection_model(db_session)
    assert selection is not None
    assert (selection.name, selection.is_visible) == ("gpt-5-nano", False)
    mappings = db_session.scalars(
        select(LLMModelFlow).where(
            LLMModelFlow.model_configuration_id == selection.id,
            LLMModelFlow.llm_model_flow_type == LLMModelFlowType.SEARCH_SELECTION,
        )
    ).all()
    assert len(mappings) == 1
    assert mappings[0].is_default

    update_no_default_chat_naming_provider(db_session)
    assert fetch_default_chat_naming_model(db_session) is None
    assert fetch_default_search_selection_model(db_session) is selection
    update_default_chat_naming_provider(provider.id, "gpt-5-mini", db_session)
    update_no_default_search_selection_provider(db_session)
    update_no_default_search_selection_provider(db_session)
    assert fetch_default_search_selection_model(db_session) is None
    naming = fetch_default_chat_naming_model(db_session)
    assert naming is not None and naming.name == "gpt-5-mini"


def test_search_selection_survives_edit_discovery_and_auto_sync(
    db_session: Session, provider: LLMProviderView
) -> None:
    update_default_search_selection_provider(provider.id, "gpt-5-nano", db_session)
    _update_provider(db_session, provider)
    sync_model_configurations(
        db_session,
        provider.id,
        [
            SyncModelEntry(
                name="gpt-5-nano", display_name="GPT 5 nano", supports_reasoning=True
            )
        ],
    )
    stored = fetch_existing_llm_provider_by_id(provider.id, db_session)
    assert stored is not None
    sync_auto_mode_models(
        db_session,
        stored,
        LLMRecommendations(
            version="test",
            updated_at=datetime.now(timezone.utc),
            providers={
                "openai": LLMProviderRecommendation(
                    default_model=SimpleKnownModel(name="gpt-5-mini")
                )
            },
        ),
    )
    selection = fetch_default_search_selection_model(db_session)
    assert selection is not None
    assert (selection.name, selection.is_visible) == ("gpt-5-nano", False)
    assert LLMModelFlowType.REASONING in selection.llm_model_flow_types


def test_search_selection_can_be_hidden_but_not_removed(
    db_session: Session, provider: LLMProviderView
) -> None:
    update_default_search_selection_provider(provider.id, "gpt-5-mini", db_session)
    _update_provider(db_session, provider, mini_visible=False)
    selection = fetch_default_search_selection_model(db_session)
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
    update_default_chat_naming_provider(provider.id, "gpt-5-mini", db_session)
    update_default_search_selection_provider(provider.id, "gpt-5-nano", db_session)
    with pytest.raises(ValueError, match="is not a valid model"):
        update_default_search_selection_provider(
            provider.id, "missing-model", db_session
        )
    selection = fetch_default_search_selection_model(db_session)
    naming = fetch_default_chat_naming_model(db_session)
    assert selection is not None and selection.name == "gpt-5-nano"
    assert naming is not None and naming.name == "gpt-5-mini"


def test_search_selection_shared_with_chat_cannot_be_hidden(
    db_session: Session, provider: LLMProviderView
) -> None:
    update_default_search_selection_provider(provider.id, "gpt-5-mini", db_session)
    update_default_provider(provider.id, "gpt-5-mini", db_session)
    with pytest.raises(ValueError, match="Cannot hide the default model"):
        _update_provider(db_session, provider, mini_visible=False)


def test_replacing_and_clearing_chat_naming_preserves_chat_and_search_selection(
    db_session: Session, provider: LLMProviderView
) -> None:
    update_default_provider(provider.id, "gpt-5-mini", db_session)
    update_default_search_selection_provider(provider.id, "gpt-5-mini", db_session)
    update_default_chat_naming_provider(provider.id, "gpt-5-mini", db_session)
    update_default_chat_naming_provider(provider.id, "gpt-5-nano", db_session)

    default = fetch_default_chat_naming_model(db_session)
    assert default is not None
    assert (default.name, default.is_visible) == ("gpt-5-nano", False)
    assert (
        sum(
            LLMModelFlowType.CHAT_NAMING in flows
            for flows in fetch_default_flows_by_model_id(db_session).values()
        )
        == 1
    )

    update_no_default_chat_naming_provider(db_session)
    update_no_default_chat_naming_provider(db_session)

    assert fetch_default_chat_naming_model(db_session) is None
    for model in [
        fetch_default_llm_model(db_session),
        fetch_default_search_selection_model(db_session),
    ]:
        assert model is not None
        assert (model.llm_provider_id, model.name, model.is_visible) == (
            provider.id,
            "gpt-5-mini",
            True,
        )


def test_hidden_chat_naming_default_survives_provider_edit_and_discovery(
    db_session: Session, provider: LLMProviderView
) -> None:
    update_default_chat_naming_provider(provider.id, "gpt-5-nano", db_session)

    _update_provider(db_session, provider)
    sync_model_configurations(
        db_session,
        provider.id,
        [
            SyncModelEntry(
                name="gpt-5-nano", display_name="GPT 5 nano", supports_reasoning=True
            )
        ],
    )

    default = fetch_default_chat_naming_model(db_session)
    assert default is not None
    assert (default.name, default.is_visible) == ("gpt-5-nano", False)
    assert {
        LLMModelFlowType.CHAT,
        LLMModelFlowType.REASONING,
        LLMModelFlowType.CHAT_NAMING,
    } <= set(default.llm_model_flow_types)


def test_chat_naming_only_default_can_be_hidden_but_shared_chat_default_cannot(
    db_session: Session, provider: LLMProviderView
) -> None:
    update_default_chat_naming_provider(provider.id, "gpt-5-mini", db_session)
    _update_provider(db_session, provider, mini_visible=False)
    default = fetch_default_chat_naming_model(db_session)
    assert default is not None
    assert (default.name, default.is_visible) == ("gpt-5-mini", False)

    update_default_provider(provider.id, "gpt-5-mini", db_session)
    with pytest.raises(ValueError, match="Cannot hide the default model"):
        _update_provider(db_session, provider, mini_visible=False)


def test_chat_naming_default_cannot_be_removed_during_provider_edit(
    db_session: Session, provider: LLMProviderView
) -> None:
    update_default_chat_naming_provider(provider.id, "gpt-5-nano", db_session)
    with pytest.raises(ValueError, match="Cannot remove the default model"):
        upsert_llm_provider(
            LLMProviderUpsertRequest(
                id=provider.id,
                provider="openai",
                model_configurations=[
                    ModelConfigurationUpsertRequest(name="gpt-5-mini", is_visible=True)
                ],
            ),
            db_session,
        )


def test_auto_sync_does_not_restore_hidden_chat_naming_only_default(
    db_session: Session, provider: LLMProviderView
) -> None:
    update_default_chat_naming_provider(provider.id, "gpt-5-nano", db_session)
    stored_provider = fetch_existing_llm_provider_by_id(provider.id, db_session)
    assert stored_provider is not None

    sync_auto_mode_models(
        db_session,
        stored_provider,
        LLMRecommendations(
            version="1",
            updated_at=datetime.now(timezone.utc),
            providers={
                "openai": LLMProviderRecommendation(
                    default_model=SimpleKnownModel(name="gpt-5-mini")
                )
            },
        ),
    )

    default = fetch_default_chat_naming_model(db_session)
    assert default is not None
    assert (default.name, default.is_visible) == ("gpt-5-nano", False)


@pytest.mark.parametrize("model_name", ["missing-model", ""])
def test_invalid_selection_preserves_existing_chat_naming_default(
    db_session: Session, provider: LLMProviderView, model_name: str
) -> None:
    update_default_chat_naming_provider(provider.id, "gpt-5-nano", db_session)
    with pytest.raises(ValueError, match="is not a valid model"):
        update_default_chat_naming_provider(provider.id, model_name, db_session)

    default = fetch_default_chat_naming_model(db_session)
    assert default is not None
    assert (default.llm_provider_id, default.name, default.is_visible) == (
        provider.id,
        "gpt-5-nano",
        False,
    )


@pytest.mark.parametrize("model_name", ["gpt-5-mini", "gpt-5-nano"])
def test_setting_craft_creates_one_mapping_and_makes_model_visible(
    db_session: Session, provider: LLMProviderView, model_name: str
) -> None:
    assert fetch_default_craft_model(db_session) is None
    assert (
        db_session.scalars(
            select(LLMModelFlow).where(
                LLMModelFlow.llm_model_flow_type == LLMModelFlowType.CRAFT
            )
        ).all()
        == []
    )

    update_default_craft_provider(provider.id, model_name, db_session)
    update_default_craft_provider(provider.id, model_name, db_session)
    db_session.rollback()

    default = fetch_default_craft_model(db_session)
    assert default is not None
    assert (default.llm_provider_id, default.name, default.is_visible) == (
        provider.id,
        model_name,
        True,
    )
    mappings = db_session.scalars(
        select(LLMModelFlow).where(
            LLMModelFlow.llm_model_flow_type == LLMModelFlowType.CRAFT
        )
    ).all()
    assert [(flow.model_configuration_id, flow.is_default) for flow in mappings] == [
        (default.id, True)
    ]
    assert LLMModelFlowType.CHAT in default.llm_model_flow_types


@pytest.mark.parametrize("model_name", ["missing-model", ""])
def test_invalid_selection_preserves_existing_craft_default(
    db_session: Session, provider: LLMProviderView, model_name: str
) -> None:
    update_default_craft_provider(provider.id, "gpt-5-nano", db_session)
    with pytest.raises(ValueError) as exc_info:
        update_default_craft_provider(provider.id, model_name, db_session)

    assert str(exc_info.value) == (
        f"Model '{model_name}' is not a valid model for provider_id={provider.id}"
    )
    default = fetch_default_craft_model(db_session)
    assert default is not None
    assert (default.llm_provider_id, default.name, default.is_visible) == (
        provider.id,
        "gpt-5-nano",
        True,
    )


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        (
            [("gpt-5-mini", "FAST", False), ("gpt-5-nano", "FAST", True)],
            {("gpt-5-mini", False), ("gpt-5-nano", True)},
        ),
        (
            [
                ("gpt-5-mini", "CHAT_NAMING", True),
                ("gpt-5-mini", "FAST", False),
                ("gpt-5-nano", "FAST", True),
            ],
            {("gpt-5-mini", True), ("gpt-5-nano", False)},
        ),
        (
            [
                ("gpt-5-mini", "CHAT_NAMING", False),
                ("gpt-5-nano", "CHAT_NAMING", False),
                ("gpt-5-nano", "FAST", True),
            ],
            {("gpt-5-mini", False), ("gpt-5-nano", True)},
        ),
        ([], set()),
        ([("gpt-5-mini", "CHAT_NAMING", True)], {("gpt-5-mini", True)}),
        (
            [("gpt-5-mini", "CHAT_NAMING", True), ("gpt-5-mini", "FAST", True)],
            {("gpt-5-mini", True)},
        ),
    ],
)
def test_migrate_draft_fast_preserves_naming_and_search_defaults(
    db_session: Session,
    provider: LLMProviderView,
    rows: list[tuple[str, str, bool]],
    expected: set[tuple[str, bool]],
) -> None:
    schema = CURRENT_TENANT_ID_CONTEXTVAR.get()
    db_session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    models = db_session.scalars(
        select(ModelConfiguration).where(
            ModelConfiguration.llm_provider_id == provider.id
        )
    ).all()
    model_ids = {model.name: model.id for model in models}
    visibility_before = {model.name: model.is_visible for model in models}
    for name, flow, is_default in [*rows, ("gpt-5-nano", "SEARCH_SELECTION", True)]:
        db_session.execute(
            text(
                "INSERT INTO llm_model_flow (model_configuration_id, llm_model_flow_type, is_default) "
                "VALUES (:model_id, :flow, :is_default)"
            ),
            {"model_id": model_ids[name], "flow": flow, "is_default": is_default},
        )

    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).parents[3] / "alembic")
    )
    revision = ScriptDirectory.from_config(config).get_revision("c92b67e56ec4")
    assert revision is not None
    with Operations.context(MigrationContext.configure(db_session.connection())):
        revision.module.upgrade()
        revision.module.upgrade()
        revision.module.downgrade()

    db_session.expire_all()
    assert (
        db_session.scalar(
            text(
                "SELECT COUNT(*) FROM llm_model_flow WHERE llm_model_flow_type = 'FAST'"
            )
        )
        == 0
    )
    naming_rows = db_session.execute(
        select(ModelConfiguration.name, LLMModelFlow.is_default)
        .join(LLMModelFlow)
        .where(LLMModelFlow.llm_model_flow_type == LLMModelFlowType.CHAT_NAMING)
    ).tuples()
    assert set(naming_rows) == expected
    selection = fetch_default_search_selection_model(db_session)
    assert selection is not None and selection.name == "gpt-5-nano"
    assert {model.name: model.is_visible for model in models} == visibility_before
