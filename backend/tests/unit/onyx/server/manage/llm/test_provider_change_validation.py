"""Tests for _validate_llm_provider_change's custom_config comparison.

In MULTI_TENANT mode, changing api_base or custom_config without re-entering
the API key is rejected (the stored key must not be redirectable to another
host). API-surface mode keys (e.g. bifrost_api_mode) only pick a path on the
same api_base, so changing them alone must NOT force key re-entry.
"""

from unittest.mock import patch

import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.llm.well_known_providers.constants import BIFROST_API_MODE_CONFIG_KEY
from onyx.server.manage.llm.api import _validate_llm_provider_change

_BASE = "https://bifrost.example.com/v1"


def _validate(
    existing_custom_config: dict[str, str] | None,
    new_custom_config: dict[str, str] | None,
    new_api_base: str = _BASE,
) -> None:
    _validate_llm_provider_change(
        existing_api_base=_BASE,
        existing_custom_config=existing_custom_config,
        new_api_base=new_api_base,
        new_custom_config=new_custom_config,
        api_key_changed=False,
    )


@patch("onyx.server.manage.llm.api.MULTI_TENANT", True)
def test_surface_mode_only_change_is_allowed() -> None:
    # Enabling responses mode on an existing provider (no prior custom_config)
    # must not demand API-key re-entry.
    _validate(None, {BIFROST_API_MODE_CONFIG_KEY: "responses"})
    # Nor must switching between modes.
    _validate(
        {BIFROST_API_MODE_CONFIG_KEY: "chat_completions"},
        {BIFROST_API_MODE_CONFIG_KEY: "responses"},
    )


@patch("onyx.server.manage.llm.api.MULTI_TENANT", True)
def test_mode_change_alongside_unchanged_entries_is_allowed() -> None:
    _validate(
        {BIFROST_API_MODE_CONFIG_KEY: "chat_completions", "extra": "kept"},
        {BIFROST_API_MODE_CONFIG_KEY: "responses", "extra": "kept"},
    )


@patch("onyx.server.manage.llm.api.MULTI_TENANT", True)
def test_other_custom_config_change_still_rejected() -> None:
    with pytest.raises(OnyxError):
        _validate(
            {BIFROST_API_MODE_CONFIG_KEY: "responses"},
            {BIFROST_API_MODE_CONFIG_KEY: "responses", "some_credential": "x"},
        )


@patch("onyx.server.manage.llm.api.MULTI_TENANT", True)
def test_mode_only_submission_dropping_stored_entries_is_rejected() -> None:
    # A submission containing only the mode key must not silently delete
    # stored non-surface entries when persisted wholesale.
    with pytest.raises(OnyxError):
        _validate(
            {BIFROST_API_MODE_CONFIG_KEY: "chat_completions", "extra": "stored"},
            {BIFROST_API_MODE_CONFIG_KEY: "responses"},
        )


@patch("onyx.server.manage.llm.api.MULTI_TENANT", True)
def test_api_base_change_still_rejected() -> None:
    with pytest.raises(OnyxError):
        _validate(
            {BIFROST_API_MODE_CONFIG_KEY: "responses"},
            {BIFROST_API_MODE_CONFIG_KEY: "responses"},
            new_api_base="https://attacker.example.com/v1",
        )


def test_single_tenant_skips_validation() -> None:
    # MULTI_TENANT is False in unit tests: everything passes.
    _validate(None, {"anything": "goes"})
