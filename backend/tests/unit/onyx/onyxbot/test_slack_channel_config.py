from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.db.slack_channel_config import create_slack_channel_persona


def test_create_slack_channel_persona_reuses_existing_persona() -> None:
    db_session = MagicMock()
    existing_persona = MagicMock()
    existing_persona.id = 42
    db_session.scalar.return_value = existing_persona

    fake_tool = MagicMock()
    fake_tool.id = 7

    with (
        patch(
            "onyx.db.slack_channel_config.get_builtin_tool",
            return_value=fake_tool,
        ),
        patch("onyx.db.slack_channel_config.upsert_persona") as mock_upsert,
    ):
        mock_upsert.return_value = MagicMock()

        create_slack_channel_persona(
            db_session=db_session,
            channel_name="general",
            document_set_ids=[1],
        )

    mock_upsert.assert_called_once()
    assert mock_upsert.call_args.kwargs["persona_id"] == existing_persona.id
