from io import BytesIO
from unittest.mock import MagicMock, patch
import pytest
from onyx.configs.constants import FileOrigin
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.persona.api import get_persona_avatar


def test_get_persona_avatar_not_found():
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


def test_get_persona_avatar_private_anonymous_rejected():
    request = MagicMock()
    request.headers.get.return_value = None
    db_session = MagicMock()

    mock_persona = MagicMock()
    mock_persona.is_public = False
    mock_persona.uploaded_image_id = "img-123"

    with patch("onyx.server.features.persona.api.get_persona_by_id", return_value=mock_persona):
        with pytest.raises(OnyxError) as exc_info:
            get_persona_avatar(
                persona_id=1,
                request=request,
                user=None,
                db_session=db_session,
            )
        assert exc_info.value.status_code == 404


def test_get_persona_avatar_public_anonymous_success():
    request = MagicMock()
    request.headers.get.return_value = None
    db_session = MagicMock()

    mock_persona = MagicMock()
    mock_persona.is_public = True
    mock_persona.uploaded_image_id = "img-123"

    mock_file_record = MagicMock()
    mock_file_record.file_origin = FileOrigin.CHAT_UPLOAD
    mock_file_record.file_type = "image/png"

    mock_file_store = MagicMock()
    mock_file_store.read_file.return_value = BytesIO(b"png-data")

    with (
        patch("onyx.server.features.persona.api.get_persona_by_id", return_value=mock_persona),
        patch("onyx.server.features.persona.api.get_filerecord_by_file_id_optional", return_value=mock_file_record),
        patch("onyx.server.features.persona.api.get_default_file_store", return_value=mock_file_store),
    ):
        response = get_persona_avatar(
            persona_id=1,
            request=request,
            user=None,
            db_session=db_session,
        )
        assert response.status_code == 200
        assert response.media_type == "image/png"

