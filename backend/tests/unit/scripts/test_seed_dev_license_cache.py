"""Seeding a dev license must drop the cached license details, or a running
instance keeps serving the license it had before."""

from unittest.mock import MagicMock, patch

import pytest
from scripts import seed_dev_license


def test_seeding_drops_the_cached_license(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONYX_DEV_LICENSE", "license-blob")
    calls: MagicMock = MagicMock()
    with (
        patch.object(seed_dev_license, "normalize_license_file", return_value="blob"),
        patch.object(seed_dev_license, "verify_license_signature"),
        patch.object(seed_dev_license, "SqlEngine"),
        patch.object(seed_dev_license, "get_session_with_current_tenant"),
        patch.object(seed_dev_license, "upsert_license") as upsert,
        patch.object(seed_dev_license, "invalidate_license_cache") as invalidate,
    ):
        calls.attach_mock(upsert, "upsert")
        calls.attach_mock(invalidate, "invalidate")
        seed_dev_license.main()

    assert [call[0] for call in calls.mock_calls] == ["upsert", "invalidate"]


def test_an_empty_license_seeds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONYX_DEV_LICENSE", "")
    with (
        patch.object(seed_dev_license, "upsert_license") as upsert,
        patch.object(seed_dev_license, "invalidate_license_cache") as invalidate,
    ):
        seed_dev_license.main()

    upsert.assert_not_called()
    invalidate.assert_not_called()
