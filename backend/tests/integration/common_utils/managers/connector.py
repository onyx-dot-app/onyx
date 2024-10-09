from typing import Any
from uuid import uuid4

import requests

from danswer.connectors.models import InputType
from danswer.server.documents.models import ConnectorUpdateRequest
from danswer.server.documents.models import DocumentSource
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestConnector
from tests.integration.common_utils.test_models import DATestUser


class ConnectorManager:
    @staticmethod
    def create(
        name: str | None = None,
        source: DocumentSource = DocumentSource.FILE,
        input_type: InputType = InputType.LOAD_STATE,
        connector_specific_config: dict[str, Any] | None = None,
        is_public: bool = True,
        groups: list[int] | None = None,
        user_performing_action: DATestUser | None = None,
    ) -> DATestConnector:
        name = f"{name}-connector" if name else f"test-connector-{uuid4()}"

        connector_update_request = ConnectorUpdateRequest(
            name=name,
            source=source,
            input_type=input_type,
            connector_specific_config=connector_specific_config or {},
            is_public=is_public,
            groups=groups or [],
        )

        response = requests.post(
            url=f"{API_SERVER_URL}/manage/admin/connector",
            json=connector_update_request.model_dump(),
            headers=user_performing_action.headers
            if user_performing_action
            else GENERAL_HEADERS,
        )
        response.raise_for_status()

        response_data = response.json()
        return DATestConnector(
            id=response_data.get("id"),
            name=name,
            source=source,
            input_type=input_type,
            connector_specific_config=connector_specific_config or {},
            groups=groups,
            is_public=is_public,
        )

    @staticmethod
    def edit(
        connector: DATestConnector,
        user_performing_action: DATestUser | None = None,
    ) -> None:
        response = requests.patch(
            url=f"{API_SERVER_URL}/manage/admin/connector/{connector.id}",
            json=connector.model_dump(exclude={"id"}),
            headers=user_performing_action.headers
            if user_performing_action
            else GENERAL_HEADERS,
        )
        response.raise_for_status()

    @staticmethod
    def delete(
        connector: DATestConnector,
        user_performing_action: DATestUser | None = None,
    ) -> None:
        response = requests.delete(
            url=f"{API_SERVER_URL}/manage/admin/connector/{connector.id}",
            headers=user_performing_action.headers
            if user_performing_action
            else GENERAL_HEADERS,
        )
        response.raise_for_status()

    @staticmethod
    def get_all(
        user_performing_action: DATestUser | None = None,
    ) -> list[DATestConnector]:
        response = requests.get(
            url=f"{API_SERVER_URL}/manage/connector",
            headers=user_performing_action.headers
            if user_performing_action
            else GENERAL_HEADERS,
        )
        response.raise_for_status()
        return [
            DATestConnector(
                id=conn.get("id"),
                name=conn.get("name", ""),
                source=conn.get("source", DocumentSource.FILE),
                input_type=conn.get("input_type", InputType.LOAD_STATE),
                connector_specific_config=conn.get("connector_specific_config", {}),
            )
            for conn in response.json()
        ]

    @staticmethod
    def get(
        connector_id: int, user_performing_action: DATestUser | None = None
    ) -> DATestConnector:
        response = requests.get(
            url=f"{API_SERVER_URL}/manage/connector/{connector_id}",
            headers=user_performing_action.headers
            if user_performing_action
            else GENERAL_HEADERS,
        )
        response.raise_for_status()
        conn = response.json()
        return DATestConnector(
            id=conn.get("id"),
            name=conn.get("name", ""),
            source=conn.get("source", DocumentSource.FILE),
            input_type=conn.get("input_type", InputType.LOAD_STATE),
            connector_specific_config=conn.get("connector_specific_config", {}),
        )
