from unittest.mock import MagicMock
from unittest.mock import patch


def test_setup_postgres_calls_consumer_default_llm_seed() -> None:
    with (
        patch("onyx.setup.create_initial_public_credential"),
        patch("onyx.setup.create_initial_default_connector"),
        patch("onyx.setup.associate_default_cc_pair"),
        patch("onyx.setup.GEN_AI_API_KEY", None),
        patch("onyx.setup.seed_consumer_default_llm_provider") as consumer_seed_mock,
    ):
        from onyx.setup import setup_postgres

        db_session = MagicMock()
        setup_postgres(db_session)

    consumer_seed_mock.assert_called_once_with(db_session)
