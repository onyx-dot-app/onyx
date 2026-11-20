"""Calls of the integration API (``/integrations`` and
``/admin/integrations``) for integration tests."""

from typing import Any

import httpx

from onyx.server.features.integrations.models import (
    ActionGrantsResponse,
    AdminIntegration,
    AdminIntegrationDetail,
    AgentIntegrationOption,
    IntegrationActionsResponse,
    MemberIntegration,
    MemberIntegrationDetail,
    PresetView,
)
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

ADMIN_URL = f"{API_SERVER_URL}/admin/integrations"
MEMBER_URL = f"{API_SERVER_URL}/integrations"


class IntegrationManager:
    @staticmethod
    def create_raw(body: dict[str, Any], user: DATestUser) -> httpx.Response:
        return client.post(ADMIN_URL, json=body, headers=user.headers)

    @staticmethod
    def create(body: dict[str, Any], user: DATestUser) -> AdminIntegrationDetail:
        response = IntegrationManager.create_raw(body, user)
        response.raise_for_status()
        return AdminIntegrationDetail.model_validate(response.json())

    @staticmethod
    def list_admin(user: DATestUser) -> list[AdminIntegration]:
        response = client.get(ADMIN_URL, headers=user.headers)
        response.raise_for_status()
        return [AdminIntegration.model_validate(item) for item in response.json()]

    @staticmethod
    def presets(user: DATestUser) -> list[PresetView]:
        response = client.get(f"{ADMIN_URL}/presets", headers=user.headers)
        response.raise_for_status()
        return [PresetView.model_validate(item) for item in response.json()]

    @staticmethod
    def get_admin(integration_id: int, user: DATestUser) -> AdminIntegrationDetail:
        response = client.get(f"{ADMIN_URL}/{integration_id}", headers=user.headers)
        response.raise_for_status()
        return AdminIntegrationDetail.model_validate(response.json())

    @staticmethod
    def update_raw(
        integration_id: int, body: dict[str, Any], user: DATestUser
    ) -> httpx.Response:
        return client.patch(
            f"{ADMIN_URL}/{integration_id}", json=body, headers=user.headers
        )

    @staticmethod
    def update(
        integration_id: int, body: dict[str, Any], user: DATestUser
    ) -> AdminIntegrationDetail:
        response = IntegrationManager.update_raw(integration_id, body, user)
        response.raise_for_status()
        return AdminIntegrationDetail.model_validate(response.json())

    @staticmethod
    def delete(integration_id: int, user: DATestUser) -> httpx.Response:
        return client.delete(f"{ADMIN_URL}/{integration_id}", headers=user.headers)

    @staticmethod
    def get_actions(
        integration_id: int, user: DATestUser
    ) -> IntegrationActionsResponse:
        response = client.get(
            f"{ADMIN_URL}/{integration_id}/actions", headers=user.headers
        )
        response.raise_for_status()
        return IntegrationActionsResponse.model_validate(response.json())

    @staticmethod
    def set_actions(
        integration_id: int, body: dict[str, Any], user: DATestUser
    ) -> IntegrationActionsResponse:
        response = client.put(
            f"{ADMIN_URL}/{integration_id}/actions", json=body, headers=user.headers
        )
        response.raise_for_status()
        return IntegrationActionsResponse.model_validate(response.json())

    @staticmethod
    def refresh_actions(
        integration_id: int, user: DATestUser
    ) -> IntegrationActionsResponse:
        response = client.post(
            f"{ADMIN_URL}/{integration_id}/actions/refresh", headers=user.headers
        )
        response.raise_for_status()
        return IntegrationActionsResponse.model_validate(response.json())

    @staticmethod
    def save_organization_connection(
        integration_id: int, fields: dict[str, str], user: DATestUser
    ) -> dict[str, Any]:
        response = client.put(
            f"{ADMIN_URL}/{integration_id}/organization-connection",
            json={"fields": fields},
            headers=user.headers,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def delete_organization_connection(
        integration_id: int, user: DATestUser
    ) -> dict[str, Any]:
        response = client.delete(
            f"{ADMIN_URL}/{integration_id}/organization-connection",
            headers=user.headers,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def list_member(user: DATestUser) -> list[MemberIntegration]:
        response = client.get(MEMBER_URL, headers=user.headers)
        response.raise_for_status()
        return [MemberIntegration.model_validate(item) for item in response.json()]

    @staticmethod
    def get_member_raw(integration_id: int, user: DATestUser) -> httpx.Response:
        return client.get(f"{MEMBER_URL}/{integration_id}", headers=user.headers)

    @staticmethod
    def get_member(integration_id: int, user: DATestUser) -> MemberIntegrationDetail:
        response = IntegrationManager.get_member_raw(integration_id, user)
        response.raise_for_status()
        return MemberIntegrationDetail.model_validate(response.json())

    @staticmethod
    def connect(
        integration_id: int, fields: dict[str, str], user: DATestUser
    ) -> dict[str, Any]:
        response = client.put(
            f"{MEMBER_URL}/{integration_id}/connection",
            json={"fields": fields},
            headers=user.headers,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def disconnect(integration_id: int, user: DATestUser) -> dict[str, Any]:
        response = client.delete(
            f"{MEMBER_URL}/{integration_id}/connection", headers=user.headers
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def get_grants(integration_id: int, user: DATestUser) -> ActionGrantsResponse:
        response = client.get(
            f"{API_SERVER_URL}/action-policies/integration/{integration_id}",
            headers=user.headers,
        )
        response.raise_for_status()
        return ActionGrantsResponse.model_validate(response.json())

    @staticmethod
    def set_grants_raw(
        integration_id: int, actions: dict[str, str | None], user: DATestUser
    ) -> httpx.Response:
        return client.put(
            f"{API_SERVER_URL}/action-policies/integration/{integration_id}",
            json={"actions": actions},
            headers=user.headers,
        )

    @staticmethod
    def agent_catalog(user: DATestUser) -> list[AgentIntegrationOption]:
        response = client.get(f"{MEMBER_URL}/agent-catalog", headers=user.headers)
        response.raise_for_status()
        return [AgentIntegrationOption.model_validate(item) for item in response.json()]
