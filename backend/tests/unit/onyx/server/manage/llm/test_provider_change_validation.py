"""Tests for _validate_llm_provider_change's custom_config comparison.

Surface-mode keys pick a path on the same api_base, so changing them alone
must not force key re-entry; everything else still must. The API token checks
the api_base itself.
"""

from unittest.mock import patch

import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.llm.well_known_providers.constants import BIFROST_API_MODE_CONFIG_KEY
from onyx.server.manage.llm.api import _validate_llm_provider_change


def _validate(
    existing_custom_config: dict[str, str] | None,
    new_custom_config: dict[str, str] | None,
    uses_saved_key: bool = True,
) -> None:
    _validate_llm_provider_change(
        existing_custom_config=existing_custom_config,
        new_custom_config=new_custom_config,
        uses_saved_key=uses_saved_key,
    )


@patch("onyx.server.manage.llm.api.MULTI_TENANT", True)
def test_surface_mode_only_change_is_allowed() -> None:
    _validate(None, {BIFROST_API_MODE_CONFIG_KEY: "responses"})
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
    # The submitted dict is persisted wholesale; dropped entries must reject.
    with pytest.raises(OnyxError):
        _validate(
            {BIFROST_API_MODE_CONFIG_KEY: "chat_completions", "extra": "stored"},
            {BIFROST_API_MODE_CONFIG_KEY: "responses"},
        )


@patch("onyx.server.manage.llm.api.MULTI_TENANT", True)
def test_new_key_allows_any_change() -> None:
    _validate(
        {BIFROST_API_MODE_CONFIG_KEY: "responses"},
        {"some_credential": "x"},
        uses_saved_key=False,
    )


def test_single_tenant_skips_validation() -> None:
    # MULTI_TENANT is False in unit tests: everything passes.
    _validate(None, {"anything": "goes"})
