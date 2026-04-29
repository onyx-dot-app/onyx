"""
Secret name enums for test secrets.

Each AWS Secrets Manager environment gets its own enum class. The environment
is derived from the enum type when fetching, so the type checker ensures you
can't mix secrets from different environments in a single batch call.

Usage:
    from tests.utils.aws_secrets import get_secrets
    from tests.utils.secret_names import TestSecret

    secrets = get_secrets([TestSecret.OPENAI_API_KEY, TestSecret.COHERE_API_KEY])
"""

from enum import StrEnum


class TestSecret(StrEnum):
    """Secrets available in the test environment (AWS prefix: ``test/``)."""

    __test__ = False

    OPENAI_API_KEY = "OPENAI_API_KEY"
    COHERE_API_KEY = "COHERE_API_KEY"
    AZURE_API_KEY = "AZURE_API_KEY"
    AZURE_API_URL = "AZURE_API_URL"
    LITELLM_API_KEY = "LITELLM_API_KEY"
    LITELLM_API_URL = "LITELLM_API_URL"
    OLLAMA_API_KEY = "OLLAMA_API_KEY"

    @classmethod
    def aws_prefix(cls) -> str:
        return "test/"


class DeploySecret(StrEnum):
    """Secrets available in the deploy environment (AWS prefix: ``deploy/``).

    Add members here when deploy-scoped secrets are needed.
    """

    @classmethod
    def aws_prefix(cls) -> str:
        return "deploy/"


AnySecret = TestSecret | DeploySecret
