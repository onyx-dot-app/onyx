import json
from typing import Any
from typing import Dict

import requests

API_SERVER_URL = "http://localhost:3000"
API_KEY = "onyx-api-key"  # API key here, if auth is enabled
HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}


def create_connector(
    name: str,
    source: str,
    input_type: str,
    connector_specific_config: Dict[str, Any],
    is_public: bool = True,
    groups: list[int] | None = None,
    access_type: str = "public",
) -> Dict[str, Any]:
    connector_update_request = {
        "name": name + " Connector",
        "source": source,
        "input_type": input_type,
        "connector_specific_config": connector_specific_config,
        "is_public": is_public,
        "groups": groups or [],
        "access_type": access_type,
    }
    try:
        response = requests.post(
            url=f"{API_SERVER_URL}/api/manage/admin/connector",
            json=connector_update_request,
            headers=HEADERS,
        )
        response.raise_for_status()
        return response.json()

    except requests.exceptions.HTTPError as e:
        print(f"Error response body: {e.response.text}")
        raise


def create_credential(
    name: str,
    source: str,
    credential_json: Dict[str, Any],
    is_public: bool = True,
    groups: list[int] | None = None,
) -> Dict[str, Any]:
    credential_request = {
        "name": name + " Credential",
        "source": source,
        "credential_json": credential_json,
        "admin_public": is_public,
        "groups": groups or [],
    }

    try:
        response = requests.post(
            url=f"{API_SERVER_URL}/api/manage/credential",
            json=credential_request,
            headers=HEADERS,
        )
        response.raise_for_status()
        return response.json()

    except requests.exceptions.HTTPError as e:
        print(f"Error response body: {e.response.text}")
        raise


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

    try:
        response = requests.put(
            url=f"{API_SERVER_URL}/api/manage/connector/{connector_id}/credential/{credential_id}",
            json=cc_pair_request,
            headers=HEADERS,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        print(f"Error response body: {e.response.text}")
        raise


def main() -> None:
    # Parse the JSON file that contains the connector creation requests
    with open("creation_request/connector_creation_template.json", "r") as file:
        connector_creation_requests = json.load(file)

    for connector_creation_request in connector_creation_requests:
        connector_response = create_connector(
            name=connector_creation_request["name"],
            source=connector_creation_request["source"],
            input_type=connector_creation_request["input_type"],
            connector_specific_config=dict(
                connector_creation_request.get("connector_specific_config", {})
            ),
            access_type=connector_creation_request.get("access_type", "public"),
        )

        credential_id = connector_creation_request.get("credential_id")
        # If a credential id is provided, reuse credential rather than creating a new one
        if not credential_id:
            credential_response = create_credential(
                name=connector_creation_request["name"],
                source=connector_creation_request["source"],
                credential_json=connector_creation_request.get("credential_json", {}),
            )
            credential_id = credential_response.get("id")

        create_cc_pair(
            connector_id=connector_response.get("id"),
            credential_id=credential_id,
            name=connector_creation_request["name"],
            access_type=connector_creation_request.get("access_type", "public"),
        )

        print(f"Created connector: {connector_creation_request['name']}")


if __name__ == "__main__":
    main()
