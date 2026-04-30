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
    BEDROCK_API_KEY = "bedrock-api-key"

    # Connector test secrets. Member names match the CI env var; values match
    # the AWS Secrets Manager key (the suffix after the ``test/`` prefix).
    AWS_ACCESS_KEY_ID_DAILY_CONNECTOR_TESTS = "aws-access-key-id"
    AWS_SECRET_ACCESS_KEY_DAILY_CONNECTOR_TESTS = "aws-secret-access-key"
    R2_ACCESS_KEY_ID_DAILY_CONNECTOR_TESTS = "r2-access-key-id"
    R2_SECRET_ACCESS_KEY_DAILY_CONNECTOR_TESTS = "r2-secret-access-key"
    GCS_ACCESS_KEY_ID_DAILY_CONNECTOR_TESTS = "gcs-access-key-id"
    GCS_SECRET_ACCESS_KEY_DAILY_CONNECTOR_TESTS = "gcs-secret-access-key"
    CONFLUENCE_ACCESS_TOKEN = "confluence-access-token"
    CONFLUENCE_ACCESS_TOKEN_SCOPED = "confluence-access-token-scoped"
    JIRA_BASE_URL = "jira-base-url"
    JIRA_ADMIN_USER_EMAIL = "jira-admin-user-email"
    JIRA_USER_EMAIL = "jira-user-email"
    JIRA_API_TOKEN = "jira-api-token"
    JIRA_API_TOKEN_SCOPED = "jira-api-token-scoped"
    GONG_ACCESS_KEY = "gong-access-key"
    GONG_ACCESS_KEY_SECRET = "gong-access-key-secret"
    GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR = "google-drive-service-account-json"
    GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON_STR_TEST_USER_1 = (
        "google-drive-oauth-creds-test-user-1"
    )
    GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON_STR = "google-drive-oauth-creds"
    GOOGLE_GMAIL_SERVICE_ACCOUNT_JSON_STR = "google-gmail-service-account-json"
    GOOGLE_GMAIL_OAUTH_CREDENTIALS_JSON_STR = "google-gmail-oauth-creds"
    SLAB_BOT_TOKEN = "slab-bot-token"
    ZENDESK_SUBDOMAIN = "zendesk-subdomain"
    ZENDESK_EMAIL = "zendesk-email"
    ZENDESK_TOKEN = "zendesk-token"
    SF_PASSWORD = "sf-password"
    SF_SECURITY_TOKEN = "sf-security-token"
    HUBSPOT_ACCESS_TOKEN = "hubspot-access-token"
    IMAP_PASSWORD = "imap-password"
    AIRTABLE_ACCESS_TOKEN = "airtable-access-token"
    SHAREPOINT_CLIENT_SECRET = "sharepoint-client-secret"
    PERM_SYNC_SHAREPOINT_CLIENT_ID = "perm-sync-sharepoint-client-id"
    PERM_SYNC_SHAREPOINT_PRIVATE_KEY = "perm-sync-sharepoint-private-key"
    PERM_SYNC_SHAREPOINT_CERTIFICATE_PASSWORD = "perm-sync-sharepoint-cert-password"
    PERM_SYNC_SHAREPOINT_DIRECTORY_ID = "perm-sync-sharepoint-directory-id"
    ACCESS_TOKEN_GITHUB = "github-access-token"
    GITLAB_ACCESS_TOKEN = "gitlab-access-token"
    GITBOOK_SPACE_ID = "gitbook-space-id"
    GITBOOK_API_KEY = "gitbook-api-key"
    NOTION_INTEGRATION_TOKEN = "notion-integration-token"
    HIGHSPOT_KEY = "highspot-key"
    HIGHSPOT_SECRET = "highspot-secret"
    SLACK_BOT_TOKEN = "slack-bot-token"
    DISCORD_CONNECTOR_BOT_TOKEN = "discord-bot-token"
    TEAMS_APPLICATION_ID = "teams-application-id"
    TEAMS_DIRECTORY_ID = "teams-directory-id"
    TEAMS_SECRET = "teams-secret"
    BITBUCKET_WORKSPACE = "bitbucket-workspace"
    BITBUCKET_API_TOKEN = "bitbucket-api-token"
    FIREFLIES_API_KEY = "fireflies-api-key"

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
