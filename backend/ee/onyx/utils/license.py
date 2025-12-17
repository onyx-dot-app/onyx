"""RSA-4096 license signature verification utilities."""

import base64
import json
import os
from datetime import datetime
from datetime import timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

from ee.onyx.server.license.models import LicenseData
from ee.onyx.server.license.models import LicensePayload
from onyx.server.settings.models import ApplicationStatus
from onyx.utils.logger import setup_logger

logger = setup_logger()


# RSA-4096 Public Key for license verification
# Load from environment variable - key is generated on the control plane
# In production, inject via Kubernetes secrets or secrets manager
LICENSE_PUBLIC_KEY_PEM = os.environ.get("LICENSE_PUBLIC_KEY_PEM", "")


def _get_public_key() -> RSAPublicKey:
    """Load the public key from environment variable."""
    if not LICENSE_PUBLIC_KEY_PEM:
        raise ValueError(
            "LICENSE_PUBLIC_KEY_PEM environment variable not set. "
            "License verification requires the control plane public key."
        )
    key = serialization.load_pem_public_key(LICENSE_PUBLIC_KEY_PEM.encode())
    if not isinstance(key, RSAPublicKey):
        raise ValueError("Expected RSA public key")
    return key


def verify_license_signature(license_data: str) -> LicensePayload:
    """
    Verify RSA-4096 signature and return payload if valid.

    Args:
        license_data: Base64-encoded JSON containing payload and signature

    Returns:
        LicensePayload if signature is valid

    Raises:
        ValueError: If license data is invalid or signature verification fails
    """
    try:
        # Decode the license data
        decoded = json.loads(base64.b64decode(license_data))
        license_obj = LicenseData(**decoded)

        payload_json = json.dumps(
            license_obj.payload.model_dump(mode="json"), sort_keys=True
        )
        signature_bytes = base64.b64decode(license_obj.signature)

        # Verify signature using PSS padding (modern standard)
        public_key = _get_public_key()
        public_key.verify(
            signature_bytes,
            payload_json.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )

        return license_obj.payload

    except InvalidSignature:
        logger.error("License signature verification failed")
        raise ValueError("Invalid license signature")
    except json.JSONDecodeError:
        logger.error("Failed to decode license JSON")
        raise ValueError("Invalid license format: not valid JSON")
    except (ValueError, KeyError, TypeError) as e:
        logger.error(f"License data validation error: {type(e).__name__}")
        raise ValueError(f"Invalid license format: {type(e).__name__}")
    except Exception:
        logger.exception("Unexpected error during license verification")
        raise ValueError("License verification failed: unexpected error")


def get_license_status(
    payload: LicensePayload,
    grace_period_end: datetime | None = None,
) -> ApplicationStatus:
    """
    Determine current license status based on expiry.

    Args:
        payload: The verified license payload
        grace_period_end: Optional grace period end datetime

    Returns:
        ApplicationStatus indicating current license state
    """
    now = datetime.now(timezone.utc)

    # Check if grace period has expired
    if grace_period_end and now > grace_period_end:
        return ApplicationStatus.GATED_ACCESS

    # Check if license has expired
    if now > payload.expires_at:
        if grace_period_end and now <= grace_period_end:
            return ApplicationStatus.GRACE_PERIOD
        return ApplicationStatus.GATED_ACCESS

    # License is valid
    return ApplicationStatus.ACTIVE


def is_license_valid(payload: LicensePayload) -> bool:
    """Check if a license is currently valid (not expired)."""
    now = datetime.now(timezone.utc)
    return now <= payload.expires_at
