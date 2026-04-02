import pytest

from onyx.configs.constants import MASK_CREDENTIAL_CHAR
from onyx.db.federated import _reject_masked_credentials


class TestRejectMaskedCredentials:
    """Verify that masked credential values are never accepted for DB writes.

    mask_string() has two output formats:
    - Short strings (< 14 chars): "••••••••••••" (U+2022 BULLET)
    - Long strings (>= 14 chars): "abcd...wxyz" (first4 + "..." + last4)
    _reject_masked_credentials must catch both.
    """

    def test_rejects_fully_masked_value(self) -> None:
        masked = MASK_CREDENTIAL_CHAR * 12  # "••••••••••••"
        with pytest.raises(ValueError, match="masked placeholder"):
            _reject_masked_credentials({"client_id": masked})

    def test_rejects_long_string_masked_value(self) -> None:
        """mask_string returns 'first4...last4' for long strings — the real
        format used for OAuth credentials like client_id and client_secret."""
        with pytest.raises(ValueError, match="masked placeholder"):
            _reject_masked_credentials({"client_id": "1234...7890"})

    def test_rejects_when_any_field_is_masked(self) -> None:
        """Even if client_id is real, a masked client_secret must be caught."""
        with pytest.raises(ValueError, match="client_secret"):
            _reject_masked_credentials(
                {
                    "client_id": "1234567890.1234567890",
                    "client_secret": MASK_CREDENTIAL_CHAR * 12,
                }
            )

    def test_accepts_real_credentials(self) -> None:
        # Should not raise
        _reject_masked_credentials(
            {
                "client_id": "1234567890.1234567890",
                "client_secret": "test_client_secret_value",
            }
        )

    def test_accepts_empty_dict(self) -> None:
        # Should not raise — empty credentials are handled elsewhere
        _reject_masked_credentials({})

    def test_ignores_non_string_values(self) -> None:
        # Non-string values (None, bool, int) should pass through
        _reject_masked_credentials(
            {
                "client_id": "real_value",
                "redirect_uri": None,
                "some_flag": True,
            }
        )
