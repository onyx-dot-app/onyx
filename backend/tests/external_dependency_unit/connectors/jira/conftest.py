import os
from typing import Any

import pytest


@pytest.fixture
def jira_connector_config() -> dict[str, Any]:
    jira_base_url = os.environ.get("JIRA_BASE_URL", "https://danswerai.atlassian.net")

    return {
        "jira_base_url": jira_base_url,
        "project_key": "",  # Empty to sync all projects
        "scoped_token": False,
    }


@pytest.fixture
def jira_credential_json() -> dict[str, Any]:
    user_email = os.environ.get("JIRA_USER_EMAIL")
    api_token = os.environ.get("JIRA_API_TOKEN")

    assert user_email, "JIRA_USER_EMAIL environment variable is required"
    assert api_token, "JIRA_API_TOKEN environment variable is required"

    return {
        "jira_user_email": user_email,
        "jira_api_token": api_token,
    }
