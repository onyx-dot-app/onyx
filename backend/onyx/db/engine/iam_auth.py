import functools
import os
import ssl
from typing import Any

import boto3

from onyx.configs.app_configs import (
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_USER,
    USE_IAM_AUTH,
)
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


def make_provide_iam_token(host: str, port: str, user: str) -> Any:
    """`do_connect` handler that mints a token for *these* coordinates.

    RDS scopes an IAM auth token to a specific hostname, port, and user, so a shard
    on different coordinates cannot reuse the token built from the global POSTGRES_*
    settings — the connection is rejected and every tenant on that shard is
    unreachable.
    """

    def _provide(
        dialect: Any,  # noqa: ARG001
        conn_rec: Any,  # noqa: ARG001
        cargs: Any,  # noqa: ARG001
        cparams: Any,
    ) -> None:
        if not USE_IAM_AUTH:
            return
        region = os.getenv("AWS_REGION_NAME", "us-east-2")
        configure_psycopg2_iam_auth(cparams, host, port, user, region)

    return _provide


# The default engine's handler: the general one bound to the global coordinates.
provide_iam_token = make_provide_iam_token(POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER)


@functools.cache
def create_ssl_context_if_iam() -> ssl.SSLContext | None:
    """Create an SSL context if IAM authentication is enabled, else return None."""
    if USE_IAM_AUTH:
        return ssl.create_default_context(cafile=SSL_CERT_FILE)
    return None
