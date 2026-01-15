"""
AWS Secrets Manager utilities for fetching test secrets.

Usage:
    In conftest.py, set up a session-scoped fixture:

        @pytest.fixture(scope="session")
        def test_secrets() -> dict[SecretName, str]:
            return get_aws_secrets(
                [SecretName.OPENAI_API_KEY, SecretName.COHERE_API_KEY],
                environment=Environment.TEST,
            )

    Then use in test fixtures:

        @pytest.fixture
        def openai_client(test_secrets: dict[SecretName, str]) -> OpenAI:
            return OpenAI(api_key=test_secrets[SecretName.OPENAI_API_KEY])

Configuration via OS environment variables:
    - AWS_REGION: AWS region for Secrets Manager (default: "us-east-1")
    - AWS_PROFILE: (Optional) AWS profile to use for SSO authentication

AWS SSO Authentication:
    boto3 automatically uses SSO credentials if configured in ~/.aws/config.
    Run `aws sso login` to authenticate before running tests.
"""

import logging
import os
from pathlib import Path
from typing import Any

import boto3
import yaml
from botocore.exceptions import ClientError

from tests.utils.secret_names import Environment
from tests.utils.secret_names import SecretName

logger = logging.getLogger(__name__)

# AWS Secrets Manager configuration
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


def _load_secrets_yaml() -> dict[str, Any]:
    """Load the secrets configuration from YAML."""
    yaml_path = Path(__file__).parent / "secrets.yaml"
    with open(yaml_path) as f:
        return yaml.safe_load(f)


def _get_prefix_for_environment(environment: Environment) -> str:
    """Get the AWS secret prefix for an environment from YAML config."""
    config = _load_secrets_yaml()
    environments = config.get("environments", {})
    if environment in environments:
        return environments[environment].get("prefix", f"onyx/{environment}/")
    return f"onyx/{environment}/"


def get_aws_secrets(
    keys: list[SecretName],
    environment: Environment = Environment.TEST,
) -> dict[SecretName, str]:
    """
    Fetch secrets from AWS Secrets Manager in a single batch request.

    Typically called once at test session startup via a session-scoped fixture.

    Args:
        keys: List of secret names to fetch. All are fetched in one API call.
        environment: The environment to fetch from (default: Environment.TEST).

    Returns:
        dict: Mapping of SecretName to secret values.

    Raises:
        RuntimeError: If secrets cannot be fetched due to auth/access issues.
    """
    if not keys:
        return {}

    prefix = _get_prefix_for_environment(environment)

    session = boto3.Session()
    client = session.client(
        service_name="secretsmanager",
        region_name=AWS_REGION,
    )

    secret_ids = [f"{prefix}{name}" for name in keys]

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

    # Build result dict from response
    secrets: dict[SecretName, str] = {}
    for secret in response.get("SecretValues", []):
        secret_id = secret.get("Name", "")
        secret_value = secret.get("SecretString")

        if secret_value:
            if secret_id.startswith(prefix):
                key_name = secret_id[len(prefix) :]
            else:
                key_name = secret_id
            # Convert string back to SecretName enum
            try:
                secrets[SecretName(key_name)] = secret_value
            except ValueError:
                # Secret exists in AWS but not in SecretName enum - skip
                logger.warning(f"Secret '{key_name}' not in SecretName enum, skipping")

    # Log any errors for individual secrets
    for error in response.get("Errors", []):
        secret_id = error.get("SecretId", "unknown")
        error_code = error.get("ErrorCode", "unknown")
        message = error.get("Message", "unknown error")
        logger.warning(
            f"Failed to fetch secret '{secret_id}': [{error_code}] {message}"
        )

    logger.info(
        f"Fetched {len(secrets)}/{len(keys)} secrets from AWS "
        f"(environment: {environment})"
    )

    return secrets
