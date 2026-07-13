from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from onyx.server.settings import api as settings_api
from onyx.server.settings.models import CRAFT_INSTRUCTIONS_MAX_LENGTH
from onyx.server.settings.models import Settings


def _put_settings(
    payload: dict[str, Any],
    existing: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> Settings:
    stored: list[Settings] = []
    monkeypatch.setattr(settings_api, "load_settings", lambda: existing)
    monkeypatch.setattr(settings_api, "store_settings", stored.append)
    monkeypatch.setattr(settings_api, "emit_audit_event", lambda *_a, **_k: None)
    monkeypatch.setattr(settings_api.global_version, "is_ee_version", lambda: False)
    settings_api.admin_put_settings(
        Settings.model_validate(payload), current_user=MagicMock()
    )
    assert len(stored) == 1
    return stored[0]


def test_omitted_craft_instructions_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = Settings(craft_instructions="keep me")
    result = _put_settings({}, existing, monkeypatch)
    assert result.craft_instructions == "keep me"


def test_explicit_null_clears_craft_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = Settings(craft_instructions="old value")
    result = _put_settings({"craft_instructions": None}, existing, monkeypatch)
    assert result.craft_instructions is None


def test_explicit_value_overwrites_craft_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = Settings(craft_instructions="old value")
    result = _put_settings({"craft_instructions": "new value"}, existing, monkeypatch)
    assert result.craft_instructions == "new value"


def test_over_length_craft_instructions_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {"craft_instructions": "x" * (CRAFT_INSTRUCTIONS_MAX_LENGTH + 1)}
        )
