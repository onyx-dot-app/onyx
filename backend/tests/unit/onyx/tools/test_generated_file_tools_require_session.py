"""Tools that write CHAT_IMAGE_GEN files must be built with the owning chat
session. A file saved without the stamp would be readable by every user."""

from uuid import uuid4

import pytest

from onyx.tools.tool_constructor import CustomToolConfig, _require_chat_session_id


def test_returns_session_id_when_present() -> None:
    session_id = uuid4()
    config = CustomToolConfig(chat_session_id=session_id)

    assert _require_chat_session_id(config, "ImageGenerationTool") == session_id


def test_raises_without_config() -> None:
    with pytest.raises(ValueError, match="chat_session_id"):
        _require_chat_session_id(None, "PythonTool")


def test_raises_when_config_has_no_session() -> None:
    with pytest.raises(ValueError, match="chat_session_id"):
        _require_chat_session_id(CustomToolConfig(), "PythonTool")
