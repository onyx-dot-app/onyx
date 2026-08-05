from typing import Any

from onyx.db.enums import EndpointPolicy, ExternalAppType
from onyx.server.features.build.external_apps.models import (
    CreateBuiltInExternalAppRequest,
    CreateCustomExternalAppRequest,
    ExternalAppAdminResponse,
    ExternalAppUserResponse,
    UpdateExternalAppRequest,
    UpsertUserCredentialsRequest,
)
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

_BUILD_PREFIX = f"{API_SERVER_URL}/build"


class ExternalAppManager:
    """HTTP wrapper around the External Apps router.

    Returns the route's own Pydantic response models so tests get
    attribute access (`app.credential_keys`) instead of dict lookups.
    """

    @staticmethod
    def create(
        user_performing_action: DATestUser,
        name: str,
        upstream_url_patterns: list[str],
        auth_template: dict[str, Any],
        organization_credentials: dict[str, Any],
        app_type: ExternalAppType = ExternalAppType.CUSTOM,
        action_policies: dict[str, EndpointPolicy] | None = None,
    ) -> ExternalAppAdminResponse:
        return ExternalAppManager._upsert(
            user_performing_action,
            None,
            name,
            app_type,
            upstream_url_patterns,
            auth_template,
            organization_credentials,
            action_policies,
        )

    @staticmethod
    def update(
        user_performing_action: DATestUser,
        app_id: int,
        name: str,
        upstream_url_patterns: list[str],
        auth_template: dict[str, Any],
        organization_credentials: dict[str, Any],
        app_type: ExternalAppType = ExternalAppType.CUSTOM,
        action_policies: dict[str, EndpointPolicy] | None = None,
    ) -> ExternalAppAdminResponse:
        return ExternalAppManager._upsert(
            user_performing_action,
            app_id,
            name,
            app_type,
            upstream_url_patterns,
            auth_template,
            organization_credentials,
            action_policies,
        )

    @staticmethod
    def _upsert(
        user_performing_action: DATestUser,
        app_id: int | None,
        name: str,
        app_type: ExternalAppType,
        upstream_url_patterns: list[str],
        auth_template: dict[str, Any],
        organization_credentials: dict[str, Any],
        action_policies: dict[str, EndpointPolicy] | None = None,
    ) -> ExternalAppAdminResponse:
        # Update (``app_id`` set) is type-agnostic — the JSON PATCH edits fields
        # for built-in and custom apps alike. Create routes by app type.
        if app_id is not None:
            update_body = UpdateExternalAppRequest(
                name=name,
                upstream_url_patterns=upstream_url_patterns,
                auth_template=auth_template,
                organization_credentials=organization_credentials,
                action_policies=action_policies,
            )
            response = client.patch(
                f"{_BUILD_PREFIX}/admin/apps/{app_id}",
                json=update_body.model_dump(mode="json"),
                headers=user_performing_action.headers,
                cookies=user_performing_action.cookies,
            )
        elif app_type == ExternalAppType.CUSTOM:
            response = ExternalAppManager._create_custom(
                user_performing_action,
                name,
                upstream_url_patterns,
                auth_template,
                organization_credentials,
            )
        else:
            create_body = CreateBuiltInExternalAppRequest(
                name=name,
                app_type=app_type,
                upstream_url_patterns=upstream_url_patterns,
                auth_template=auth_template,
                organization_credentials=organization_credentials,
                action_policies=action_policies,
            )
            response = client.post(
                f"{_BUILD_PREFIX}/admin/apps/built-in",
                json=create_body.model_dump(mode="json"),
                headers=user_performing_action.headers,
                cookies=user_performing_action.cookies,
            )
        response.raise_for_status()
        return ExternalAppAdminResponse.model_validate(response.json())

    @staticmethod
    def _create_custom(
        user_performing_action: DATestUser,
        name: str,
        upstream_url_patterns: list[str],
        auth_template: dict[str, Any],
        organization_credentials: dict[str, Any],
    ) -> Any:
        body = CreateCustomExternalAppRequest(
            name=name,
            upstream_url_patterns=upstream_url_patterns,
            auth_template=auth_template,
            organization_credentials=organization_credentials,
        )
        return client.post(
            f"{_BUILD_PREFIX}/admin/apps/custom",
            json=body.model_dump(mode="json"),
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        )

    @staticmethod
    def list_admin(
        user_performing_action: DATestUser,
    ) -> list[ExternalAppAdminResponse]:
        response = client.get(
            f"{_BUILD_PREFIX}/admin/apps",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        )
        response.raise_for_status()
        return [ExternalAppAdminResponse.model_validate(row) for row in response.json()]

    @staticmethod
    def set_enabled(
        user_performing_action: DATestUser,
        app_id: int,
        enabled: bool,
    ) -> ExternalAppAdminResponse:
        response = client.patch(
            f"{_BUILD_PREFIX}/admin/apps/{app_id}",
            json={"enabled": enabled},
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        )
        response.raise_for_status()
        return ExternalAppAdminResponse.model_validate(response.json())

    @staticmethod
    def delete(user_performing_action: DATestUser, app_id: int) -> None:
        response = client.delete(
            f"{_BUILD_PREFIX}/admin/apps/{app_id}",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        )
        response.raise_for_status()

    @staticmethod
    def list_for_user(
        user_performing_action: DATestUser,
    ) -> list[ExternalAppUserResponse]:
        response = client.get(
            f"{_BUILD_PREFIX}/apps",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        )
        response.raise_for_status()
        return [ExternalAppUserResponse.model_validate(row) for row in response.json()]

    @staticmethod
    def get_for_user(
        user_performing_action: DATestUser, app_id: int
    ) -> ExternalAppUserResponse:
        """Convenience: list and find by id. Raises KeyError if not visible."""
        for app in ExternalAppManager.list_for_user(user_performing_action):
            if app.id == app_id:
                return app
        raise KeyError(
            f"App {app_id} not visible to user {user_performing_action.email}"
        )

    @staticmethod
    def upsert_user_credentials(
        user_performing_action: DATestUser,
        app_id: int,
        credentials: dict[str, Any],
    ) -> None:
        body = UpsertUserCredentialsRequest(user_credentials=credentials)
        response = client.post(
            f"{_BUILD_PREFIX}/apps/{app_id}/credentials",
            json=body.model_dump(mode="json"),
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        )
        response.raise_for_status()
