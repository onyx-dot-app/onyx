"""Custom-tool header values are secrets: masked on read, restored on echo.

Mirrors the embedding-provider guard added in #14210 — a caller that writes back
what it read must not store the mask as the real value.
"""

import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.tool.api import _resolve_masked_headers
from onyx.server.features.tool.models import Header, mask_custom_headers

_SECRET = "Bearer super-secret-token-value"


def test_read_masks_header_values_but_keeps_keys() -> None:
    masked = mask_custom_headers([{"key": "Authorization", "value": _SECRET}])

    assert masked is not None
    assert masked[0]["key"] == "Authorization"
    assert masked[0]["value"] != _SECRET
    assert _SECRET not in masked[0]["value"]


def test_echoing_the_mask_restores_the_stored_value() -> None:
    stored = [{"key": "Authorization", "value": _SECRET}]
    masked = mask_custom_headers(stored)
    assert masked is not None

    resolved = _resolve_masked_headers(
        [Header(key=h["key"], value=h["value"]) for h in masked], stored
    )

    assert resolved is not None
    assert resolved[0].value == _SECRET


def test_a_real_new_value_is_taken_as_written() -> None:
    stored = [{"key": "Authorization", "value": _SECRET}]

    resolved = _resolve_masked_headers(
        [Header(key="Authorization", value="Bearer rotated-token-value")], stored
    )

    assert resolved is not None
    assert resolved[0].value == "Bearer rotated-token-value"


def test_a_mask_with_nothing_stored_is_rejected() -> None:
    masked = mask_custom_headers([{"key": "Authorization", "value": _SECRET}])
    assert masked is not None

    with pytest.raises(OnyxError):
        _resolve_masked_headers(
            [Header(key="Authorization", value=masked[0]["value"])], None
        )


def test_a_mask_under_a_different_key_is_rejected() -> None:
    stored = [{"key": "Authorization", "value": _SECRET}]
    masked = mask_custom_headers(stored)
    assert masked is not None

    with pytest.raises(OnyxError):
        _resolve_masked_headers(
            [Header(key="X-Other", value=masked[0]["value"])], stored
        )
