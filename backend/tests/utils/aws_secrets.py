"""
Secrets utilities for fetching test secrets.

Secrets are resolved in order:
    1. Environment variables (already set in the process)
    2. .env file at the repo root (loaded via dotenv)
    3. AWS Secrets Manager (batch fetch for any remaining keys)

The AWS environment (prefix) is derived from the enum type passed in, so
mixing ``TestSecret`` and ``DeploySecret`` values in one call is rejected
by the type checker.

Usage:
    In conftest.py, set up a session-scoped fixture driven by the
    ``@pytest.mark.secrets(...)`` markers collected from tests:

        @pytest.fixture(scope="session")
        def test_secrets(request) -> dict[TestSecret, str]:
            needed = getattr(request.config, "_onyx_test_secrets_needed", set())
            return get_secrets(sorted(needed, key=lambda s: s.value))

    Then in a test module:

        @pytest.mark.secrets(TestSecret.OPENAI_API_KEY)
        def test_openai(openai_client): ...

Configuration via OS environment variables:
    - AWS_REGION: AWS region for Secrets Manager (default: "us-east-2")

AWS SSO Authentication:
    boto3 automatically uses SSO credentials if configured in ~/.aws/config.
    Run ``aws sso login`` to authenticate before running tests.
"""

import logging
import os
from collections.abc import Sequence
from typing import cast
from typing import overload

from dotenv import dotenv_values

from tests.utils.secret_names import AnySecret
from tests.utils.secret_names import DeploySecret
from tests.utils.secret_names import TestSecret

logger = logging.getLogger(__name__)

AWS_REGION = os.environ.get("AWS_REGION", "us-east-2")

_DOTENV_PATH = os.path.join(
    os.path.dirname(__file__), os.pardir, os.pardir, os.pardir, ".vscode", ".env"
)


def _get_local_secrets(keys: Sequence[AnySecret]) -> dict[AnySecret, str]:
    """Resolve secrets from ``os.environ`` first, then ``.vscode/.env``."""
    dotenv = dotenv_values(_DOTENV_PATH)
    found: dict[AnySecret, str] = {}

    for key in keys:
        env_val = os.environ.get(key.value)
        value = env_val if env_val is not None else dotenv.get(key.value)
        if value:
            found[key] = value

    return found


def _get_aws_secrets(
    keys: Sequence[AnySecret],
    enum_type: type[AnySecret],
) -> dict[AnySecret, str]:
    """Fetch secrets from AWS Secrets Manager in a single batch request."""
    import boto3
    from botocore.exceptions import ClientError

    prefix = enum_type.aws_prefix()

    session = boto3.Session()
    client = session.client(
        service_name="secretsmanager",
        region_name=AWS_REGION,
    )

    secret_ids = [f"{prefix}{name.value}" for name in keys]

    try:
        response = client.batch_get_secret_value(SecretIdList=secret_ids)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        if error_code == "AccessDeniedException":
            raise RuntimeError(
                f"Access denied to secrets with prefix '{prefix}'. "
                f"Please check your AWS credentials/permissions or run 'aws sso login'."
            ) from e
        elif error_code == "UnrecognizedClientException":
            raise RuntimeError(
                "AWS credentials not found or expired. "
                "If using SSO, run 'aws sso login' to authenticate."
            ) from e
        else:
            raise RuntimeError(
                f"Failed to fetch secrets from AWS Secrets Manager: {e}"
            ) from e

    secrets: dict[AnySecret, str] = {}
    for secret in response.get("SecretValues", []):
        secret_id = secret.get("Name", "")
        secret_value = secret.get("SecretString")

        if secret_value:
            key_name = (
                secret_id[len(prefix) :] if secret_id.startswith(prefix) else secret_id
            )
            try:
                secrets[enum_type(key_name)] = secret_value
            except ValueError:
                logger.warning(
                    f"Secret '{key_name}' not in {enum_type.__name__}, skipping"
                )

    for error in response.get("Errors", []):
        secret_id = error.get("SecretId", "unknown")
        error_code = error.get("ErrorCode", "unknown")
        message = error.get("Message", "unknown error")
        logger.warning(
            f"Failed to fetch secret '{secret_id}': [{error_code}] {message}"
        )

    return secrets


@overload
def get_secrets(keys: list[TestSecret]) -> dict[TestSecret, str]: ...
@overload
def get_secrets(keys: list[DeploySecret]) -> dict[DeploySecret, str]: ...
def get_secrets(
    keys: list[TestSecret] | list[DeploySecret],
) -> dict[TestSecret, str] | dict[DeploySecret, str]:
    """Resolve secrets from local sources, then AWS Secrets Manager.

    The AWS prefix is derived from the enum type of the keys. All keys must
    belong to the same enum; mixing environments in one call is a programming
    error (and the type checker will reject it at call sites).
    """
    if not keys:
        return cast("dict[TestSecret, str]", {})

    enum_type = type(keys[0])
    if not all(isinstance(k, enum_type) for k in keys):
        raise ValueError(
            "All secrets passed to get_secrets() must belong to the same enum "
            f"(got a mix including {enum_type.__name__})"
        )

    secrets = _get_local_secrets(keys)

    if secrets:
        local_names = ", ".join(k.value for k in secrets)
        logger.info(f"Resolved {len(secrets)} secret(s) locally: {local_names}")

    remaining: list[AnySecret] = [k for k in keys if k not in secrets]
    if remaining:
        aws_secrets = _get_aws_secrets(remaining, enum_type)
        secrets.update(aws_secrets)
        logger.info(
            f"Fetched {len(aws_secrets)}/{len(remaining)} secret(s) from AWS "
            f"(prefix: {enum_type.aws_prefix()!r})"
        )

    return cast("dict[TestSecret, str] | dict[DeploySecret, str]", secrets)
