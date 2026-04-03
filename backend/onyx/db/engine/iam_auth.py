import functools
import os
import ssl
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError
from botocore.exceptions import ClientError

from onyx.configs.app_configs import POSTGRES_HOST
from onyx.configs.app_configs import POSTGRES_PORT
from onyx.configs.app_configs import POSTGRES_USER
from onyx.configs.app_configs import USE_IAM_AUTH
from onyx.configs.constants import SSL_CERT_FILE
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_iam_auth_token(
    host: str, port: str, user: str, region: str = "us-east-2"
) -> str:
    """
    Generate an IAM authentication token using boto3 for AWS RDS.

    This function should only be called when USE_IAM_AUTH=true.
    Requires AWS credentials to be available (IAM role, env vars, or credentials file).

    Args:
        host: RDS instance hostname
        port: PostgreSQL port (typically 5432)
        user: Database username (must match IAM database user)
        region: AWS region where RDS instance is located

    Returns:
        str: IAM authentication token (valid for 15 minutes)

    Raises:
        RuntimeError: If token generation fails or AWS credentials unavailable
    """
    try:
        client = boto3.client("rds", region_name=region)

        # Check if we can get credentials
        session = boto3.Session()
        credentials = session.get_credentials()
        if not credentials:
            raise RuntimeError(
                "No AWS credentials available - cannot generate IAM token"
            )

        # Generate token
        token = client.generate_db_auth_token(
            DBHostname=host, Port=int(port), DBUsername=user
        )

        if not token:
            raise RuntimeError("Token generation returned None")

        return token

    except (BotoCoreError, ClientError) as e:
        logger.error(f"AWS error generating IAM token: {e}")
        raise RuntimeError(f"Failed to generate IAM authentication token: {e}")
    except Exception as e:
        logger.error(f"Unexpected error generating IAM token: {e}")
        raise RuntimeError(f"Unexpected error generating IAM token: {e}")


def configure_psycopg2_iam_auth(
    cparams: dict[str, Any], host: str, port: str, user: str, region: str
) -> None:
    """
    Configure connection parameters for psycopg2 with IAM token and SSL.

    Generates a fresh IAM authentication token and configures SSL requirement
    for the database connection. IAM authentication always requires SSL.

    Args:
        cparams: psycopg2 connection parameters dictionary to modify
        host: RDS instance hostname
        port: PostgreSQL port
        user: Database username
        region: AWS region

    Raises:
        RuntimeError: If token generation fails or returns None
    """
    token = get_iam_auth_token(host, port, user, region)

    if not token:
        raise RuntimeError("IAM token is None after generation")

    cparams["password"] = token
    cparams["sslmode"] = "require"


def provide_iam_token(
    dialect: Any,  # noqa: ARG001
    conn_rec: Any,  # noqa: ARG001
    cargs: Any,  # noqa: ARG001
    cparams: Any,
) -> None:
    """
    SQLAlchemy event listener for 'do_connect' event.

    Provides IAM token for psycopg2 connections when USE_IAM_AUTH=true.
    Called automatically before each database connection is established
    to inject a fresh IAM token (tokens expire after 15 minutes).

    Only activates when USE_IAM_AUTH environment variable is set to true.
    """
    if USE_IAM_AUTH:
        host = POSTGRES_HOST
        port = POSTGRES_PORT
        user = POSTGRES_USER
        region = os.getenv("AWS_REGION_NAME", "us-east-2")

        try:
            configure_psycopg2_iam_auth(cparams, host, port, user, region)
        except Exception as e:
            logger.error(f"Failed to provide IAM token: {e}")
            raise


@functools.cache
def create_ssl_context_if_iam() -> ssl.SSLContext | None:
    """
    Create an SSL context if IAM authentication is enabled, else return None.

    Note: This function is primarily for backward compatibility.
    New code should use get_rds_ssl_context_or_require() from rds_ssl module.

    Returns:
        ssl.SSLContext if USE_IAM_AUTH=true, None otherwise
    """
    if USE_IAM_AUTH:
        return ssl.create_default_context(cafile=SSL_CERT_FILE)
    return None
