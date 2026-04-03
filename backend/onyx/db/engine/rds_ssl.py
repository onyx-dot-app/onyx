"""
SSL connection handling for PostgreSQL.

This module provides SSL context creation for PostgreSQL connections,
particularly for AWS RDS which requires SSL. SSL can be enabled via:
- USE_IAM_AUTH=true (IAM auth always requires SSL)
- POSTGRES_REQUIRE_SSL=true (explicitly enable SSL for any PostgreSQL)

When SSL is not required, this module is not used and connections
proceed without SSL (suitable for local development).
"""

import functools
import os
import ssl

from onyx.utils.logger import setup_logger

logger = setup_logger()


def _find_rds_ca_bundle() -> str | None:
    """
    Find the RDS SSL certificate bundle.
    Tries multiple locations in order.

    Returns:
        Path to certificate file, or None if not found
    """
    # Try multiple possible locations
    possible_paths = [
        "/app/bundle.pem",  # Primary location (volume mount or in image)
        "bundle.pem",  # Current directory
        "/etc/ssl/certs/bundle.pem",  # System certs location
        os.path.join(os.getcwd(), "bundle.pem"),  # Explicit pwd
    ]

    for path in possible_paths:
        if os.path.exists(path):
            try:
                # Verify it's readable and is a valid file
                size = os.path.getsize(path)
                if size > 0:
                    logger.info(f"Found RDS CA bundle at: {path} (size: {size} bytes)")
                    return path
                else:
                    logger.warning(f"Found RDS CA bundle at {path} but file is empty")
            except Exception as e:
                logger.warning(f"Found {path} but cannot read: {e}")

    logger.warning(f"RDS CA bundle not found. Searched: {possible_paths}")
    return None


@functools.cache
def get_rds_ssl_context() -> ssl.SSLContext:
    """
    Create SSL context for PostgreSQL connections (primarily for RDS).

    Always returns a valid SSL context. Uses RDS CA bundle if available,
    otherwise falls back to system certificates.

    This function should only be called when SSL is required
    (USE_IAM_AUTH=true or POSTGRES_REQUIRE_SSL=true).

    Returns:
        ssl.SSLContext: Configured SSL context

    Raises:
        RuntimeError: If SSL context cannot be created (should never happen)
    """
    cert_path = _find_rds_ca_bundle()

    if cert_path:
        try:
            context = ssl.create_default_context(cafile=cert_path)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_REQUIRED
            return context
        except Exception as e:
            logger.error(f"Failed to create SSL context with {cert_path}: {e}")
            logger.error("Will fall back to system CA certificates")

    # Fallback: create SSL context without specific RDS cert
    try:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_REQUIRED
        return context
    except Exception as e:
        logger.error(f"Cannot create SSL context: {e}")
        raise RuntimeError(f"Failed to create SSL context for RDS: {e}")


def get_rds_ssl_context_or_require() -> ssl.SSLContext | str:
    """
    Get SSL configuration for asyncpg connections.

    Returns "require" string for asyncpg, which ensures SSL is used
    and delegates certificate verification to asyncpg's defaults.

    This function should only be called when SSL is required
    (USE_IAM_AUTH=true or POSTGRES_REQUIRE_SSL=true).

    Returns:
        str: "require" string for asyncpg SSL mode
    """
    return "require"
