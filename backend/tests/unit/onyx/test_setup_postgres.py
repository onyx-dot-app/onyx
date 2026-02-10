from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx import setup as setup_lib


def test_setup_postgres_does_not_seed_dev_provider_when_provider_exists() -> None:
    """Regression test: existing providers should prevent local dev provider reseeding."""
    db_session = MagicMock()
    db_session.scalar.return_value = 123  # Existing provider id

    with (
        patch.object(setup_lib, "GEN_AI_API_KEY", "test-api-key"),
        patch.object(setup_lib, "GEN_AI_MODEL_VERSION", None),
        patch.object(setup_lib, "create_initial_public_credential"),
        patch.object(setup_lib, "create_initial_default_connector"),
        patch.object(setup_lib, "associate_default_cc_pair"),
        patch.object(setup_lib, "fetch_default_llm_model", return_value=None),
        patch.object(setup_lib, "_backfill_llm_model_flow_mappings", return_value=True),
        patch.object(setup_lib, "upsert_llm_provider") as mock_upsert,
        patch.object(setup_lib, "update_default_provider") as mock_update_default,
    ):
        setup_lib.setup_postgres(db_session)

    mock_upsert.assert_not_called()
    mock_update_default.assert_not_called()


def test_setup_postgres_seeds_dev_provider_on_fresh_install() -> None:
    db_session = MagicMock()
    db_session.scalar.return_value = None  # No providers yet

    with (
        patch.object(setup_lib, "GEN_AI_API_KEY", "test-api-key"),
        patch.object(setup_lib, "GEN_AI_MODEL_VERSION", None),
        patch.object(setup_lib, "create_initial_public_credential"),
        patch.object(setup_lib, "create_initial_default_connector"),
        patch.object(setup_lib, "associate_default_cc_pair"),
        patch.object(setup_lib, "fetch_default_llm_model", return_value=None),
        patch.object(setup_lib, "get_openai_model_names", return_value=["gpt-4o-mini"]),
        patch.object(
            setup_lib, "upsert_llm_provider", return_value=SimpleNamespace(id=17)
        ) as mock_upsert,
        patch.object(setup_lib, "update_default_provider") as mock_update_default,
    ):
        setup_lib.setup_postgres(db_session)

    mock_upsert.assert_called_once()
    request = mock_upsert.call_args.kwargs["llm_provider_upsert_request"]
    assert request.name == "DevEnvPresetOpenAI"
    mock_update_default.assert_called_once_with(provider_id=17, db_session=db_session)


def test_setup_postgres_attempts_flow_backfill_when_provider_exists_and_no_default() -> (
    None
):
    db_session = MagicMock()
    db_session.scalar.return_value = 123  # Existing provider id

    with (
        patch.object(setup_lib, "GEN_AI_API_KEY", "test-api-key"),
        patch.object(setup_lib, "GEN_AI_MODEL_VERSION", None),
        patch.object(setup_lib, "create_initial_public_credential"),
        patch.object(setup_lib, "create_initial_default_connector"),
        patch.object(setup_lib, "associate_default_cc_pair"),
        patch.object(setup_lib, "fetch_default_llm_model", side_effect=[None, None]),
        patch.object(
            setup_lib, "_backfill_llm_model_flow_mappings", return_value=True
        ) as mock_backfill,
        patch.object(setup_lib, "upsert_llm_provider") as mock_upsert,
    ):
        setup_lib.setup_postgres(db_session)

    mock_backfill.assert_called_once_with(db_session)
    mock_upsert.assert_not_called()
