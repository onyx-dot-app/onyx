"""Guards the license persistence contract: a blob is stored only after its
signature verifies, and the control-plane re-claim authenticates with the
stored license, validates the response, and persists through the same path."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.server.license.models import LicensePayload, LicenseSource, PlanType
from ee.onyx.utils.license import (
    reclaim_license_from_control_plane,
    verify_and_store_license,
)


def _make_license_payload() -> LicensePayload:
    now = datetime.now(timezone.utc)
    return LicensePayload(
        version="1.0",
        tenant_id="tenant_123",
        organization_name="Test Org",
        issued_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=30),
        seats=10,
        plan_type=PlanType.MONTHLY,
    )


class TestVerifyAndStoreLicense:
    @patch("ee.onyx.db.license.update_license_cache")
    @patch("ee.onyx.db.license.upsert_license")
    @patch("ee.onyx.utils.license.verify_license_signature")
    def test_persists_and_caches_with_the_given_source(
        self,
        mock_verify: MagicMock,
        mock_upsert: MagicMock,
        mock_update_cache: MagicMock,
    ) -> None:
        db_session = MagicMock()
        payload = _make_license_payload()
        mock_verify.return_value = payload

        result = verify_and_store_license(
            db_session, "signed-license", source=LicenseSource.MANUAL_UPLOAD
        )

        assert result == payload
        mock_upsert.assert_called_once_with(db_session, "signed-license")
        mock_update_cache.assert_called_once_with(
            payload, source=LicenseSource.MANUAL_UPLOAD
        )

    @patch("ee.onyx.db.license.upsert_license")
    @patch("ee.onyx.utils.license.verify_license_signature")
    def test_rejects_unverifiable_blob_without_persisting(
        self,
        mock_verify: MagicMock,
        mock_upsert: MagicMock,
    ) -> None:
        mock_verify.side_effect = ValueError("Invalid license signature")

        with pytest.raises(ValueError, match="Invalid license signature"):
            verify_and_store_license(
                MagicMock(), "tampered-license", source=LicenseSource.MANUAL_UPLOAD
            )

        mock_upsert.assert_not_called()


class TestReclaimLicenseFromControlPlane:
    @patch("ee.onyx.utils.license.CLOUD_DATA_PLANE_URL", "https://cloud.example.com")
    @patch("ee.onyx.db.license.get_license")
    @patch("ee.onyx.db.license.get_license_metadata")
    @patch("ee.onyx.db.license.update_license_cache")
    @patch("ee.onyx.db.license.upsert_license")
    @patch("ee.onyx.utils.license.verify_license_signature")
    @patch("ee.onyx.utils.license.requests.get")
    def test_successfully_reclaims_and_persists_license(
        self,
        mock_get_request: MagicMock,
        mock_verify: MagicMock,
        mock_upsert: MagicMock,
        mock_update_cache: MagicMock,
        mock_get_metadata: MagicMock,
        mock_get_license: MagicMock,
    ) -> None:
        db_session = MagicMock()
        payload = _make_license_payload()
        mock_get_metadata.return_value = MagicMock(tenant_id="tenant_123")
        mock_get_license.return_value = MagicMock(license_data="stored-license")
        mock_verify.return_value = payload

        response = MagicMock()
        response.json.return_value = {"license": "signed-license"}
        response.raise_for_status = MagicMock()
        mock_get_request.return_value = response

        result = reclaim_license_from_control_plane(db_session)

        assert result == payload
        mock_get_request.assert_called_once_with(
            "https://cloud.example.com/proxy/license/tenant_123",
            headers={
                "Authorization": "Bearer stored-license",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        mock_verify.assert_called_once_with("signed-license")
        mock_upsert.assert_called_once_with(db_session, "signed-license")
        mock_update_cache.assert_called_once_with(
            payload,
            source=LicenseSource.AUTO_FETCH,
        )

    @pytest.mark.parametrize(
        ("metadata", "license_row"),
        [
            (None, MagicMock(license_data="stored-license")),
            (MagicMock(tenant_id=""), MagicMock(license_data="stored-license")),
            (MagicMock(tenant_id="tenant_123"), None),
            (MagicMock(tenant_id="tenant_123"), MagicMock(license_data="")),
        ],
    )
    @patch("ee.onyx.db.license.get_license")
    @patch("ee.onyx.db.license.get_license_metadata")
    @patch("ee.onyx.db.license.upsert_license")
    @patch("ee.onyx.utils.license.requests.get")
    def test_returns_none_when_local_reclaim_prereqs_are_missing(
        self,
        mock_get_request: MagicMock,
        mock_upsert: MagicMock,
        mock_get_metadata: MagicMock,
        mock_get_license: MagicMock,
        metadata: MagicMock | None,
        license_row: MagicMock | None,
    ) -> None:
        mock_get_metadata.return_value = metadata
        mock_get_license.return_value = license_row

        result = reclaim_license_from_control_plane(MagicMock())

        assert result is None
        mock_get_request.assert_not_called()
        mock_upsert.assert_not_called()

    @patch("ee.onyx.utils.license.logger")
    @patch("ee.onyx.db.license.get_license")
    @patch("ee.onyx.db.license.get_license_metadata")
    @patch("ee.onyx.db.license.update_license_cache")
    @patch("ee.onyx.db.license.upsert_license")
    @patch("ee.onyx.utils.license.verify_license_signature")
    @patch("ee.onyx.utils.license.requests.get")
    def test_cache_update_failure_is_logged_and_swallowed(
        self,
        mock_get_request: MagicMock,
        mock_verify: MagicMock,
        mock_upsert: MagicMock,
        mock_update_cache: MagicMock,
        mock_get_metadata: MagicMock,
        mock_get_license: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        db_session = MagicMock()
        payload = _make_license_payload()
        mock_get_metadata.return_value = MagicMock(tenant_id="tenant_123")
        mock_get_license.return_value = MagicMock(license_data="stored-license")
        mock_verify.return_value = payload
        mock_update_cache.side_effect = RuntimeError("cache failed")

        response = MagicMock()
        response.json.return_value = {"license": "signed-license"}
        response.raise_for_status = MagicMock()
        mock_get_request.return_value = response

        result = reclaim_license_from_control_plane(db_session)

        assert result == payload
        mock_upsert.assert_called_once_with(db_session, "signed-license")
        mock_logger.warning.assert_called_once_with(
            "Failed to update license cache: %s",
            mock_update_cache.side_effect,
        )

    @patch("ee.onyx.db.license.get_license")
    @patch("ee.onyx.db.license.get_license_metadata")
    @patch("ee.onyx.db.license.upsert_license")
    @patch("ee.onyx.utils.license.requests.get")
    def test_raises_value_error_when_response_has_no_license_field(
        self,
        mock_get_request: MagicMock,
        mock_upsert: MagicMock,
        mock_get_metadata: MagicMock,
        mock_get_license: MagicMock,
    ) -> None:
        mock_get_metadata.return_value = MagicMock(tenant_id="tenant_123")
        mock_get_license.return_value = MagicMock(license_data="stored-license")

        response = MagicMock()
        response.json.return_value = {"tenant_id": "tenant_123"}
        response.raise_for_status = MagicMock()
        mock_get_request.return_value = response

        with pytest.raises(ValueError, match="No license in response"):
            reclaim_license_from_control_plane(MagicMock())

        mock_upsert.assert_not_called()

    @patch("ee.onyx.db.license.get_license")
    @patch("ee.onyx.db.license.get_license_metadata")
    @patch("ee.onyx.db.license.upsert_license")
    @patch("ee.onyx.utils.license.verify_license_signature")
    @patch("ee.onyx.utils.license.requests.get")
    def test_does_not_persist_unverified_license(
        self,
        mock_get_request: MagicMock,
        mock_verify: MagicMock,
        mock_upsert: MagicMock,
        mock_get_metadata: MagicMock,
        mock_get_license: MagicMock,
    ) -> None:
        mock_get_metadata.return_value = MagicMock(tenant_id="tenant_123")
        mock_get_license.return_value = MagicMock(license_data="stored-license")
        mock_verify.side_effect = ValueError("invalid license signature")

        response = MagicMock()
        response.json.return_value = {"license": "signed-license"}
        response.raise_for_status = MagicMock()
        mock_get_request.return_value = response

        with pytest.raises(ValueError, match="invalid license signature"):
            reclaim_license_from_control_plane(MagicMock())

        mock_upsert.assert_not_called()
