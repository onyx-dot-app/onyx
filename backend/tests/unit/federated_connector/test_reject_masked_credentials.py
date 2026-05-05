import pytest

from onyx.configs.constants import MASK_CREDENTIAL_CHAR
from onyx.utils.encryption import reject_masked_credentials


class TestRejectMaskedCredentials:
    """Verify that masked credential values are never accepted for DB writes.

    mask_string() has two output formats:
    - Short strings (< 14 chars): "••••••••••••" (U+2022 BULLET)
    - Long strings (>= 14 chars): "abcd...wxyz" (first4 + "..." + last4)
    reject_masked_credentials must catch both.
    """

    def test_rejects_fully_masked_value(self) -> None:
        masked = MASK_CREDENTIAL_CHAR * 12  # "••••••••••••"
        with pytest.raises(ValueError, match="masked placeholder"):
            reject_masked_credentials({"client_id": masked})

    def test_rejects_long_string_masked_value(self) -> None:
        """mask_string returns 'first4...last4' for long strings — the real
        format used for OAuth credentials like client_id and client_secret."""
        with pytest.raises(ValueError, match="masked placeholder"):
            reject_masked_credentials({"client_id": "1234...7890"})

    def test_rejects_when_any_field_is_masked(self) -> None:
        """Even if client_id is real, a masked client_secret must be caught."""
        with pytest.raises(ValueError, match="client_secret"):
            reject_masked_credentials(
                {
                    "client_id": "1234567890.1234567890",
                    "client_secret": MASK_CREDENTIAL_CHAR * 12,
                }
            )

    def test_accepts_real_credentials(self) -> None:
        # Should not raise
        reject_masked_credentials(
            {
                "client_id": "1234567890.1234567890",
                "client_secret": "test_client_secret_value",
            }
        )

    def test_accepts_empty_dict(self) -> None:
        # Should not raise — empty credentials are handled elsewhere
        reject_masked_credentials({})

    def test_ignores_non_string_values(self) -> None:
        # Non-string values (None, bool, int) should pass through
        reject_masked_credentials(
            {
                "client_id": "real_value",
                "redirect_uri": None,
                "some_flag": True,
            }
        )

    def test_rejects_masked_value_inside_nested_dict(self) -> None:
        """`mask_credential_dict` recurses into nested dicts; the rejection
        helper must do the same so a masked nested string can't slip
        through on resubmit."""
        with pytest.raises(ValueError, match=r"oauth\.client_secret"):
            reject_masked_credentials(
                {
                    "name": "fine",
                    "oauth": {
                        "client_id": "1234567890.1234567890",
                        "client_secret": "abcd...wxyz",
                    },
                }
            )

    def test_rejects_masked_value_inside_list(self) -> None:
        """`_mask_list` masks string elements; the rejection helper must
        catch them too."""
        with pytest.raises(ValueError, match=r"keys\[1\]"):
            reject_masked_credentials(
                {
                    "keys": ["real-key-aaaa", "abcd...wxyz", "real-key-bbbb"],
                }
            )

    def test_rejects_masked_value_inside_list_of_dicts(self) -> None:
        with pytest.raises(ValueError, match=r"sessions\[0\]\.token"):
            reject_masked_credentials(
                {
                    "sessions": [
                        {"token": "abcd...wxyz"},
                        {"token": "real-token-value"},
                    ],
                }
            )

    def test_accepts_deeply_nested_real_values(self) -> None:
        reject_masked_credentials(
            {
                "oauth": {
                    "client_id": "real-id-value-1234",
                    "extras": {
                        "scopes": ["read", "write"],
                        "metadata": {"region": "us-east-1"},
                    },
                },
            }
        )
