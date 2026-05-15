from collections.abc import Callable
from unittest.mock import MagicMock

from google.auth.exceptions import RefreshError

from onyx.connectors.google_utils.resources import ImpersonationError
from onyx.connectors.google_utils.resources import make_user_removal_checker
from onyx.connectors.google_utils.resources import UserRemovedError
from onyx.connectors.google_utils.shared_constants import MISSING_SCOPES_ERROR_STR


def _make_checker(
    get_fresh_emails: Callable[[], list[str]] | None = None,
    user_email: str = "user@example.com",
) -> Callable[[], bool]:
    return make_user_removal_checker(
        user_email=user_email, get_fresh_emails=get_fresh_emails
    )


class TestUserRemovalChecker:
    def test_returns_false_without_callback(self) -> None:
        is_removed = _make_checker(get_fresh_emails=None)
        assert is_removed() is False

    def test_returns_true_when_email_absent(self) -> None:
        callback = MagicMock(return_value=["other@example.com"])
        is_removed = _make_checker(
            get_fresh_emails=callback, user_email="gone@example.com"
        )
        assert is_removed() is True
        callback.assert_called_once()

    def test_returns_false_when_email_present(self) -> None:
        callback = MagicMock(return_value=["user@example.com", "other@example.com"])
        is_removed = _make_checker(
            get_fresh_emails=callback, user_email="user@example.com"
        )
        assert is_removed() is False
        callback.assert_called_once()

    def test_returns_false_when_callback_fails(self) -> None:
        callback = MagicMock(side_effect=Exception("admin sdk down"))
        is_removed = _make_checker(
            get_fresh_emails=callback, user_email="user@example.com"
        )
        assert is_removed() is False

    def test_callback_called_at_most_once(self) -> None:
        callback = MagicMock(return_value=["user@example.com"])
        is_removed = _make_checker(
            get_fresh_emails=callback, user_email="user@example.com"
        )
        is_removed()
        is_removed()
        is_removed()
        callback.assert_called_once()

    def test_cached_result_used_on_repeated_calls(self) -> None:
        callback = MagicMock(return_value=["other@example.com"])
        is_removed = _make_checker(
            get_fresh_emails=callback, user_email="gone@example.com"
        )
        assert is_removed() is True
        assert is_removed() is True
        callback.assert_called_once()


class TestImpersonationErrorClasses:
    def test_message_does_not_contain_missing_scopes_string(self) -> None:
        original = RefreshError(MISSING_SCOPES_ERROR_STR)
        err = ImpersonationError("u@example.com", original)
        assert MISSING_SCOPES_ERROR_STR not in str(err)

    def test_original_error_preserved(self) -> None:
        original = RefreshError("some message")
        err = ImpersonationError("u@example.com", original)
        assert err.original is original

    def test_user_removed_is_subclass_of_impersonation(self) -> None:
        original = RefreshError("x")
        err = UserRemovedError("u@example.com", original)
        assert isinstance(err, ImpersonationError)
