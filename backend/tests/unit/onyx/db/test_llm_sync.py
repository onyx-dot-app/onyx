"""Tests for LLM provider model sync functionality."""

from unittest.mock import MagicMock, patch

import pytest

from onyx.db.enums import LLMModelFlowType
from onyx.db.llm import _model_protocol_flows, sync_model_configurations
from onyx.server.manage.llm.models import SyncModelEntry


def _session_with_locked_provider(provider: MagicMock) -> MagicMock:
    """Session whose locked provider read returns ``provider``."""
    session = MagicMock()
    (
        session.query.return_value.populate_existing.return_value.filter.return_value.with_for_update.return_value.first.return_value
    ) = provider
    return session


def _make_existing_model(name: str, flow_types: list[LLMModelFlowType]) -> MagicMock:
    model = MagicMock()
    model.id = 42
    model.name = name
    model.llm_model_flow_types = flow_types
    return model


@pytest.mark.parametrize("stored", [None, {LLMModelFlowType.CHAT}])
def test_custom_name_does_not_remove_chat_capability(
    stored: set[LLMModelFlowType] | None,
) -> None:
    assert _model_protocol_flows("ollama", "instructor-chat", stored) == {
        LLMModelFlowType.CHAT
    }


@pytest.mark.parametrize("provider", ["openrouter", "vercel_ai_gateway"])
def test_unselected_discovered_model_does_not_gain_chat_on_save(provider: str) -> None:
    assert _model_protocol_flows(provider, "vendor/evaluation", set()) == set()


def test_decision_discovery_does_not_select_model() -> None:
    assert _model_protocol_flows(
        "openrouter",
        "vendor/decision",
        {LLMModelFlowType.CHAT},
    ) == {LLMModelFlowType.CHAT}


def test_vercel_gateway_chat_save_preserves_decision_only_flow() -> None:
    assert _model_protocol_flows(
        "vercel_ai_gateway",
        "openai/gpt-6-luna-decisions",
        {LLMModelFlowType.DECISION},
    ) == {LLMModelFlowType.DECISION}


