from typing import Any
from typing import Dict

import requests

API_SERVER_URL = "http://localhost:3000"  # Adjust this to your Onyx server URL
HEADERS = {"Content-Type": "application/json"}
API_KEY = "onyx-api-key"  # API key here, if auth is enabled


def create_connector(
    name: str,
    source: str,
    input_type: str,
    connector_specific_config: Dict[str, Any],
    is_public: bool = True,
    groups: list[int] | None = None,
) -> Dict[str, Any]:
    connector_update_request = {
        "name": name,
        "source": source,
        "input_type": input_type,
        "connector_specific_config": connector_specific_config,
        "is_public": is_public,
        "groups": groups or [],
    }

    response = requests.post(
        url=f"{API_SERVER_URL}/api/manage/admin/connector",
        json=connector_update_request,
        headers=HEADERS,
    )
    response.raise_for_status()
    return response.json()


def create_credential(
    name: str,
    source: str,
    credential_json: Dict[str, Any],
    is_public: bool = True,
    groups: list[int] | None = None,
) -> Dict[str, Any]:
    credential_request = {
        "name": name,
        "source": source,
        "credential_json": credential_json,
        "admin_public": is_public,
        "groups": groups or [],
    }

    response = requests.post(
        url=f"{API_SERVER_URL}/api/manage/credential",
        json=credential_request,
        headers=HEADERS,
    )
    response.raise_for_status()
    return response.json()


def create_cc_pair(
    connector_id: int,
    credential_id: int,
    name: str,
    access_type: str = "public",
    groups: list[int] | None = None,
) -> Dict[str, Any]:
    cc_pair_request = {
        "name": name,
        "access_type": access_type,
        "groups": groups or [],
    }

    response = requests.put(
        url=f"{API_SERVER_URL}/api/manage/connector/{connector_id}/credential/{credential_id}",
        json=cc_pair_request,
        headers=HEADERS,
    )
    response.raise_for_status()
    return response.json()


def main() -> None:
    # Create a Web connector
    web_connector = create_connector(
        name="Example Web Connector",
        source="web",
        input_type="load_state",
        connector_specific_config={
            "base_url": "https://example.com",
            "web_connector_type": "recursive",
        },
    )
    print(f"Created Web Connector: {web_connector}")

    # Create a credential for the Web connector
    web_credential = create_credential(
        name="Example Web Credential",
        source="web",
        credential_json={},  # Web connectors typically don't need credentials
        is_public=True,
    )
    print(f"Created Web Credential: {web_credential}")

    # Create CC pair for Web connector
    web_cc_pair = create_cc_pair(
        connector_id=web_connector["id"],
        credential_id=web_credential["id"],
        name="Example Web CC Pair",
        access_type="public",
    )
    print(f"Created Web CC Pair: {web_cc_pair}")

    # Create a GitHub connector
    github_connector = create_connector(
        name="Example GitHub Connector",
        source="github",
        input_type="poll",
        connector_specific_config={
            "repo_owner": "example-owner",
            "repo_name": "example-repo",
            "include_prs": True,
            "include_issues": True,
        },
    )
    print(f"Created GitHub Connector: {github_connector}")

    # Create a credential for the GitHub connector
    github_credential = create_credential(
        name="Example GitHub Credential",
        source="github",
        credential_json={"github_access_token": "your_github_access_token_here"},
        is_public=True,
    )
    print(f"Created GitHub Credential: {github_credential}")

    # Create CC pair for GitHub connector
    github_cc_pair = create_cc_pair(
        connector_id=github_connector["id"],
        credential_id=github_credential["id"],
        name="Example GitHub CC Pair",
        access_type="public",
    )
    print(f"Created GitHub CC Pair: {github_cc_pair}")


if __name__ == "__main__":
    main()
