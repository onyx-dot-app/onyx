"""Dev seeds use the same guarded store as license uploads."""

from unittest.mock import patch

import pytest

from scripts import seed_dev_license


def test_seeding_normalizes_the_license_before_the_guarded_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "ONYX_DEV_LICENSE",
        "-----BEGIN ONYX LICENSE-----\nlicense-\nblob\n-----END ONYX LICENSE-----\n",
    )
    with (
        patch.object(seed_dev_license, "SqlEngine") as engine,
        patch.object(seed_dev_license, "get_session_with_current_tenant") as session,
        patch.object(seed_dev_license, "verify_and_store_license") as store,
    ):
        seed_dev_license.main()

    store.assert_called_once_with(
        session.return_value.__enter__.return_value, "license-blob"
    )
    # Publishing opens a second session inside the first, plus a lock connection.
    pool: dict[str, int] = engine.init_engine.call_args.kwargs
    assert pool["pool_size"] + pool["max_overflow"] >= 3


def test_an_empty_license_seeds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONYX_DEV_LICENSE", "")
    with (
        patch.object(seed_dev_license, "verify_and_store_license") as store,
    ):
        seed_dev_license.main()

    store.assert_not_called()