class TestSyncModelConfigurations:
    """Tests for sync_model_configurations function."""

    def test_discovery_adds_chat_to_existing_decision_model(self) -> None:
        provider = MagicMock()
        provider.id = 1
        provider.provider = "openrouter"
        provider.model_configurations = [
            _make_existing_model("vendor/dual", [LLMModelFlowType.DECISION])
        ]
        session = MagicMock()
        with patch(
            "onyx.db.llm.fetch_existing_llm_provider_by_id", return_value=provider
        ):
            result = sync_model_configurations(
                session,
                1,
                [
                    SyncModelEntry(
                        name="vendor/dual",
                        display_name="Dual",
                        supports_chat=True,
                        supports_decisions=True,
                    )
                ],
            )
        assert result == 0
        assert session.execute.call_count == 1
        assert session.execute.call_args.args[0].compile().params == {
            "model_configuration_id": 42,
            "llm_model_flow_type": LLMModelFlowType.CHAT,
            "is_default": False,
        }
        session.commit.assert_called_once()

    def test_keeps_chat_capability_when_model_holds_chat_default(self) -> None:
        provider = MagicMock()
        provider.id = 1
        provider.provider = "openrouter"
        provider.model_configurations = [
            _make_existing_model("vendor/decision", [LLMModelFlowType.CHAT])
        ]
        session = MagicMock()
        with (
            patch(
                "onyx.db.llm.fetch_existing_llm_provider_by_id",
                return_value=provider,
            ),
            patch(
                "onyx.db.llm.fetch_default_flows_by_model_id",
                return_value={42: {LLMModelFlowType.CHAT}},
            ),
        ):
            result = sync_model_configurations(
                session,
                1,
                [
                    SyncModelEntry(
                        name="vendor/decision",
                        display_name="Decision",
                        supports_chat=False,
                        supports_decisions=True,
                    )
                ],
            )

        assert result == 0
        session.execute.assert_not_called()
        session.commit.assert_not_called()

    def test_inserts_new_models(self) -> None:
        """Test that new models are inserted."""
        # Mock the provider with no existing models
        mock_provider = MagicMock()
        mock_provider.id = 1
        mock_provider.model_configurations = []

        mock_session = MagicMock()

        with patch(
            "onyx.db.llm.fetch_existing_llm_provider_by_id", return_value=mock_provider
        ):
            models = [
                SyncModelEntry(
                    name="gpt-4",
                    display_name="GPT-4",
                    max_input_tokens=128000,
                    supports_image_input=True,
                ),
                SyncModelEntry(
                    name="gpt-6-sol",
                    display_name="GPT-6 Sol",
                    max_input_tokens=128000,
                    supports_image_input=True,
                ),
            ]

            # The bulk model insert returns the inserted (id, name) rows.
            mock_session.execute.return_value.all.return_value = [
                (1, "gpt-4"),
                (2, "gpt-6-sol"),
            ]

            result = sync_model_configurations(
                db_session=mock_session,
                provider_id=1,
                models=models,
            )

            assert result == 2  # Two new models
            # One bulk insert for the models, one for their flows.
            assert mock_session.execute.call_count == 2
            mock_session.commit.assert_called_once()

    def test_skips_existing_models(self) -> None:
        """Existing models with up-to-date flows are left untouched."""
        # Existing model already has the capabilities the source reports.
        mock_existing_model = _make_existing_model(
            "gpt-4", [LLMModelFlowType.CHAT, LLMModelFlowType.VISION]
        )

        mock_provider = MagicMock()
        mock_provider.id = 1
        mock_provider.model_configurations = [mock_existing_model]

        mock_session = MagicMock()

        with patch(
            "onyx.db.llm.fetch_existing_llm_provider_by_id", return_value=mock_provider
        ):
            models = [
                SyncModelEntry(
                    name="gpt-4",  # Existing - should be skipped
                    display_name="GPT-4",
                    max_input_tokens=128000,
                    supports_image_input=True,
                ),
                SyncModelEntry(
                    name="gpt-6-sol",  # New - should be inserted
                    display_name="GPT-6 Sol",
                    max_input_tokens=128000,
                    supports_image_input=True,
                ),
            ]

            mock_session.execute.return_value.all.return_value = [(2, "gpt-6-sol")]

            result = sync_model_configurations(
                db_session=mock_session,
                provider_id=1,
                models=models,
            )

            assert result == 1  # Only one new model
            # One bulk insert for the new model, one for its flows.
            assert mock_session.execute.call_count == 2

    def test_no_commit_when_no_new_models(self) -> None:
        """Test that commit is not called when nothing new or upgraded."""
        mock_existing_model = _make_existing_model(
            "gpt-4", [LLMModelFlowType.CHAT, LLMModelFlowType.VISION]
        )

        mock_provider = MagicMock()
        mock_provider.id = 1
        mock_provider.model_configurations = [mock_existing_model]

        mock_session = MagicMock()

        with patch(
            "onyx.db.llm.fetch_existing_llm_provider_by_id", return_value=mock_provider
        ):
            models = [
                SyncModelEntry(
                    name="gpt-4",  # Already exists
                    display_name="GPT-4",
                    max_input_tokens=128000,
                    supports_image_input=True,
                ),
            ]

            result = sync_model_configurations(
                db_session=mock_session,
                provider_id=1,
                models=models,
            )

            assert result == 0
            mock_session.commit.assert_not_called()

    @pytest.mark.parametrize("provider_name", ["nace", "typesafe"])
    def test_inserts_decision_flow_for_hosted_decision_provider(
        self, provider_name: str
    ) -> None:
        """A discovered hosted decision model is listed as a decision model."""
        mock_provider = MagicMock()
        mock_provider.id = 1
        mock_provider.provider = provider_name
        mock_provider.model_configurations = []
        mock_session = _session_with_locked_provider(mock_provider)
        mock_session.execute.return_value.all.return_value = [(1, "decision-model")]

        result = sync_model_configurations(
            db_session=mock_session,
            provider_id=1,
            models=[
                SyncModelEntry(
                    name="decision-model",
                    display_name="Decision Model",
                    supports_chat=False,
                    supports_decisions=True,
                )
            ],
            expected_provider=provider_name,
        )

        assert result == 1
        inserted_flow_types = {
            value
            for call in mock_session.execute.call_args_list
            for key, value in call.args[0].compile().params.items()
            if key.startswith("llm_model_flow_type")
        }
        assert inserted_flow_types == {LLMModelFlowType.DECISION}
        mock_session.commit.assert_called_once()

    def test_other_provider_discovery_does_not_insert_decision_flow(self) -> None:
        mock_provider = MagicMock()
        mock_provider.id = 1
        mock_provider.provider = "openrouter"
        mock_provider.model_configurations = []
        mock_session = MagicMock()
        mock_session.execute.return_value.all.return_value = [(1, "vendor/decision")]

        with patch(
            "onyx.db.llm.fetch_existing_llm_provider_by_id", return_value=mock_provider
        ):
            result = sync_model_configurations(
                db_session=mock_session,
                provider_id=1,
                models=[
                    SyncModelEntry(
                        name="vendor/decision",
                        display_name="Decision",
                        supports_chat=False,
                        supports_decisions=True,
                    )
                ],
            )

        assert result == 1
        inserted_flow_types = {
            value
            for call in mock_session.execute.call_args_list
            for key, value in call.args[0].compile().params.items()
            if key.startswith("llm_model_flow_type")
        }
        assert LLMModelFlowType.DECISION not in inserted_flow_types
        assert LLMModelFlowType.CHAT not in inserted_flow_types

    def test_rejects_sync_when_stored_provider_type_differs(self) -> None:
        """Models fetched for one provider must not land on another type."""
        mock_provider = MagicMock()
        mock_provider.id = 7
        mock_provider.provider = "openai"
        mock_provider.model_configurations = []
        mock_session = _session_with_locked_provider(mock_provider)

        with pytest.raises(ValueError, match="is openai, not nace"):
            sync_model_configurations(
                db_session=mock_session,
                provider_id=7,
                models=[
                    SyncModelEntry(
                        name="drex-max-v1.1",
                        display_name="Drex Max",
                        supports_chat=False,
                        supports_decisions=True,
                    )
                ],
                expected_provider="nace",
            )

        mock_session.execute.assert_not_called()
        mock_session.commit.assert_not_called()
        mock_session.rollback.assert_called_once()

    def test_sync_refuses_when_loaded_provider_type_changes(self) -> None:
        """A provider already in the session must be reloaded under the row lock.

        Without populate_existing the identity map still says nace, and the
        Nace model is inserted onto the provider that is now OpenAI.
        """
        from sqlalchemy import create_engine, text, update
        from sqlalchemy.dialects import postgresql
        from sqlalchemy.orm import Query, Session
        from sqlalchemy.pool import StaticPool

        from onyx.db.models import LLMProvider

        engine = create_engine(
            "sqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE llm_provider (
                        id INTEGER PRIMARY KEY,
                        name VARCHAR,
                        provider VARCHAR NOT NULL,
                        api_key BLOB,
                        api_base VARCHAR,
                        api_version VARCHAR,
                        zoom_voice_provider_id INTEGER,
                        custom_config TEXT,
                        default_model_name VARCHAR,
                        deployment_name VARCHAR,
                        is_default_provider BOOLEAN,
                        is_default_vision_provider BOOLEAN,
                        default_vision_model VARCHAR,
                        is_public BOOLEAN NOT NULL,
                        is_auto_mode BOOLEAN NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    "INSERT INTO llm_provider (provider, is_public, is_auto_mode)"
                    " VALUES ('nace', 1, 0)"
                )
            )

        reader = Session(engine)
        loaded = reader.query(LLMProvider).filter(LLMProvider.id == 1).one()
        with Session(engine) as writer:
            writer.execute(
                update(LLMProvider).where(LLMProvider.id == 1).values(provider="openai")
            )
            writer.commit()
        # The loaded object is unchanged until a refresh. That is the bug.
        assert loaded.provider == "nace"

        lock_sql: list[str] = []
        original_for_update = Query.with_for_update

        def record_lock(self: Query, *args: object, **kwargs: object) -> Query:
            locked = original_for_update(self, *args, **kwargs)
            lock_sql.append(str(locked.statement.compile(dialect=postgresql.dialect())))
            return locked

        try:
            with (
                patch.object(Query, "with_for_update", record_lock),
                pytest.raises(ValueError, match="is openai, not nace"),
            ):
                sync_model_configurations(
                    reader,
                    1,
                    [
                        SyncModelEntry(
                            name="drex-max-v1.1",
                            display_name="Drex Max",
                            supports_chat=False,
                            supports_decisions=True,
                        )
                    ],
                    expected_provider="nace",
                )
        finally:
            reader.close()

        assert lock_sql
        assert "FOR UPDATE" in lock_sql[0]

    def test_hosted_decision_provider_still_rejects_chat_discovery(self) -> None:
        mock_provider = MagicMock()
        mock_provider.id = 1
        mock_provider.provider = "nace"
        mock_provider.model_configurations = []
        mock_session = _session_with_locked_provider(mock_provider)

        with pytest.raises(ValueError, match="does not support chat"):
            sync_model_configurations(
                db_session=mock_session,
                provider_id=1,
                models=[
                    SyncModelEntry(
                        name="drex-max-v1.1",
                        display_name="Drex Max",
                        supports_chat=True,
                        supports_decisions=True,
                    )
                ],
                expected_provider="nace",
            )

        mock_session.execute.assert_not_called()

    def test_raises_on_missing_provider(self) -> None:
        """Test that ValueError is raised when provider not found."""
        mock_session = MagicMock()

        with patch("onyx.db.llm.fetch_existing_llm_provider_by_id", return_value=None):
            with pytest.raises(ValueError, match="not found"):
                sync_model_configurations(
                    db_session=mock_session,
                    provider_id=999,
                    models=[SyncModelEntry(name="model", display_name="Model")],
                )

    def test_inserts_reasoning_flow_when_supports_reasoning(self) -> None:
        """Test that a REASONING flow row is created when supports_reasoning=True."""
        mock_provider = MagicMock()
        mock_provider.id = 1
        mock_provider.model_configurations = []

        mock_session = MagicMock()

        with patch(
            "onyx.db.llm.fetch_existing_llm_provider_by_id", return_value=mock_provider
        ):
            models = [
                SyncModelEntry(
                    name="deepseek-r1",
                    display_name="DeepSeek R1",
                    max_input_tokens=65536,
                    supports_image_input=True,
                    supports_reasoning=True,
                ),
            ]

            mock_session.execute.return_value.all.return_value = [(1, "deepseek-r1")]

            result = sync_model_configurations(
                db_session=mock_session,
                provider_id=1,
                models=models,
            )

            assert result == 1
            # One bulk insert for the model, one for its CHAT, VISION and
            # REASONING flows.
            assert mock_session.execute.call_count == 2
            inserted_flow_types = {
                value
                for call in mock_session.execute.call_args_list
                for key, value in call.args[0].compile().params.items()
                if key.startswith("llm_model_flow_type")
            }
            assert inserted_flow_types == {
                LLMModelFlowType.CHAT,
                LLMModelFlowType.VISION,
                LLMModelFlowType.REASONING,
            }
            mock_session.commit.assert_called_once()

    def test_handles_missing_optional_fields(self) -> None:
        """Test that optional fields default correctly."""
        mock_provider = MagicMock()
        mock_provider.id = 1
        mock_provider.model_configurations = []

        mock_session = MagicMock()

        with patch(
            "onyx.db.llm.fetch_existing_llm_provider_by_id", return_value=mock_provider
        ):
            # Model with only required fields (max_input_tokens and supports_image_input default)
            models = [
                SyncModelEntry(
                    name="model-1",
                    display_name="Model 1",
                ),
            ]

            result = sync_model_configurations(
                db_session=mock_session,
                provider_id=1,
                models=models,
            )

            assert result == 1
            # Verify execute was called with correct defaults
            call_args = mock_session.execute.call_args
            assert call_args is not None

    def test_upgrades_existing_model_vision_flow(self) -> None:
        """Existing model gains a VISION flow when the source newly reports it.

        Repairs rows synced before the source exposed vision (e.g. a Bifrost
        model added before vision detection resolved correctly). Returns 0 new
        models but commits the added flow.
        """
        mock_existing_model = _make_existing_model("gemini", [LLMModelFlowType.CHAT])

        mock_provider = MagicMock()
        mock_provider.id = 1
        mock_provider.model_configurations = [mock_existing_model]

        mock_session = MagicMock()

        with patch(
            "onyx.db.llm.fetch_existing_llm_provider_by_id", return_value=mock_provider
        ):
            models = [
                SyncModelEntry(
                    name="gemini",
                    display_name="Gemini",
                    supports_image_input=True,
                ),
            ]

            result = sync_model_configurations(
                db_session=mock_session,
                provider_id=1,
                models=models,
            )

            assert result == 0  # No new models, only an upgraded flow
            assert mock_session.execute.call_count == 1  # One VISION flow insert
            mock_session.commit.assert_called_once()

    def test_marks_existing_model_as_router(self) -> None:
        """An existing row gains is_router when the source newly reports it
        (e.g. a row synced before router detection existed). Returns 0 new
        models but commits the flag."""
        mock_existing_model = _make_existing_model(
            "openrouter/auto", [LLMModelFlowType.CHAT]
        )
        mock_existing_model.is_router = False

        mock_provider = MagicMock()
        mock_provider.id = 1
        mock_provider.model_configurations = [mock_existing_model]

        mock_session = MagicMock()

        with patch(
            "onyx.db.llm.fetch_existing_llm_provider_by_id", return_value=mock_provider
        ):
            models = [
                SyncModelEntry(
                    name="openrouter/auto",
                    display_name="Auto Router",
                    is_router=True,
                ),
            ]

            result = sync_model_configurations(
                db_session=mock_session,
                provider_id=1,
                models=models,
            )

            assert result == 0
            assert mock_existing_model.is_router is True
            mock_session.commit.assert_called_once()

    def test_does_not_remove_flows(self) -> None:
        """Capability flags are only added, never removed: a model that already
        has VISION keeps it even if the source omits it this fetch."""
        mock_existing_model = _make_existing_model(
            "gemini", [LLMModelFlowType.CHAT, LLMModelFlowType.VISION]
        )

        mock_provider = MagicMock()
        mock_provider.id = 1
        mock_provider.model_configurations = [mock_existing_model]

        mock_session = MagicMock()

        with patch(
            "onyx.db.llm.fetch_existing_llm_provider_by_id", return_value=mock_provider
        ):
            models = [
                SyncModelEntry(
                    name="gemini",
                    display_name="Gemini",
                    supports_image_input=False,
                ),
            ]

            result = sync_model_configurations(
                db_session=mock_session,
                provider_id=1,
                models=models,
            )

            assert result == 0
            mock_session.execute.assert_not_called()
            mock_session.commit.assert_not_called()
