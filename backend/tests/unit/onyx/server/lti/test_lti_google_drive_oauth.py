import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import UUID

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.google_utils import google_kv
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.lti import api


USER_ID = UUID("12345678-1234-1234-1234-123456789abc")


def test_google_auth_url_uses_lti_state_without_overwriting_admin_state() -> None:
    kv_store = MagicMock()
    kv_store.load.return_value = "{}"
    flow = MagicMock()
    flow.authorization_url.return_value = (
        "https://accounts.google.com/consent?state=lti_google_drive_random-state",
        "lti_google_drive_random-state",
    )
    with (
        patch.object(google_kv, "get_kv_store", return_value=kv_store),
        patch.object(
            google_kv.InstalledAppFlow, "from_client_config", return_value=flow
        ),
    ):
        url = google_kv.get_auth_url(
            18,
            DocumentSource.GOOGLE_DRIVE,
            state="lti_google_drive_random-state",
        )

    assert "state=lti_google_drive_random-state" in url
    flow.authorization_url.assert_called_once_with(
        prompt="consent", state="lti_google_drive_random-state"
    )
    kv_store.store.assert_not_called()


def test_regular_google_auth_url_still_stores_csrf_state() -> None:
    kv_store = MagicMock()
    kv_store.load.return_value = "{}"
    flow = MagicMock()
    flow.authorization_url.return_value = (
        "https://accounts.google.com/consent?state=admin-state",
        "admin-state",
    )
    with (
        patch.object(google_kv, "get_kv_store", return_value=kv_store),
        patch.object(
            google_kv.InstalledAppFlow, "from_client_config", return_value=flow
        ),
    ):
        google_kv.get_auth_url(18, DocumentSource.GOOGLE_DRIVE)

    flow.authorization_url.assert_called_once_with(prompt="consent")
    assert kv_store.store.call_args.args[1] == {"value": "admin-state"}


def test_google_drive_connect_returns_consent_url_without_popup_session() -> None:
    user = SimpleNamespace(id=USER_ID)
    credential = SimpleNamespace(id=18)
    redis = MagicMock()
    with (
        patch.object(api, "_get_launch_context_for_course_or_raise") as launch,
        patch.object(api, "lti_roles_include_instructor", return_value=True),
        patch.object(api, "_google_drive_oauth_app_is_configured", return_value=True),
        patch.object(
            api, "_get_or_create_lti_google_drive_credential", return_value=credential
        ),
        patch.object(
            api, "get_auth_url", return_value="https://accounts.google.com/consent"
        ) as get_url,
        patch.object(api, "get_raw_redis_client", return_value=redis),
        patch.object(api, "get_current_tenant_id", return_value="tenant-1"),
        patch.object(api.secrets, "token_urlsafe", return_value="random-state"),
    ):
        launch.return_value.roles = ["Instructor"]
        result = api.connect_lti_course_google_drive(
            course_id="course-1", user=user, db_session=MagicMock()  # type: ignore[arg-type]
        )

    assert result.auth_url == "https://accounts.google.com/consent"
    get_url.assert_called_once_with(
        credential.id,
        DocumentSource.GOOGLE_DRIVE,
        state="lti_google_drive_random-state",
    )
    stored = json.loads(redis.set.call_args.args[1])
    assert stored == {
        "user_id": str(USER_ID),
        "course_id": "course-1",
        "credential_id": 18,
        "tenant_id": "tenant-1",
    }
    assert redis.set.call_args.kwargs["ex"] == 600


def test_google_drive_callback_consumes_state_and_checks_credential_owner() -> None:
    state = "lti_google_drive_random-state"
    redis = MagicMock()
    redis.getdel.side_effect = [
        json.dumps(
            {
                "user_id": str(USER_ID),
                "course_id": "course-1",
                "credential_id": 18,
                "tenant_id": "tenant-1",
            }
        ),
        None,
    ]
    user = SimpleNamespace(id=USER_ID, is_active=True)
    credential = SimpleNamespace(
        id=18, user_id=USER_ID, source=DocumentSource.GOOGLE_DRIVE
    )
    db_session = MagicMock()
    with (
        patch.object(api, "get_raw_redis_client", return_value=redis),
        patch.object(
            api, "get_session_with_tenant", return_value=nullcontext(db_session)
        ),
        patch.object(api, "fetch_user_by_id", return_value=user),
        patch.object(api, "fetch_credential_by_id", return_value=credential),
        patch.object(
            api, "update_credential_access_tokens", return_value=MagicMock()
        ) as update,
    ):
        result = api.lti_google_drive_oauth_callback(
            api.LtiGoogleDriveCallbackRequest(code="google-code", state=state)
        )
        with pytest.raises(OnyxError) as exc_info:
            api.lti_google_drive_oauth_callback(
                api.LtiGoogleDriveCallbackRequest(code="google-code", state=state)
            )

    assert result.success is True
    assert update.call_count == 1
    assert update.call_args.args[:3] == ("google-code", 18, user)
    assert exc_info.value.error_code == OnyxErrorCode.UNAUTHENTICATED


def test_google_drive_callback_rejects_reassigned_credential() -> None:
    state = "lti_google_drive_random-state"
    redis = MagicMock()
    redis.getdel.return_value = json.dumps(
        {
            "user_id": str(USER_ID),
            "course_id": "course-1",
            "credential_id": 18,
            "tenant_id": "tenant-1",
        }
    )
    credential = SimpleNamespace(
        id=18,
        user_id=UUID("99999999-9999-9999-9999-999999999999"),
        source=DocumentSource.GOOGLE_DRIVE,
    )
    with (
        patch.object(api, "get_raw_redis_client", return_value=redis),
        patch.object(
            api, "get_session_with_tenant", return_value=nullcontext(MagicMock())
        ),
        patch.object(
            api,
            "fetch_user_by_id",
            return_value=SimpleNamespace(id=USER_ID, is_active=True),
        ),
        patch.object(api, "fetch_credential_by_id", return_value=credential),
        patch.object(api, "update_credential_access_tokens") as update,
    ):
        with pytest.raises(OnyxError) as exc_info:
            api.lti_google_drive_oauth_callback(
                api.LtiGoogleDriveCallbackRequest(code="google-code", state=state)
            )

    assert exc_info.value.error_code == OnyxErrorCode.UNAUTHENTICATED
    update.assert_not_called()
