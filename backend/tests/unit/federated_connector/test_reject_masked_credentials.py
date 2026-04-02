import pytest

from onyx.db.federated import _reject_masked_credentials
from onyx.db.federated import MASK_CHAR


class TestRejectMaskedCredentials:
    """Verify that masked credential values are never accepted for DB writes.

    The mask_string() utility replaces secrets with "••••••••••••" (U+2022 BULLET).
    If these masked placeholders reach create/update, the real secret is permanently
    lost. _reject_masked_credentials is a backend safety-net for this.
    """

    def test_rejects_fully_masked_value(self) -> None:
        masked = MASK_CHAR * 12  # "••••••••••••"
        with pytest.raises(ValueError, match="masked placeholder"):
            _reject_masked_credentials({"client_id": masked})

    def test_rejects_partially_masked_value(self) -> None:
        """mask_string returns 'first4...last4' for long strings — but the
        short-string branch returns pure bullets. Both must be caught."""
        with pytest.raises(ValueError, match="masked placeholder"):
            _reject_masked_credentials({"client_id": f"abcd{MASK_CHAR * 6}wxyz"})

    def test_rejects_when_any_field_is_masked(self) -> None:
        """Even if client_id is real, a masked client_secret must be caught."""
        with pytest.raises(ValueError, match="client_secret"):
            _reject_masked_credentials(
                {
                    "client_id": "1234567890.1234567890",
                    "client_secret": MASK_CHAR * 12,
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
                "redirect_uri": None,  # type: ignore[dict-item]
                "some_flag": True,  # type: ignore[dict-item]
            }
        )
