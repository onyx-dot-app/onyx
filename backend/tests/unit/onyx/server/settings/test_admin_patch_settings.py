from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from onyx.server.settings import api as settings_api
from onyx.server.settings.models import CRAFT_INSTRUCTIONS_MAX_LENGTH, Settings


@contextmanager
def _noop_lock(*_a: Any, **_k: Any) -> Iterator[None]:
    yield


def _patch_settings(
    payload: dict[str, Any],
    existing: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> Settings:
    stored: list[Settings] = []
    monkeypatch.setattr(
        settings_api,
        "load_settings",
        lambda raise_on_error=False: existing,  # noqa: ARG005
    )
    monkeypatch.setattr(settings_api, "store_settings", stored.append)
    monkeypatch.setattr(settings_api, "emit_audit_event", lambda *_a, **_k: None)
    monkeypatch.setattr(settings_api, "settings_write_lock", _noop_lock)
    monkeypatch.setattr(settings_api.global_version, "is_ee_version", lambda: False)
    settings_api.admin_patch_settings(
        Settings.model_validate(payload), current_user=MagicMock()
    )
    assert len(stored) == 1
    return stored[0]


def test_omitted_craft_instructions_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = Settings(craft_instructions="keep me")
    result = _patch_settings({}, existing, monkeypatch)
    assert result.craft_instructions == "keep me"


def test_explicit_null_clears_craft_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = Settings(craft_instructions="old value")
    result = _patch_settings({"craft_instructions": None}, existing, monkeypatch)
    assert result.craft_instructions is None


def test_explicit_value_overwrites_craft_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = Settings(craft_instructions="old value")
    result = _patch_settings({"craft_instructions": "new value"}, existing, monkeypatch)
    assert result.craft_instructions == "new value"


def test_omitted_field_preserved_generally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Partial merge applies to every field, not just craft: a write that omits
    an access-control field leaves it unchanged instead of resetting it."""
    existing = Settings(invite_only_enabled=True, maximum_chat_retention_days=30)
    result = _patch_settings({"craft_instructions": "x"}, existing, monkeypatch)
    assert result.invite_only_enabled is True
    assert result.maximum_chat_retention_days == 30


def test_over_length_craft_instructions_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {"craft_instructions": "x" * (CRAFT_INSTRUCTIONS_MAX_LENGTH + 1)}
        )
