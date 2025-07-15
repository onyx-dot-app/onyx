import os
from typing import Any

import pytest


@pytest.fixture
def confluence_connector_config() -> dict[str, Any]:
    url_base = os.environ.get("CONFLUENCE_URL")
    space_key = os.environ.get("CONFLUENCE_SPACE_KEY")
    page_id = os.environ.get("CONFLUENCE_PAGE_ID")
    is_cloud = os.environ.get("CONFLUENCE_IS_CLOUD", "").lower() == "true"

    assert url_base

    return {
        "wiki_base": url_base,
        "is_cloud": is_cloud,
        "space": space_key or "",
        "page_id": page_id or "",
    }


@pytest.fixture
def confluence_credential_json() -> dict[str, Any]:
    username = os.environ.get("CONFLUENCE_USERNAME")
    access_token = os.environ.get("CONFLUENCE_ACCESS_TOKEN")

    assert username
    assert access_token

    return {
        "confluence_username": username,
        "confluence_access_token": access_token,
    }
