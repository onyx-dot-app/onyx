"""A Publishing setting that cannot be read stops a publish, instead of
falling back to the OPEN default."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

import onyx.db.plugin as plugin_db
from onyx.server.settings.models import Settings


def test_publish_fails_closed_when_settings_read_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _load_settings(raise_on_error: bool = False) -> Settings:
        if raise_on_error:
            raise RuntimeError("kv down")
        return Settings()

    monkeypatch.setattr(plugin_db, "load_settings", _load_settings)
    monkeypatch.setattr(
        plugin_db,
        "has_global_permission",
        lambda user, permission: False,  # noqa: ARG005
    )
    db_session = MagicMock()

    with pytest.raises(RuntimeError):
        plugin_db.publish_or_request_review__no_commit(
            MagicMock(), None, uuid4(), MagicMock(), "raise", db_session
        )
    db_session.flush.assert_not_called()
