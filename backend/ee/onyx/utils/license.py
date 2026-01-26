"""RSA-4096 license signature verification utilities."""

import base64
import json
import os
from datetime import datetime
from datetime import timezone
from pathlib import Path

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

# Path to the license public key file
_LICENSE_PUBLIC_KEY_PATH = (
    Path(__file__).parent.parent.parent.parent / "keys" / "license_public_key.pem"
)


def _get_public_key() -> RSAPublicKey:
    """Load the public key from file, with env var override."""
    # Allow env var override for flexibility
    key_pem = os.environ.get("LICENSE_PUBLIC_KEY_PEM")

    if not key_pem:
        # Read from file
        if not _LICENSE_PUBLIC_KEY_PATH.exists():
            raise ValueError(
                f"License public key not found at {_LICENSE_PUBLIC_KEY_PATH}. "
                "License verification requires the control plane public key."
            )
        key_pem = _LICENSE_PUBLIC_KEY_PATH.read_text()

    key = serialization.load_pem_public_key(key_pem.encode())
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
        decoded = json.loads(base64.b64decode(license_data))

        # Parse into LicenseData to validate structure
        license_obj = LicenseData(**decoded)
        logger.info(
            f"[verify_license] Parsed LicenseData, tenant_id={license_obj.payload.tenant_id}"
        )

        # IMPORTANT: Use the ORIGINAL payload JSON for signature verification,
        # not re-serialized through Pydantic. Pydantic may format fields differently
        # (e.g., datetime "+00:00" vs "Z") which would break signature verification.
        original_payload = decoded.get("payload", {})
        payload_json = json.dumps(original_payload, sort_keys=True)
        signature_bytes = base64.b64decode(license_obj.signature)

        # Verify signature using PSS padding (modern standard)
        logger.info("[verify_license] Loading public key...")
        public_key = _get_public_key()
        logger.info("[verify_license] Verifying signature...")

        public_key.verify(
            signature_bytes,
            payload_json.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )

        logger.info(
            f"[verify_license] SUCCESS: license verified for tenant {license_obj.payload.tenant_id}"
        )
        return license_obj.payload

    except InvalidSignature:
        logger.error("[verify_license] FAILED: Signature verification failed")
        raise ValueError("Invalid license signature")
    except json.JSONDecodeError as e:
        logger.error(f"[verify_license] FAILED: JSON decode error: {e}")
        raise ValueError("Invalid license format: not valid JSON")
    except (ValueError, KeyError, TypeError) as e:
        logger.error(
            f"[verify_license] FAILED: Validation error: {type(e).__name__}: {e}"
        )
        raise ValueError(f"Invalid license format: {type(e).__name__}: {e}")
    except Exception:
        logger.exception("[verify_license] FAILED: Unexpected error")
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
