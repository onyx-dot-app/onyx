"""
Redis IAM Authentication Module
This module provides Redis IAM authentication functionality for AWS ElastiCache.
Unlike RDS IAM auth, Redis IAM auth relies on IAM roles and policies rather than
generating authentication tokens.
Key functions:
- configure_redis_iam_auth: Configure Redis connection parameters for IAM auth
- create_redis_ssl_context_if_iam: Create SSL context for secure connections
"""

import ssl
from typing import Any


def configure_redis_iam_auth(connection_kwargs: dict[str, Any]) -> None:
    """
    Configure Redis connection parameters for IAM authentication.
    Modifies the connection_kwargs dict in-place to:
    1. Remove password (not needed with IAM)
    2. Enable SSL with system CA certificates
    3. Set proper SSL context for secure connections
    """
    # Remove password as it's not needed with IAM authentication
    if "password" in connection_kwargs:
        del connection_kwargs["password"]

    # Ensure SSL is enabled for IAM authentication
    connection_kwargs["ssl"] = True
    connection_kwargs["ssl_context"] = create_redis_ssl_context_if_iam()


def create_redis_ssl_context_if_iam() -> ssl.SSLContext:
    """Create an SSL context for Redis IAM authentication using system CA certificates."""
    # Use system CA certificates by default - no need for additional CA files
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = True
    ssl_context.verify_mode = ssl.CERT_REQUIRED
    return ssl_context
