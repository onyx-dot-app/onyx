from unittest.mock import MagicMock, patch
import pytest
from onyx.server.features.persona.api import get_persona_avatar
from onyx.error_handlers import OnyxError


def test_get_persona_avatar_handles_none_user():
    request = MagicMock()
    request.headers.get.return_value = None
    db_session = MagicMock()

    with patch("onyx.server.features.persona.api.get_persona_by_id", side_effect=ValueError("Not found")):
        with pytest.raises(OnyxError) as exc_info:
            get_persona_avatar(
                persona_id=999,
                request=request,
                user=None,
                db_session=db_session,
            )
        assert exc_info.value.status_code == 404
