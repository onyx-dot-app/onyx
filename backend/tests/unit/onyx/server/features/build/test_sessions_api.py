from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.api import sessions_api


class TestBuildSessionExportErrors:
    @pytest.mark.parametrize(
        ("endpoint", "manager_method"),
        [
            (sessions_api.export_docx, "export_docx"),
            (sessions_api.export_odt, "export_odt"),
        ],
    )
    def test_export_endpoint_maps_access_denied_to_onyx_error(
        self,
        endpoint: Callable[..., object],
        manager_method: str,
    ) -> None:
        user = SimpleNamespace(id=uuid4())

        with patch.object(sessions_api, "SessionManager") as mock_manager_cls:
            getattr(mock_manager_cls.return_value, manager_method).side_effect = ValueError(
                "Access denied"
            )

            with pytest.raises(OnyxError) as exc_info:
                endpoint(
                    session_id=uuid4(),
                    path="notes.md",
                    user=user,
                    db_session=MagicMock(),
                )

        assert exc_info.value.error_code is OnyxErrorCode.UNAUTHORIZED
        assert exc_info.value.detail == "Access denied"

    @pytest.mark.parametrize(
        ("endpoint", "manager_method"),
        [
            (sessions_api.export_docx, "export_docx"),
            (sessions_api.export_odt, "export_odt"),
        ],
    )
    def test_export_endpoint_maps_other_value_errors_to_invalid_input(
        self,
        endpoint: Callable[..., object],
        manager_method: str,
    ) -> None:
        user = SimpleNamespace(id=uuid4())

        with patch.object(sessions_api, "SessionManager") as mock_manager_cls:
            getattr(mock_manager_cls.return_value, manager_method).side_effect = ValueError(
                "Only markdown files can be exported"
            )

            with pytest.raises(OnyxError) as exc_info:
                endpoint(
                    session_id=uuid4(),
                    path="notes.txt",
                    user=user,
                    db_session=MagicMock(),
                )

        assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT
        assert exc_info.value.detail == "Only markdown files can be exported"

    @pytest.mark.parametrize(
        ("endpoint", "manager_method"),
        [
            (sessions_api.export_docx, "export_docx"),
            (sessions_api.export_odt, "export_odt"),
        ],
    )
    def test_export_endpoint_maps_missing_result_to_not_found(
        self,
        endpoint: Callable[..., object],
        manager_method: str,
    ) -> None:
        user = SimpleNamespace(id=uuid4())

        with patch.object(sessions_api, "SessionManager") as mock_manager_cls:
            getattr(mock_manager_cls.return_value, manager_method).return_value = None

            with pytest.raises(OnyxError) as exc_info:
                endpoint(
                    session_id=uuid4(),
                    path="missing.md",
                    user=user,
                    db_session=MagicMock(),
                )

        assert exc_info.value.error_code is OnyxErrorCode.NOT_FOUND
        assert exc_info.value.detail == "File not found"
