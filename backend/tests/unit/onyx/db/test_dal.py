from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.db.dal import DAL


class TestDALSessionDelegation:
    """Verify that DAL methods delegate correctly to the underlying session."""

    def test_commit(self) -> None:
        session = MagicMock()
        dal = DAL(session)
        dal.commit()
        session.commit.assert_called_once()

    def test_flush(self) -> None:
        session = MagicMock()
        dal = DAL(session)
        dal.flush()
        session.flush.assert_called_once()

    def test_rollback(self) -> None:
        session = MagicMock()
        dal = DAL(session)
        dal.rollback()
        session.rollback.assert_called_once()

    def test_session_property_exposes_underlying_session(self) -> None:
        session = MagicMock()
        dal = DAL(session)
        assert dal.session is session

    def test_commit_propagates_exception(self) -> None:
        session = MagicMock()
        session.commit.side_effect = RuntimeError("db error")
        dal = DAL(session)
        with pytest.raises(RuntimeError, match="db error"):
            dal.commit()


class TestDALFromTenant:
    """Verify the from_tenant context manager lifecycle."""

    @patch("onyx.db.dal.get_session_with_tenant")
    def test_yields_dal_with_tenant_session(self, mock_get_session: MagicMock) -> None:
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        with DAL.from_tenant("tenant_abc") as dal:
            assert isinstance(dal, DAL)
            assert dal.session is mock_session

        mock_get_session.assert_called_once_with(tenant_id="tenant_abc")

    @patch("onyx.db.dal.get_session_with_tenant")
    def test_session_closed_after_context_exits(
        self, mock_get_session: MagicMock
    ) -> None:
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        with DAL.from_tenant("tenant_abc"):
            pass

        mock_get_session.return_value.__exit__.assert_called_once()

    @patch("onyx.db.dal.get_session_with_tenant")
    def test_session_closed_on_exception(self, mock_get_session: MagicMock) -> None:
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        with pytest.raises(ValueError):
            with DAL.from_tenant("tenant_abc"):
                raise ValueError("something broke")

        mock_get_session.return_value.__exit__.assert_called_once()

    @patch("onyx.db.dal.get_session_with_tenant")
    def test_subclass_from_tenant_returns_subclass_instance(
        self, mock_get_session: MagicMock
    ) -> None:
        """from_tenant uses cls(), so subclasses should get their own type back."""
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        class MyDAL(DAL):
            pass

        with MyDAL.from_tenant("tenant_abc") as dal:
            assert isinstance(dal, MyDAL)

    @patch("onyx.db.dal.get_session_with_tenant")
    def test_uncommitted_changes_not_auto_committed(
        self, mock_get_session: MagicMock
    ) -> None:
        """Exiting the context manager should NOT auto-commit."""
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        with DAL.from_tenant("tenant_abc"):
            pass

        mock_session.commit.assert_not_called()
