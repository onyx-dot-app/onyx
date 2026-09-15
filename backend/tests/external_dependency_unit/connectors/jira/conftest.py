import os
from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

JIRA_ADMIN_USER_EMAIL_ENV = "JIRA_ADMIN_USER_EMAIL"
JIRA_ADMIN_API_TOKEN_ENV = "JIRA_ADMIN_API_TOKEN"


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
def jira_credentials() -> JiraTestCredentials:
    return JiraTestCredentials(
        user_email=os.environ[JIRA_ADMIN_USER_EMAIL_ENV],
        api_token=SecretStr(os.environ[JIRA_ADMIN_API_TOKEN_ENV]),
    )
