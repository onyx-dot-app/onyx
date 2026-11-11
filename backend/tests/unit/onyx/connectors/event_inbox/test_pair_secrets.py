"""What a source's verifier and handler see of the pair's credential."""

from typing import Any
from unittest.mock import MagicMock

from onyx.connectors.event_inbox.credentials import pair_secrets


def _pair(values: dict[str, Any] | None) -> MagicMock:
    pair = MagicMock()
    if values is None:
        pair.credential.credential_json = None
    else:
        pair.credential.credential_json.get_value.return_value = values
    return pair


def test_a_null_secret_stays_missing() -> None:
    """As the string "null" it would be a non-empty key a verifier accepts."""
    assert "webhook_secret" not in pair_secrets(_pair({"webhook_secret": None}))


def test_a_value_that_is_not_a_string_arrives_as_json() -> None:
    secrets = pair_secrets(
        _pair({"token": "t", "port": 443, "oauth": {"refresh": "r"}, "on": True})
    )

    assert secrets == {
        "token": "t",
        "port": "443",
        "oauth": '{"refresh": "r"}',
        "on": "true",
    }


def test_a_pair_with_no_credential_json_has_no_secrets() -> None:
    assert pair_secrets(_pair(None)) == {}
