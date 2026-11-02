"""Seeding a dev license must republish the cached license details, or a
running instance keeps serving the license it had before."""

from unittest.mock import MagicMock, patch

import pytest
from scripts import seed_dev_license


def test_seeding_republishes_the_cached_license(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONYX_DEV_LICENSE", "license-blob")
    calls: MagicMock = MagicMock()
    with (
        patch.object(seed_dev_license, "normalize_license_file", return_value="blob"),
        patch.object(seed_dev_license, "verify_license_signature"),
        patch.object(seed_dev_license, "SqlEngine") as engine,
        patch.object(seed_dev_license, "get_session_with_current_tenant"),
        patch.object(seed_dev_license, "upsert_license") as upsert,
        patch.object(seed_dev_license, "publish_license_metadata") as publish,
    ):
        calls.attach_mock(upsert, "upsert")
        calls.attach_mock(publish, "publish")
        seed_dev_license.main()

    assert [call[0] for call in calls.mock_calls] == ["upsert", "publish"]
    # Publishing opens a second session inside the first, plus a lock connection.
    pool: dict[str, int] = engine.init_engine.call_args.kwargs
    assert pool["pool_size"] + pool["max_overflow"] >= 3


def test_an_empty_license_seeds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONYX_DEV_LICENSE", "")
    with (
        patch.object(seed_dev_license, "upsert_license") as upsert,
        patch.object(seed_dev_license, "publish_license_metadata") as publish,
    ):
        seed_dev_license.main()

    upsert.assert_not_called()
    publish.assert_not_called()
