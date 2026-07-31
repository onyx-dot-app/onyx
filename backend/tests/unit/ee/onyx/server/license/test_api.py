"""Tests for license API utilities."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.server.license.api import _normalize_license_file
from ee.onyx.server.license.models import LicensePayload, PlanType
from onyx.error_handling.exceptions import OnyxError


class TestNormalizeLicenseFile:
    """Reduces a .lic file to the bare base64 blob."""

    def test_strips_pem_delimiters(self) -> None:
        """Content wrapped in PEM delimiters is extracted correctly."""
        content = """-----BEGIN ONYX LICENSE-----
eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ==
-----END ONYX LICENSE-----"""

        result = _normalize_license_file(content)

        assert result == "eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ=="

    def test_joins_wrapped_base64_into_one_line(self) -> None:
        """A wrapped file must collapse to a single line.

        The stored blob is later sent as a Bearer token, and a header value
        containing newlines is rejected before the request is sent.
        """
        content = """-----BEGIN ONYX LICENSE-----
eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjog
IjEuMCIsICJ0ZW5hbnRfaWQiOiAidGVz
dCJ9LCAic2lnbmF0dXJlIjogImFiYyJ9
-----END ONYX LICENSE-----"""

        result = _normalize_license_file(content)

        assert "\n" not in result
        assert result == (
            "eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjog"
            "IjEuMCIsICJ0ZW5hbnRfaWQiOiAidGVz"
            "dCJ9LCAic2lnbmF0dXJlIjogImFiYyJ9"
        )

    def test_returns_unchanged_without_delimiters(self) -> None:
        """Content without PEM delimiters is returned unchanged."""
        content = "eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ=="

        result = _normalize_license_file(content)

        assert result == content

    def test_handles_whitespace(self) -> None:
        """Leading/trailing whitespace is handled correctly."""
        content = """
  -----BEGIN ONYX LICENSE-----
eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ==
-----END ONYX LICENSE-----
  """

        result = _normalize_license_file(content)

        assert result == "eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ=="

    def test_partial_delimiters_keep_their_marker(self) -> None:
        """Only a matched pair is a license file, so a lone marker stays and
        the blob fails signature verification rather than being half-accepted.
        Whitespace still collapses, since that is unconditional."""
        begin_only = """-----BEGIN ONYX LICENSE-----
eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ=="""

        end_only = """eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ==
-----END ONYX LICENSE-----"""

        assert _normalize_license_file(begin_only) == "".join(begin_only.split())
        assert _normalize_license_file(end_only) == "".join(end_only.split())

    def test_trailing_newlines_stripped_from_raw_input(self) -> None:
        """Raw license strings with trailing newlines from user paste are cleaned."""
        content = "eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ==\n\n"

        result = _normalize_license_file(content)

        assert result == "eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ=="

    def test_trailing_newlines_stripped_after_pem(self) -> None:
        """Inner content with trailing newlines after PEM stripping is cleaned."""
        content = """-----BEGIN ONYX LICENSE-----
eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ==

-----END ONYX LICENSE-----"""

        result = _normalize_license_file(content)

        assert result == "eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ=="


class TestClaimLicenseBustsBillingCache:
    """The cached snapshot feeds the plan, period end and status the page
    renders, so a claim that leaves it cached shows the pre-change plan."""

    @pytest.mark.asyncio
    @patch("ee.onyx.server.license.api.invalidate_billing_info_cache")
    @patch("ee.onyx.server.license.api.reclaim_license_from_control_plane")
    @patch("ee.onyx.server.license.api.MULTI_TENANT", False)
    async def test_reclaim_busts_the_billing_snapshot(
        self,
        mock_reclaim: MagicMock,
        mock_invalidate: MagicMock,
    ) -> None:
        """A subscription changed outside the product reaches the instance only
        through this endpoint."""
        from ee.onyx.server.license.api import claim_license

        now = datetime.now(timezone.utc)
        mock_reclaim.return_value = LicensePayload(
            version="1.0",
            tenant_id="tenant_123",
            organization_name="Test Org",
            issued_at=now,
            expires_at=now + timedelta(days=30),
            seats=10,
            plan_type=PlanType.MONTHLY,
        )

        await claim_license(_=MagicMock(), db_session=MagicMock())

        mock_invalidate.assert_called_once()

    @pytest.mark.asyncio
    @patch("ee.onyx.server.license.api.invalidate_billing_info_cache")
    @patch("ee.onyx.server.license.api.reclaim_license_from_control_plane")
    @patch("ee.onyx.server.license.api.MULTI_TENANT", False)
    async def test_a_failed_claim_leaves_the_snapshot_alone(
        self,
        mock_reclaim: MagicMock,
        mock_invalidate: MagicMock,
    ) -> None:
        """Dropping the entry on failure would send the next reader to the
        upstream that just failed."""
        from ee.onyx.server.license.api import claim_license

        mock_reclaim.return_value = None

        with pytest.raises(OnyxError):
            await claim_license(_=MagicMock(), db_session=MagicMock())

        mock_invalidate.assert_not_called()
