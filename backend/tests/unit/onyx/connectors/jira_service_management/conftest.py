import pytest


@pytest.fixture
def jira_base_url() -> str:
    return "https://jira.example.com"
