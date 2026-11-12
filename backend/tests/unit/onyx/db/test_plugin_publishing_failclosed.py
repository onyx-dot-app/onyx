"""A Publishing setting that cannot be read stops a publish, instead of
falling back to the OPEN default."""

from unittest.mock import MagicMock

import pytest

import onyx.db.plugin_review as plugin_review
from onyx.server.settings.models import Settings


def test_publish_fails_closed_when_settings_read_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _load_settings(raise_on_error: bool = False) -> Settings:
        if raise_on_error:
            raise RuntimeError("kv down")
        return Settings()

    monkeypatch.setattr(plugin_review, "load_settings", _load_settings)
    monkeypatch.setattr(
        plugin_review,
        "has_global_permission",
        lambda user, permission: False,  # noqa: ARG005
    )

    with pytest.raises(RuntimeError):
        plugin_review.publish_action_for(MagicMock())
