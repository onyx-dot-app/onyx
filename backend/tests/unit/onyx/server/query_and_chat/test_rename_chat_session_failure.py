from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.query_and_chat import chat_backend
from onyx.server.query_and_chat.models import ChatRenameRequest

_MODULE = "onyx.server.query_and_chat.chat_backend"


def test_failed_regeneration_is_an_onyx_error() -> None:
    request = MagicMock()
    request.headers = {}
    with (
        patch(f"{_MODULE}.get_session_with_current_tenant"),
        patch(f"{_MODULE}.get_chat_session_by_id"),
        patch(f"{_MODULE}.record_mode_persists_content", return_value=True),
        patch(f"{_MODULE}.name_chat_session", side_effect=RuntimeError("llm down")),
        pytest.raises(OnyxError) as error,
    ):
        chat_backend.rename_chat_session(
            rename_req=ChatRenameRequest(
                chat_session_id=uuid4(), name=None, regenerate=True
            ),
            request=request,
            user=MagicMock(),
        )

    assert error.value.error_code == OnyxErrorCode.LLM_PROVIDER_ERROR
