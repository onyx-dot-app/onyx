"""Search receipts are on by default and can only be turned off through the flag."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from ee.onyx.feature_flags import posthog_provider
from ee.onyx.feature_flags.posthog_provider import PostHogFeatureFlagProvider
from onyx.chat.search_receipts import SEARCH_RECEIPTS_FLAG, search_receipts_enabled
from onyx.feature_flags.interface import (
    ANONYMOUS_USER_FLAG_ID,
    NoOpFeatureFlagProvider,
)

MODULE = "onyx.chat.search_receipts"


def _user() -> MagicMock:
    return MagicMock(id=uuid4(), email="user@example.com")


def test_enabled_without_a_flag_provider() -> None:
    with (
        patch(
            f"{MODULE}.get_default_feature_flag_provider",
            return_value=NoOpFeatureFlagProvider(),
        ),
        patch(f"{MODULE}.get_current_tenant_id", return_value="public"),
    ):
        assert search_receipts_enabled(_user()) is True
        assert search_receipts_enabled(None) is True


@pytest.mark.parametrize(
    ("posthog_answer", "expected"),
    [
        (None, True),  # flag not defined in PostHog: default wins
        (True, True),
        (False, False),  # only an explicit False turns receipts off
    ],
)
def test_posthog_flag_only_overrides_the_default(
    posthog_answer: bool | None, expected: bool
) -> None:
    fake_posthog = MagicMock()
    fake_posthog.feature_enabled.return_value = posthog_answer
    user = _user()
    with (
        patch.object(posthog_provider, "posthog", fake_posthog),
        patch(
            f"{MODULE}.get_default_feature_flag_provider",
            return_value=PostHogFeatureFlagProvider(),
        ),
        patch(f"{MODULE}.get_current_tenant_id", return_value="tenant-1"),
    ):
        assert search_receipts_enabled(user) is expected
    args, kwargs = fake_posthog.feature_enabled.call_args
    assert args == (SEARCH_RECEIPTS_FLAG, str(user.id))
    assert kwargs["person_properties"] == {
        "tenant_id": "tenant-1",
        "email": "user@example.com",
    }


def test_posthog_error_falls_back_to_default() -> None:
    fake_posthog = MagicMock()
    fake_posthog.feature_enabled.side_effect = RuntimeError("posthog down")
    with (
        patch.object(posthog_provider, "posthog", fake_posthog),
        patch(
            f"{MODULE}.get_default_feature_flag_provider",
            return_value=PostHogFeatureFlagProvider(),
        ),
        patch(f"{MODULE}.get_current_tenant_id", return_value="tenant-1"),
    ):
        assert search_receipts_enabled(_user()) is True


def test_posthog_not_configured_falls_back_to_default() -> None:
    with (
        patch.object(posthog_provider, "posthog", None),
        patch(
            f"{MODULE}.get_default_feature_flag_provider",
            return_value=PostHogFeatureFlagProvider(),
        ),
        patch(f"{MODULE}.get_current_tenant_id", return_value="tenant-1"),
    ):
        assert search_receipts_enabled(_user()) is True


def test_anonymous_user_uses_fixed_distinct_id() -> None:
    fake_posthog = MagicMock()
    fake_posthog.feature_enabled.return_value = False
    with patch.object(posthog_provider, "posthog", fake_posthog):
        result = (
            PostHogFeatureFlagProvider().feature_enabled_for_user_tenant_or_default(
                SEARCH_RECEIPTS_FLAG, None, "tenant-1", default=True
            )
        )
    assert result is False
    args, _ = fake_posthog.feature_enabled.call_args
    assert args == (SEARCH_RECEIPTS_FLAG, str(ANONYMOUS_USER_FLAG_ID))
