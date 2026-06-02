import io
import json
import zipfile
from typing import Any
from uuid import uuid4

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.server.features.build.api.models import ExternalAppAdminResponse
from onyx.server.features.build.api.models import ExternalAppUserResponse
from onyx.server.features.build.api.models import UpsertExternalAppRequest
from onyx.server.features.build.api.models import UpsertUserCredentialsRequest
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

_BUILD_PREFIX = f"{API_SERVER_URL}/build"


def _minimal_bundle_zip() -> bytes:
    """A valid skill bundle (SKILL.md + helper file) for creating bundle-backed
    custom apps through the admin endpoint."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "SKILL.md",
            "---\nname: Bundle Name\ndescription: Bundle description\n---\n\nDo things.\n",
        )
        zf.writestr("helper.py", "print('hello')\n")
    return buf.getvalue()


class ExternalAppManager:
    """HTTP wrapper around the External Apps router.

    Returns the route's own Pydantic response models so tests get
    attribute access (`app.credential_keys`) instead of dict lookups.
    """

    @staticmethod
    def create(
        user_performing_action: DATestUser,
        name: str,
        description: str,
        upstream_url_patterns: list[str],
        auth_template: dict[str, Any],
        organization_credentials: dict[str, Any],
        enabled: bool = True,
        app_type: ExternalAppType = ExternalAppType.CUSTOM,
        action_policies: dict[str, EndpointPolicy] | None = None,
    ) -> ExternalAppAdminResponse:
        return ExternalAppManager._upsert(
            user_performing_action,
            None,
            name,
            description,
            app_type,
            upstream_url_patterns,
            auth_template,
            organization_credentials,
            enabled,
            action_policies,
        )

    @staticmethod
    def update(
        user_performing_action: DATestUser,
        app_id: int,
        name: str,
        description: str,
        upstream_url_patterns: list[str],
        auth_template: dict[str, Any],
        organization_credentials: dict[str, Any],
        enabled: bool = True,
        app_type: ExternalAppType = ExternalAppType.CUSTOM,
        action_policies: dict[str, EndpointPolicy] | None = None,
    ) -> ExternalAppAdminResponse:
        return ExternalAppManager._upsert(
            user_performing_action,
            app_id,
            name,
            description,
            app_type,
            upstream_url_patterns,
            auth_template,
            organization_credentials,
            enabled,
            action_policies,
        )

    @staticmethod
    def _upsert(
        user_performing_action: DATestUser,
        app_id: int | None,
        name: str,
        description: str,
        app_type: ExternalAppType,
        upstream_url_patterns: list[str],
        auth_template: dict[str, Any],
        organization_credentials: dict[str, Any],
        enabled: bool,
        action_policies: dict[str, EndpointPolicy] | None = None,
    ) -> ExternalAppAdminResponse:
        # Custom (bundle-backed) apps go through the multipart endpoint so a
        # bundle can be uploaded; built-in providers use the JSON endpoint.
        if app_type == ExternalAppType.CUSTOM:
            response = ExternalAppManager._upsert_custom(
                user_performing_action,
                app_id,
                name,
                description,
                upstream_url_patterns,
                auth_template,
                organization_credentials,
                enabled,
            )
        else:
            body = UpsertExternalAppRequest(
                id=app_id,
                name=name,
                description=description,
                app_type=app_type,
                upstream_url_patterns=upstream_url_patterns,
                auth_template=auth_template,
                organization_credentials=organization_credentials,
                enabled=enabled,
                action_policies=action_policies,
            )
            response = client.post(
                f"{_BUILD_PREFIX}/admin/apps",
                json=body.model_dump(mode="json"),
                headers=user_performing_action.headers,
                cookies=user_performing_action.cookies,
            )
        response.raise_for_status()
        return ExternalAppAdminResponse.model_validate(response.json())

    @staticmethod
    def _upsert_custom(
        user_performing_action: DATestUser,
        app_id: int | None,
        name: str,
        description: str,
        upstream_url_patterns: list[str],
        auth_template: dict[str, Any],
        organization_credentials: dict[str, Any],
        enabled: bool,
    ) -> Any:
        """POST the multipart custom-app endpoint. A bundle is required on create
        (``app_id`` omitted) and omitted on edit."""
        data: dict[str, str] = {
            "name": name,
            "description": description,
            "upstream_url_patterns": json.dumps(upstream_url_patterns),
            "auth_template": json.dumps(auth_template),
            "organization_credentials": json.dumps(organization_credentials),
            "enabled": str(enabled).lower(),
        }
        files: dict[str, tuple[str, bytes, str]] | None = None
        if app_id is not None:
            data["app_id"] = str(app_id)
        else:
            # Unique filename → unique slug, so repeated creates within one test
            # don't collide on the bundle-derived skill slug.
            files = {
                "bundle": (
                    f"custom-{uuid4().hex[:8]}.zip",
                    _minimal_bundle_zip(),
                    "application/zip",
                )
            }
        # Drop the default JSON Content-Type so httpx can set the multipart
        # boundary itself; leaving "application/json" in place makes the server
        # try to JSON-parse the form body and report every field as missing.
        headers = user_performing_action.headers.copy()
        headers.pop("Content-Type", None)
        return client.post(
            f"{_BUILD_PREFIX}/admin/apps/custom",
            data=data,
            files=files,
            headers=headers,
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
