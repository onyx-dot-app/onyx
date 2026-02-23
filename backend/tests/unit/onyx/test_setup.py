"""Unit tests for code interpreter server seeding in setup_postgres."""

from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.setup import setup_postgres


MODULE = "onyx.setup"

# Patch all the other setup_postgres calls so we only test the code interpreter logic
COMMON_PATCHES = [
    patch(f"{MODULE}.create_initial_public_credential"),
    patch(f"{MODULE}.create_initial_default_connector"),
    patch(f"{MODULE}.associate_default_cc_pair"),
    patch(f"{MODULE}.GEN_AI_API_KEY", None),
]


def _apply_patches(patches: list) -> list:  # type: ignore
    mocks = [p.start() for p in patches]
    return mocks


def _stop_patches(patches: list) -> None:  # type: ignore
    for p in patches:
        p.stop()


class TestSetupPostgresCodeInterpreterSeeding:
    """Tests for the code interpreter seeding block in setup_postgres."""

    def test_inserts_server_when_url_set_and_no_existing_servers(self) -> None:
        """When CODE_INTERPRETER_BASE_URL is set and no servers exist,
        a new server should be inserted."""
        _apply_patches(COMMON_PATCHES)
        try:
            mock_session = MagicMock()
            with (
                patch(
                    f"{MODULE}.CODE_INTERPRETER_BASE_URL",
                    "http://code-interpreter:8080",
                ),
                patch(
                    f"{MODULE}.fetch_code_interpreter_servers",
                    return_value=[],
                ) as mock_fetch,
                patch(
                    f"{MODULE}.insert_code_interpreter_server",
                ) as mock_insert,
            ):
                setup_postgres(mock_session)

                mock_fetch.assert_called_once_with(mock_session)
                mock_insert.assert_called_once_with(
                    db_session=mock_session,
                    url="http://code-interpreter:8080",
                    server_enabled=True,
                )
        finally:
            _stop_patches(COMMON_PATCHES)

    def test_skips_insert_when_url_not_set(self) -> None:
        """When CODE_INTERPRETER_BASE_URL is None, no server should be inserted."""
        _apply_patches(COMMON_PATCHES)
        try:
            mock_session = MagicMock()
            with (
                patch(f"{MODULE}.CODE_INTERPRETER_BASE_URL", None),
                patch(
                    f"{MODULE}.fetch_code_interpreter_servers",
                ) as mock_fetch,
                patch(
                    f"{MODULE}.insert_code_interpreter_server",
                ) as mock_insert,
            ):
                setup_postgres(mock_session)

                mock_fetch.assert_not_called()
                mock_insert.assert_not_called()
        finally:
            _stop_patches(COMMON_PATCHES)

    def test_skips_insert_when_servers_already_exist(self) -> None:
        """When servers already exist in the DB, no new server should be inserted."""
        _apply_patches(COMMON_PATCHES)
        try:
            mock_session = MagicMock()
            existing_server = MagicMock()
            with (
                patch(
                    f"{MODULE}.CODE_INTERPRETER_BASE_URL",
                    "http://code-interpreter:8080",
                ),
                patch(
                    f"{MODULE}.fetch_code_interpreter_servers",
                    return_value=[existing_server],
                ) as mock_fetch,
                patch(
                    f"{MODULE}.insert_code_interpreter_server",
                ) as mock_insert,
            ):
                setup_postgres(mock_session)

                mock_fetch.assert_called_once_with(mock_session)
                mock_insert.assert_not_called()
        finally:
            _stop_patches(COMMON_PATCHES)

    def test_skips_insert_when_url_is_empty_string(self) -> None:
        """When CODE_INTERPRETER_BASE_URL is an empty string (falsy),
        no server should be inserted."""
        _apply_patches(COMMON_PATCHES)
        try:
            mock_session = MagicMock()
            with (
                patch(f"{MODULE}.CODE_INTERPRETER_BASE_URL", ""),
                patch(
                    f"{MODULE}.fetch_code_interpreter_servers",
                ) as mock_fetch,
                patch(
                    f"{MODULE}.insert_code_interpreter_server",
                ) as mock_insert,
            ):
                setup_postgres(mock_session)

                mock_fetch.assert_not_called()
                mock_insert.assert_not_called()
        finally:
            _stop_patches(COMMON_PATCHES)
