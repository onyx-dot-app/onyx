from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.db.dal import DAL


class TestDAL:
    """Tests for the base DAL class."""

    def test_commit_delegates_to_session(self) -> None:
        session = MagicMock()
        dal = DAL(session)
        dal.commit()
        session.commit.assert_called_once()

    def test_flush_delegates_to_session(self) -> None:
        session = MagicMock()
        dal = DAL(session)
        dal.flush()
        session.flush.assert_called_once()

    def test_rollback_delegates_to_session(self) -> None:
        session = MagicMock()
        dal = DAL(session)
        dal.rollback()
        session.rollback.assert_called_once()

    def test_session_property(self) -> None:
        session = MagicMock()
        dal = DAL(session)
        assert dal.session is session

    @patch("onyx.db.dal.get_session_with_tenant")
    def test_from_tenant_context_manager(self, mock_get_session: MagicMock) -> None:
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        with DAL.from_tenant("test_tenant") as dal:
            assert dal.session is mock_session

        mock_get_session.assert_called_once_with(tenant_id="test_tenant")
