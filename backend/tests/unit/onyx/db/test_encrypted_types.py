"""Unit tests for `_EncryptedBase.compare_values` tolerance of undecryptable
stored values. SQLAlchemy calls it at flush to decide whether an UPDATE is
needed; an undecryptable old value must compare as "changed" (not raise) so
overwriting a broken row — the credential recovery path — succeeds."""

from __future__ import annotations

import json
from typing import Any

from onyx.db.models import EncryptedJson
from onyx.utils.sensitive import SensitiveValue


def _bad_sensitive() -> SensitiveValue[dict[str, Any]]:
    """SensitiveValue whose decryption raises UnicodeDecodeError (a ValueError subclass)."""
    return SensitiveValue(
        encrypted_bytes=b"\xa5garbage",
        decrypt_fn=lambda b: b.decode(),
        is_json=True,
    )


def _good_sensitive(data: dict[str, Any]) -> SensitiveValue[dict[str, Any]]:
    """SensitiveValue that decrypts successfully to ``data``."""
    raw = json.dumps(data).encode()
    return SensitiveValue(
        encrypted_bytes=raw,
        decrypt_fn=lambda b: b.decode(),
        is_json=True,
    )


def test_compare_values_undecryptable_old_value_reads_as_changed() -> None:
    assert EncryptedJson().compare_values({"api_key": "new"}, _bad_sensitive()) is False


def test_compare_values_equal_decryptable_values() -> None:
    data = {"api_key": "k"}
    assert EncryptedJson().compare_values(data, _good_sensitive(data)) is True


def test_compare_values_different_decryptable_values() -> None:
    assert (
        EncryptedJson().compare_values(
            {"api_key": "new"}, _good_sensitive({"api_key": "old"})
        )
        is False
    )
