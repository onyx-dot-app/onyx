from cryptography.hazmat.primitives.serialization import pkcs12

from onyx.utils.logger import setup_logger

logger = setup_logger()


def _is_password_related_error(error: Exception) -> bool:
    """
    Check if the exception indicates a password-related issue rather than a format issue.
    """
    error_msg = str(error).lower()
    password_keywords = ["mac", "integrity", "password", "authentication", "verify"]
    return any(keyword in error_msg for keyword in password_keywords)


def validate_pkcs12_content(file_bytes: bytes) -> bool:
    """
    Validate that the file content is actually a PKCS#12 file.
    This performs basic format validation without requiring passwords.
    """
    try:
        # Basic file size check
        if len(file_bytes) < 10:
            logger.debug("File too small to be a valid PKCS#12 file")
            return False

        # Check for PKCS#12 magic bytes/ASN.1 structure
        # PKCS#12 files start with ASN.1 SEQUENCE tag (0x30)
        if file_bytes[0] != 0x30:
            logger.debug("File does not start with ASN.1 SEQUENCE tag")
            return False

        # Try to parse the outer ASN.1 structure without password validation
        # This checks if the file has the basic PKCS#12 structure
        try:
            # Attempt to load just to validate the basic format
            # We expect this to fail due to password, but it should fail with a specific error
            pkcs12.load_key_and_certificates(file_bytes, password=None)
            return True
        except ValueError as e:
            # Check if the error is related to password (expected) vs format issues
            if _is_password_related_error(e):
                # These errors indicate the file format is correct but password is wrong/missing
                logger.debug(
                    f"PKCS#12 format appears valid, password-related error: {e}"
                )
                return True
            else:
                # Other ValueError likely indicates format issues
                logger.debug(f"PKCS#12 format validation failed: {e}")
                return False
        except Exception as e:
            # Try with empty password as fallback
            try:
                pkcs12.load_key_and_certificates(file_bytes, password=b"")
                return True
            except ValueError as e2:
                if _is_password_related_error(e2):
                    logger.debug(
                        f"PKCS#12 format appears valid with empty password attempt: {e2}"
                    )
                    return True
                else:
                    logger.debug(
                        f"PKCS#12 validation failed on both attempts: {e}, {e2}"
                    )
                    return False
            except Exception:
                logger.debug(f"PKCS#12 validation failed: {e}")
                return False

    except Exception as e:
        logger.debug(f"Unexpected error during PKCS#12 validation: {e}")
        return False
