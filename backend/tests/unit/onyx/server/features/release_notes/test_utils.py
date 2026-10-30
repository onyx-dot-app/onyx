"""Unit tests for release notes fetch gating."""

from unittest.mock import Mock, patch

from onyx.server.features.release_notes import utils


def test_airgapped_skips_github_fetch() -> None:
    """ONYX_AIRGAPPED short-circuits before any fetch machinery runs."""
    with (
        patch.object(utils, "ONYX_AIRGAPPED", True),
        patch.object(utils, "is_cache_stale") as stale,
        patch.object(
            utils.httpx,
            "get",
            side_effect=AssertionError("must not fetch when air-gapped"),
        ),
    ):
        utils.ensure_release_notes_fresh_and_notify(db_session=Mock())
        stale.assert_not_called()
