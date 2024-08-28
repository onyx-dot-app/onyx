import uuid
from typing import cast

import requests
from pydantic import BaseModel

from danswer.configs.constants import DocumentSource
from danswer.db.enums import ConnectorCredentialPairStatus
from tests.integration.common_utils.constants import API_SERVER_URL


class ConnectorCreationDetails(BaseModel):
    connector_id: int
    credential_id: int
    cc_pair_id: int


class ConnectorClient:
    @staticmethod
    def create_connector(
        name_prefix: str = "test_connector", credential_id: int | None = None
    ) -> ConnectorCreationDetails:
        unique_id = uuid.uuid4()

        connector_name = f"{name_prefix}_{unique_id}"
        connector_data = {
            "name": connector_name,
            "source": DocumentSource.NOT_APPLICABLE,
            "input_type": "load_state",
            "connector_specific_config": {},
            "refresh_freq": 60,
            "disabled": True,
        }
        response = requests.post(
            f"{API_SERVER_URL}/manage/admin/connector",
            json=connector_data,
        )
        response.raise_for_status()
        connector_id = response.json()["id"]

        # associate the credential with the connector
        if not credential_id:
            print("ID not specified, creating new credential")
            # Create a new credential
            credential_data = {
                "credential_json": {},
                "admin_public": True,
                "source": DocumentSource.NOT_APPLICABLE,
            }
            response = requests.post(
                f"{API_SERVER_URL}/manage/credential",
                json=credential_data,
            )
            response.raise_for_status()
            credential_id = cast(int, response.json()["id"])

        cc_pair_metadata = {"name": f"test_cc_pair_{unique_id}", "is_public": True}
        response = requests.put(
            f"{API_SERVER_URL}/manage/connector/{connector_id}/credential/{credential_id}",
            json=cc_pair_metadata,
        )
        response.raise_for_status()

        # fetch the conenector credential pair id using the indexing status API
        response = requests.get(
            f"{API_SERVER_URL}/manage/admin/connector/indexing-status"
        )
        response.raise_for_status()
        indexing_statuses = response.json()

        cc_pair_id = None
        for status in indexing_statuses:
            if (
                status["connector"]["id"] == connector_id
                and status["credential"]["id"] == credential_id
            ):
                cc_pair_id = status["cc_pair_id"]
                break

        if cc_pair_id is None:
            raise ValueError("Could not find the connector credential pair id")

        print(
            f"Created connector with connector_id: {connector_id}, credential_id: {credential_id}, cc_pair_id: {cc_pair_id}"
        )
        return ConnectorCreationDetails(
            connector_id=int(connector_id),
            credential_id=int(credential_id),
            cc_pair_id=int(cc_pair_id),
        )

    @staticmethod
    def update_connector_status(
        cc_pair_id: int, status: ConnectorCredentialPairStatus
    ) -> None:
        response = requests.put(
            f"{API_SERVER_URL}/manage/admin/cc-pair/{cc_pair_id}/status",
            json={"status": status},
        )
        response.raise_for_status()

    @staticmethod
    def delete_connector(connector_id: int, credential_id: int) -> None:
        response = requests.post(
            f"{API_SERVER_URL}/manage/admin/deletion-attempt",
            json={"connector_id": connector_id, "credential_id": credential_id},
        )
        response.raise_for_status()

    @staticmethod
    def get_connectors() -> list[dict]:
        response = requests.get(f"{API_SERVER_URL}/manage/connector")
        response.raise_for_status()
        return response.json()
