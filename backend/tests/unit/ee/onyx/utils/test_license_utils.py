"""Tests for license signature verification utilities."""

import base64
import json
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric import rsa

from ee.onyx.server.license.models import LicensePayload
from ee.onyx.server.license.models import PlanType
from ee.onyx.utils.license import get_license_status
from ee.onyx.utils.license import is_license_valid
from ee.onyx.utils.license import verify_license_signature
from onyx.server.settings.models import ApplicationStatus


def generate_test_key_pair() -> tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]:
    """Generate a test RSA key pair."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,  # Use smaller key for faster tests
    )
    public_key = private_key.public_key()
    return private_key, public_key


def create_signed_license(
    private_key: rsa.RSAPrivateKey,
    payload: LicensePayload,
) -> str:
    """Create a signed license for testing."""
    payload_json = json.dumps(payload.model_dump(mode="json"), sort_keys=True)
    signature = private_key.sign(
        payload_json.encode(),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )

    license_data = {
        "payload": payload.model_dump(mode="json"),
        "signature": base64.b64encode(signature).decode(),
    }

    return base64.b64encode(json.dumps(license_data).encode()).decode()


class TestVerifyLicenseSignature:
    """Tests for verify_license_signature function."""

    def test_valid_signature(self) -> None:
        """Test that a valid signature passes verification."""
        private_key, public_key = generate_test_key_pair()

        payload = LicensePayload(
            version="1.0",
            tenant_id="tenant_123",
            issued_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2025, 12, 31, tzinfo=timezone.utc),
            seats=50,
            plan_type=PlanType.MONTHLY,
        )

        license_data = create_signed_license(private_key, payload)

        # Patch the public key in the validator module
        public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

        with patch("ee.onyx.utils.license.PUBLIC_KEY_PEM", public_key_pem):
            result = verify_license_signature(license_data)

        assert result.tenant_id == "tenant_123"
        assert result.seats == 50
        assert result.plan_type == PlanType.MONTHLY

    def test_invalid_signature(self) -> None:
        """Test that an invalid signature fails verification."""
        private_key, public_key = generate_test_key_pair()
        _, different_public_key = generate_test_key_pair()

        payload = LicensePayload(
            version="1.0",
            tenant_id="tenant_123",
            issued_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2025, 12, 31, tzinfo=timezone.utc),
            seats=50,
            plan_type=PlanType.MONTHLY,
        )

        license_data = create_signed_license(private_key, payload)

        # Use a different public key
        different_public_key_pem = different_public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

        with patch(
            "ee.onyx.utils.license.PUBLIC_KEY_PEM",
            different_public_key_pem,
        ):
            with pytest.raises(ValueError, match="Invalid license signature"):
                verify_license_signature(license_data)

    def test_tampered_payload(self) -> None:
        """Test that a tampered payload fails verification."""
        private_key, public_key = generate_test_key_pair()

        payload = LicensePayload(
            version="1.0",
            tenant_id="tenant_123",
            issued_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2025, 12, 31, tzinfo=timezone.utc),
            seats=50,
            plan_type=PlanType.MONTHLY,
        )

        # Create valid signature
        payload_json = json.dumps(payload.model_dump(mode="json"), sort_keys=True)
        signature = private_key.sign(
            payload_json.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )

        # Tamper with the payload (change seats)
        tampered_payload = payload.model_dump(mode="json")
        tampered_payload["seats"] = 1000  # Changed!

        license_data = {
            "payload": tampered_payload,
            "signature": base64.b64encode(signature).decode(),
        }

        encoded_license = base64.b64encode(json.dumps(license_data).encode()).decode()

        public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

        with patch("ee.onyx.utils.license.PUBLIC_KEY_PEM", public_key_pem):
            with pytest.raises(ValueError, match="Invalid license signature"):
                verify_license_signature(encoded_license)

    def test_invalid_base64(self) -> None:
        """Test that invalid base64 fails."""
        with pytest.raises(ValueError):
            verify_license_signature("not-valid-base64!!!")

    def test_invalid_json(self) -> None:
        """Test that invalid JSON fails."""
        invalid_data = base64.b64encode(b"not json").decode()
        with pytest.raises(ValueError):
            verify_license_signature(invalid_data)


class TestGetLicenseStatus:
    """Tests for get_license_status function."""

    def test_active_license(self) -> None:
        """Test status for an active license."""
        payload = LicensePayload(
            version="1.0",
            tenant_id="tenant_123",
            issued_at=datetime.now(timezone.utc) - timedelta(days=30),
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            seats=50,
            plan_type=PlanType.MONTHLY,
        )

        status = get_license_status(payload)
        assert status == ApplicationStatus.ACTIVE

    def test_expired_license_no_grace(self) -> None:
        """Test status for an expired license without grace period."""
        payload = LicensePayload(
            version="1.0",
            tenant_id="tenant_123",
            issued_at=datetime.now(timezone.utc) - timedelta(days=60),
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            seats=50,
            plan_type=PlanType.MONTHLY,
        )

        status = get_license_status(payload)
        assert status == ApplicationStatus.GATED_ACCESS

    def test_expired_license_within_grace(self) -> None:
        """Test status for an expired license within grace period."""
        payload = LicensePayload(
            version="1.0",
            tenant_id="tenant_123",
            issued_at=datetime.now(timezone.utc) - timedelta(days=60),
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            seats=50,
            plan_type=PlanType.MONTHLY,
        )

        grace_end = datetime.now(timezone.utc) + timedelta(days=29)
        status = get_license_status(payload, grace_period_end=grace_end)
        assert status == ApplicationStatus.GRACE_PERIOD

    def test_grace_period_expired(self) -> None:
        """Test status when grace period has expired."""
        payload = LicensePayload(
            version="1.0",
            tenant_id="tenant_123",
            issued_at=datetime.now(timezone.utc) - timedelta(days=90),
            expires_at=datetime.now(timezone.utc) - timedelta(days=31),
            seats=50,
            plan_type=PlanType.MONTHLY,
        )

        grace_end = datetime.now(timezone.utc) - timedelta(days=1)
        status = get_license_status(payload, grace_period_end=grace_end)
        assert status == ApplicationStatus.GATED_ACCESS


class TestIsLicenseValid:
    """Tests for is_license_valid function."""

    def test_valid_license(self) -> None:
        """Test that an unexpired license is valid."""
        payload = LicensePayload(
            version="1.0",
            tenant_id="tenant_123",
            issued_at=datetime.now(timezone.utc) - timedelta(days=30),
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            seats=50,
            plan_type=PlanType.MONTHLY,
        )

        assert is_license_valid(payload) is True

    def test_expired_license(self) -> None:
        """Test that an expired license is invalid."""
        payload = LicensePayload(
            version="1.0",
            tenant_id="tenant_123",
            issued_at=datetime.now(timezone.utc) - timedelta(days=60),
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            seats=50,
            plan_type=PlanType.MONTHLY,
        )

        assert is_license_valid(payload) is False
