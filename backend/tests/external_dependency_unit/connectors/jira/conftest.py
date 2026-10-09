from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from tests.utils.secret_names import TestSecret


class JiraTestCredentials(BaseModel):
    user_email: str
    api_token: SecretStr

    def as_credential_json(self) -> dict[str, str]:
        return {
            "jira_user_email": self.user_email,
            "jira_api_token": self.api_token.get_secret_value(),
        }


@pytest.fixture
def jira_connector_config() -> dict[str, Any]:
    return {
        "jira_base_url": "https://danswerai.atlassian.net",
        "project_key": "",  # Empty to sync all projects
        "scoped_token": False,
    }


@pytest.fixture
def jira_credentials(
    test_secrets: dict[TestSecret, str],
) -> JiraTestCredentials:
    return JiraTestCredentials(
        user_email=test_secrets[TestSecret.JIRA_USER_EMAIL],
        api_token=SecretStr(test_secrets[TestSecret.JIRA_API_TOKEN]),
    )


@pytest.fixture
def jira_credential_json(
    jira_credentials: JiraTestCredentials,
) -> dict[str, str]:
    return jira_credentials.as_credential_json()
