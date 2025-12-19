import os
from typing import Any

import pytest


@pytest.fixture
def confluence_connector_config() -> dict[str, Any]:
    url_base = os.environ.get("CONFLUENCE_TEST_SPACE_URL")
    space_key = os.environ.get("CONFLUENCE_SPACE_KEY")
    page_id = os.environ.get("CONFLUENCE_PAGE_ID")
    is_cloud = os.environ.get("CONFLUENCE_IS_CLOUD", "true").lower() == "true"

    assert url_base, "CONFLUENCE_URL environment variable is required"

    return {
        "wiki_base": url_base,
        "is_cloud": is_cloud,
        "space": space_key or "",
        "page_id": page_id or "",
    }


@pytest.fixture
def confluence_credential_json() -> dict[str, Any]:
    username = os.environ.get("CONFLUENCE_USER_NAME")
    access_token = os.environ.get("CONFLUENCE_ACCESS_TOKEN")

    assert username, "CONFLUENCE_USERNAME environment variable is required"
    assert access_token, "CONFLUENCE_ACCESS_TOKEN environment variable is required"

    return {
        "confluence_username": username,
        "confluence_access_token": access_token,
    }
