import os
import ssl
from typing import Any

import boto3

from onyx.configs.app_configs import POSTGRES_HOST
from onyx.configs.app_configs import POSTGRES_PORT
from onyx.configs.app_configs import POSTGRES_USER
from onyx.configs.app_configs import USE_IAM_AUTH
from onyx.configs.constants import SSL_CERT_FILE


def get_iam_auth_token(
    host: str, port: str, user: str, region: str = "us-east-2"
) -> str:
    """
    Generate an IAM authentication token using boto3.
    """
    client = boto3.client("rds", region_name=region)
    token = client.generate_db_auth_token(
        DBHostname=host, Port=int(port), DBUsername=user
    )
    return token


def configure_psycopg2_iam_auth(
    cparams: dict[str, Any], host: str, port: str, user: str, region: str
) -> None:
    """
    Configure cparams for psycopg2 with IAM token and SSL.
    """
    token = get_iam_auth_token(host, port, user, region)
    cparams["password"] = token
    cparams["sslmode"] = "require"
    cparams["sslrootcert"] = SSL_CERT_FILE


def provide_iam_token(dialect: Any, conn_rec: Any, cargs: Any, cparams: Any) -> None:
    if USE_IAM_AUTH:
        host = POSTGRES_HOST
        port = POSTGRES_PORT
        user = POSTGRES_USER
        region = os.getenv("AWS_REGION_NAME", "us-east-2")
        # Configure for psycopg2 with IAM token
        configure_psycopg2_iam_auth(cparams, host, port, user, region)


def create_ssl_context_if_iam() -> ssl.SSLContext | None:
    """Create an SSL context if IAM authentication is enabled, else return None."""
    if USE_IAM_AUTH:
        return ssl.create_default_context(cafile=SSL_CERT_FILE)
    return None


ssl_context = create_ssl_context_if_iam()
