import json
import re
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.canvas import oauth
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.lti import api
from onyx.server.lti.utils import LtiLaunchContext


def test_canvas_base_url_from_lti_claims_uses_launch_return_url() -> None:
    claims = {
        "https://purl.imsglobal.org/spec/lti/claim/launch_presentation": {
            "return_url": "https://school.instructure.com/courses/123/external_content/success"
        }
    }

    assert api._canvas_base_url_from_lti_claims(claims) == (
        "https://school.instructure.com"
    )


def test_canvas_course_id_from_lti_claims_uses_launch_return_url() -> None:
    claims = {
        "https://purl.imsglobal.org/spec/lti/claim/launch_presentation": {
            "return_url": "https://school.instructure.com/courses/123/external_content/success"
        }
    }

    assert api._canvas_course_id_from_lti_claims(claims) == 123


def test_normalize_google_drive_folder_selections_accepts_urls_and_ids() -> None:
    folders = api._normalize_google_drive_folder_selections(
        [
            api.LtiGoogleDriveFolderSelection(
                url="https://drive.google.com/drive/folders/folder_123"
            ),
            api.LtiGoogleDriveFolderSelection(id="folder_456"),
            api.LtiGoogleDriveFolderSelection(id="folder_123"),
        ]
    )

    assert [(folder.id, folder.url) for folder in folders] == [
        ("folder_123", "https://drive.google.com/drive/folders/folder_123"),
        ("folder_456", "https://drive.google.com/drive/folders/folder_456"),
    ]


def test_normalize_google_drive_folder_selections_rejects_empty_input() -> None:
    with pytest.raises(OnyxError) as exc_info:
        api._normalize_google_drive_folder_selections([])

    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT


@patch("onyx.server.lti.api.get_google_app_cred")
def test_google_drive_oauth_app_configured_when_admin_credentials_exist(
    mock_get_google_app_cred: MagicMock,
) -> None:
    mock_get_google_app_cred.return_value = MagicMock()

    assert api._google_drive_oauth_app_is_configured() is True


@patch("onyx.server.lti.api.get_google_app_cred")
def test_google_drive_oauth_app_not_configured_when_admin_credentials_missing(
    mock_get_google_app_cred: MagicMock,
) -> None:
    mock_get_google_app_cred.side_effect = KvKeyNotFoundError()

    assert api._google_drive_oauth_app_is_configured() is False


def test_canvas_base_url_for_launch_context_uses_local_lti_endpoint_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api, "LTI_CANVAS_BASE_URL", None)
    monkeypatch.setattr(
        api, "LTI_AUTH_TOKEN_URL", "http://canvas.docker/login/oauth2/token"
    )
    monkeypatch.setattr(
        api,
        "LTI_JWKS_URL",
        "http://canvas.docker/api/lti/security/jwks",
    )
    monkeypatch.setattr(
        api,
        "LTI_AUTH_LOGIN_URL",
        "http://canvas.docker/api/lti/authorize_redirect",
    )
    launch_context = LtiLaunchContext(
        course_id="opaque-lti-context",
        roles=[],
        issuer="https://canvas.instructure.com",
    )

    assert api._canvas_base_url_for_launch_context(launch_context) == (
        "http://canvas.docker"
    )


def test_canvas_base_url_for_launch_context_prefers_explicit_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api, "LTI_CANVAS_BASE_URL", "http://canvas.docker")
    launch_context = LtiLaunchContext(
        course_id="opaque-lti-context",
        roles=[],
        issuer="https://canvas.instructure.com",
    )

    assert api._canvas_base_url_for_launch_context(launch_context) == (
        "http://canvas.docker"
    )


def test_resolve_canvas_api_course_uses_canvas_course_id() -> None:
    canvas_client = MagicMock()
    canvas_client.get.return_value = (
        {"id": 123, "name": "Intro Biology", "course_code": "BIO101"},
        None,
    )
    launch_context = LtiLaunchContext(
        course_id="opaque-lti-context",
        roles=[],
        canvas_course_id=123,
    )

    course = api._resolve_canvas_api_course(canvas_client, launch_context)

    assert course.id == 123
    canvas_client.get.assert_called_once_with("courses/123")
    canvas_client.paginate.assert_not_called()


def test_resolve_canvas_api_course_rejects_inaccessible_canvas_course_id() -> None:
    canvas_client = MagicMock()
    canvas_client.get.side_effect = OnyxError(
        OnyxErrorCode.BAD_GATEWAY,
        "Not found",
        status_code_override=404,
    )
    launch_context = LtiLaunchContext(
        course_id="opaque-lti-context",
        roles=[],
        canvas_course_id=123,
    )

    with pytest.raises(OnyxError) as exc_info:
        api._resolve_canvas_api_course(canvas_client, launch_context)

    assert exc_info.value.error_code == OnyxErrorCode.CREDENTIAL_INVALID


@patch("onyx.server.lti.api.fetch_canvas_course_node_id_for_cc_pair")
@patch("onyx.server.lti.api.get_document_counts_for_cc_pairs")
@patch("onyx.server.lti.api.get_latest_index_attempt_for_cc_pair_id")
@patch("onyx.server.lti.api.fetch_canvas_cc_pair_for_lti_course")
def test_lti_course_connector_status_uses_indexed_document_relationship(
    mock_fetch_cc_pair: MagicMock,
    mock_latest_attempt: MagicMock,
    mock_document_counts: MagicMock,
    mock_course_node_id: MagicMock,
) -> None:
    mock_course_node_id.return_value = 58
    mock_fetch_cc_pair.return_value = SimpleNamespace(
        id=10,
        connector_id=20,
        credential_id=30,
        status="ACTIVE",
        indexing_trigger=None,
        total_docs_indexed=0,
        last_successful_index_time=None,
    )
    mock_latest_attempt.return_value = SimpleNamespace(
        status="success",
        total_docs_indexed=0,
    )
    mock_document_counts.return_value = [(20, 30, 1)]
    launch_context = LtiLaunchContext(
        course_id="opaque-lti-context",
        roles=[],
    )

    status = api._build_lti_course_connector_status(
        course_id="opaque-lti-context",
        launch_context=launch_context,
        db_session=MagicMock(),
    )

    assert status["has_connector"] is True
    assert status["has_indexed_documents"] is True
    assert status["total_docs_indexed"] == 1
    assert status["canvas_course_node_id"] == 58


@patch("onyx.server.lti.api.fetch_canvas_cc_pair_for_lti_course")
def test_lti_course_connector_status_without_connector_has_no_course_node(
    mock_fetch_cc_pair: MagicMock,
) -> None:
    mock_fetch_cc_pair.return_value = None

    status = api._build_lti_course_connector_status(
        course_id="opaque-lti-context",
        launch_context=LtiLaunchContext(course_id="opaque-lti-context", roles=[]),
        db_session=MagicMock(),
    )

    assert status["has_connector"] is False
    assert status["canvas_course_node_id"] is None


def _cc_pair_with_course_ids(course_ids: Any) -> Any:
    return SimpleNamespace(
        connector=SimpleNamespace(connector_specific_config={"course_ids": course_ids})
    )


@patch("onyx.db.lti.get_hierarchy_node_by_raw_id")
def test_fetch_canvas_course_node_id_matches_course_raw_id(
    mock_get_node: MagicMock,
) -> None:
    from onyx.db.enums import HierarchyNodeType
    from onyx.db.lti import fetch_canvas_course_node_id_for_cc_pair

    mock_get_node.return_value = SimpleNamespace(
        id=58, node_type=HierarchyNodeType.COURSE
    )
    db_session = MagicMock()

    node_id = fetch_canvas_course_node_id_for_cc_pair(
        db_session=db_session, cc_pair=_cc_pair_with_course_ids([1])
    )

    assert node_id == 58
    mock_get_node.assert_called_once_with(
        db_session=db_session,
        raw_node_id="canvas-course-1",
        source=DocumentSource.CANVAS,
    )


@patch("onyx.db.lti.get_hierarchy_node_by_raw_id")
def test_fetch_canvas_course_node_id_none_until_indexed(
    mock_get_node: MagicMock,
) -> None:
    from onyx.db.lti import fetch_canvas_course_node_id_for_cc_pair

    mock_get_node.return_value = None

    assert (
        fetch_canvas_course_node_id_for_cc_pair(
            db_session=MagicMock(), cc_pair=_cc_pair_with_course_ids([1])
        )
        is None
    )


@patch("onyx.db.lti.get_hierarchy_node_by_raw_id")
def test_fetch_canvas_course_node_id_requires_single_course(
    mock_get_node: MagicMock,
) -> None:
    from onyx.db.lti import fetch_canvas_course_node_id_for_cc_pair

    for course_ids in ([], [1, 2], None):
        assert (
            fetch_canvas_course_node_id_for_cc_pair(
                db_session=MagicMock(),
                cc_pair=_cc_pair_with_course_ids(course_ids),
            )
            is None
        )
    mock_get_node.assert_not_called()


# ---------------------------------------------------------------------------
# Canvas OAuth (instructor self-serve)
# ---------------------------------------------------------------------------

_INSTRUCTOR_ROLE = "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"


def _fake_user() -> Any:
    return SimpleNamespace(id=uuid.uuid4())


def _fake_cc_pair(**attrs: Any) -> Any:
    return SimpleNamespace(**attrs)


def _fake_credential(
    credential_json: dict[str, Any],
    *,
    user_id: uuid.UUID | None = None,
    credential_id: int = 30,
    source: DocumentSource = DocumentSource.CANVAS,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=credential_id,
        user_id=user_id or uuid.uuid4(),
        source=source,
        name=api._LTI_CANVAS_OAUTH_CREDENTIAL_NAME,
        credential_json=SimpleNamespace(
            get_value=lambda **_kwargs: dict(credential_json)
        ),
    )


def _oauth_json(**overrides: Any) -> dict[str, Any]:
    credential_json: dict[str, Any] = {
        oauth.CANVAS_ACCESS_TOKEN_KEY: "access-1",
        oauth.CANVAS_REFRESH_TOKEN_KEY: "refresh-1",
        oauth.CANVAS_TOKEN_EXPIRES_AT_KEY: 9_999_999_999,
        oauth.CANVAS_BASE_URL_KEY: "https://school.instructure.com",
        oauth.CANVAS_USER_NAME_KEY: "Ada Instructor",
    }
    credential_json.update(overrides)
    return credential_json


def test_setup_request_requires_token_or_credential() -> None:
    with pytest.raises(ValueError):
        api.LtiCanvasConnectorSetupRequest()

    assert api.LtiCanvasConnectorSetupRequest(credential_id=5).credential_id == 5
    assert (
        api.LtiCanvasConnectorSetupRequest(
            canvas_access_token="tok"
        ).canvas_access_token
        == "tok"
    )


@patch("onyx.server.lti.api.get_raw_redis_client")
def test_canvas_oauth_state_round_trips_and_is_single_use(
    mock_get_redis: MagicMock,
) -> None:
    store: dict[str, str] = {}
    redis_client = MagicMock()
    redis_client.set.side_effect = lambda key, value, **_kwargs: store.__setitem__(
        key, value
    )
    redis_client.getdel.side_effect = lambda key: (
        store.pop(key).encode("utf-8") if key in store else None
    )
    mock_get_redis.return_value = redis_client

    oauth_state = api.LtiCanvasOAuthState(
        user_id=str(uuid.uuid4()),
        course_id="ctx-1",
        credential_id=30,
        canvas_base_url="https://school.instructure.com",
        tenant_id="public",
    )
    state_token = api._store_canvas_oauth_state(oauth_state)

    assert redis_client.set.call_args.kwargs["ex"] == (
        api.LTI_CANVAS_OAUTH_STATE_TTL_SECONDS
    )
    assert api._consume_canvas_oauth_state(state_token) == oauth_state
    # Replaying the same state must fail.
    assert api._consume_canvas_oauth_state(state_token) is None


def test_canvas_oauth_popup_response_posts_message_and_escapes_html() -> None:
    response = api._canvas_oauth_popup_response(
        "failed", detail="<script>alert(1)</script> nope"
    )
    body = bytes(response.body).decode("utf-8")

    match = re.search(r"var message = (\{.*?\});", body)
    assert match is not None
    message = json.loads(match.group(1))
    assert message == {
        "type": "onyx:lti-canvas-oauth",
        "status": "failed",
        "credential_id": None,
        "detail": "<script>alert(1)</script> nope",
    }
    # Raw `<script>` from Canvas-supplied text must never reach the page.
    assert "<script>alert" not in body
    assert "window.opener.postMessage(message, targetOrigin)" in body


def test_canvas_oauth_popup_response_success_carries_credential_id() -> None:
    body = bytes(
        api._canvas_oauth_popup_response("success", credential_id=42).body
    ).decode("utf-8")
    match = re.search(r"var message = (\{.*?\});", body)
    assert match is not None
    assert json.loads(match.group(1))["credential_id"] == 42


def test_canvas_connection_state_reports_connected_expired_and_static() -> None:
    connected = _fake_cc_pair(
        status=ConnectorCredentialPairStatus.ACTIVE,
        credential=_fake_credential(_oauth_json()),
    )
    assert api._canvas_connection_state(connected) == ("connected", "Ada Instructor")

    revoked = _fake_cc_pair(
        status=ConnectorCredentialPairStatus.ACTIVE,
        credential=_fake_credential(
            _oauth_json(**{oauth.CANVAS_TOKEN_INVALID_AT_KEY: 123})
        ),
    )
    assert api._canvas_connection_state(revoked) == ("expired", "Ada Instructor")

    invalid_cc_pair = _fake_cc_pair(
        status=ConnectorCredentialPairStatus.INVALID,
        credential=_fake_credential(_oauth_json()),
    )
    assert api._canvas_connection_state(invalid_cc_pair)[0] == "expired"

    static = _fake_cc_pair(
        status=ConnectorCredentialPairStatus.ACTIVE,
        credential=_fake_credential({oauth.CANVAS_ACCESS_TOKEN_KEY: "pasted"}),
    )
    assert api._canvas_connection_state(static) == ("static_token", None)


@patch("onyx.server.lti.api.lti_canvas_oauth_is_configured", return_value=True)
@patch("onyx.server.lti.api.fetch_canvas_cc_pair_for_lti_course", return_value=None)
def test_connector_status_setup_block_reports_oauth_availability(
    _mock_fetch_cc_pair: MagicMock,
    _mock_configured: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api, "LTI_CANVAS_BASE_URL", "https://school.instructure.com")
    launch_context = LtiLaunchContext(course_id="ctx-1", roles=[_INSTRUCTOR_ROLE])

    status = api._build_lti_course_connector_status(
        course_id="ctx-1",
        launch_context=launch_context,
        db_session=MagicMock(),
    )

    setup = status["setup"]
    assert isinstance(setup, dict)
    assert setup["can_setup"] is True
    assert setup["oauth_available"] is True
    assert setup["connection_state"] is None
    assert setup["connected_canvas_user"] is None


@patch("onyx.server.lti.api.fetch_credential_by_id")
def test_require_connected_credential_rejects_other_users_credential(
    mock_fetch_credential: MagicMock,
) -> None:
    mock_fetch_credential.return_value = _fake_credential(_oauth_json())
    user = _fake_user()

    with pytest.raises(OnyxError) as exc_info:
        api._require_connected_canvas_oauth_credential(
            db_session=MagicMock(), user=user, credential_id=30
        )

    assert exc_info.value.error_code == OnyxErrorCode.CREDENTIAL_NOT_FOUND


@patch("onyx.server.lti.api.fetch_credential_by_id")
def test_require_connected_credential_rejects_unauthorized_credential(
    mock_fetch_credential: MagicMock,
) -> None:
    user = _fake_user()
    # Credential row exists (created when the popup opened) but Canvas never
    # called back, so there is no refresh token yet.
    mock_fetch_credential.return_value = _fake_credential(
        {oauth.CANVAS_BASE_URL_KEY: "https://school.instructure.com"},
        user_id=user.id,
    )

    with pytest.raises(OnyxError) as exc_info:
        api._require_connected_canvas_oauth_credential(
            db_session=MagicMock(), user=user, credential_id=30
        )

    assert exc_info.value.error_code == OnyxErrorCode.CREDENTIAL_INVALID


@patch("onyx.server.lti.api.fetch_credential_by_id")
def test_require_connected_credential_accepts_owner(
    mock_fetch_credential: MagicMock,
) -> None:
    user = _fake_user()
    credential = _fake_credential(_oauth_json(), user_id=user.id)
    mock_fetch_credential.return_value = credential

    assert (
        api._require_connected_canvas_oauth_credential(
            db_session=MagicMock(), user=user, credential_id=30
        )
        is credential
    )


@patch("onyx.server.lti.api.fetch_credentials_by_source_for_user")
def test_get_lti_canvas_oauth_credential_prefers_live_connection_for_host(
    mock_fetch_credentials: MagicMock,
) -> None:
    user = _fake_user()
    pasted = _fake_credential(
        {oauth.CANVAS_ACCESS_TOKEN_KEY: "pasted"}, user_id=user.id, credential_id=1
    )
    pasted.name = "Canvas - CS101 credential"
    other_host = _fake_credential(
        _oauth_json(**{oauth.CANVAS_BASE_URL_KEY: "https://other.instructure.com"}),
        user_id=user.id,
        credential_id=2,
    )
    pending = _fake_credential(
        {oauth.CANVAS_BASE_URL_KEY: "https://school.instructure.com"},
        user_id=user.id,
        credential_id=3,
    )
    live = _fake_credential(_oauth_json(), user_id=user.id, credential_id=4)
    someone_elses = _fake_credential(_oauth_json(), credential_id=5)
    mock_fetch_credentials.return_value = [
        pasted,
        other_host,
        pending,
        live,
        someone_elses,
    ]

    chosen = api._get_lti_canvas_oauth_credential(
        db_session=MagicMock(),
        user=user,
        canvas_base_url="https://school.instructure.com/",
    )

    assert chosen is live


@patch("onyx.server.lti.api._consume_canvas_oauth_state", return_value=None)
def test_callback_with_unknown_state_reports_failure(
    _mock_consume: MagicMock,
) -> None:
    response = api.lti_canvas_oauth_callback(
        code="abc", state="nope", error=None, error_description=None
    )
    body = bytes(response.body).decode("utf-8")
    assert '"status": "failed"' in body
    assert "expired" in body


@patch("onyx.server.lti.api._consume_canvas_oauth_state")
def test_callback_with_access_denied_reports_cancelled(
    mock_consume: MagicMock,
) -> None:
    mock_consume.return_value = api.LtiCanvasOAuthState(
        user_id=str(uuid.uuid4()),
        course_id="ctx-1",
        credential_id=30,
        canvas_base_url="https://school.instructure.com",
        tenant_id="public",
    )

    response = api.lti_canvas_oauth_callback(
        code=None,
        state="state-1",
        error="access_denied",
        error_description="User denied",
    )

    assert '"status": "cancelled"' in bytes(response.body).decode("utf-8")


@patch("onyx.server.lti.api.backend_update_credential_json")
@patch("onyx.server.lti.api.fetch_credential_by_id")
@patch("onyx.server.lti.api.get_session_with_tenant")
@patch("onyx.server.lti.api.exchange_canvas_authorization_code")
@patch("onyx.server.lti.api._consume_canvas_oauth_state")
def test_callback_exchanges_code_and_stores_tokens(
    mock_consume: MagicMock,
    mock_exchange: MagicMock,
    mock_get_session: MagicMock,
    mock_fetch_credential: MagicMock,
    mock_update_credential: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api, "LTI_CANVAS_OAUTH_CLIENT_ID", "client-1")
    monkeypatch.setattr(api, "LTI_CANVAS_OAUTH_CLIENT_SECRET", "secret-1")
    monkeypatch.setattr(api, "WEB_DOMAIN", "https://onyx.example.com")
    user_id = uuid.uuid4()
    mock_consume.return_value = api.LtiCanvasOAuthState(
        user_id=str(user_id),
        course_id="ctx-1",
        credential_id=30,
        canvas_base_url="https://school.instructure.com",
        tenant_id="public",
    )
    mock_exchange.return_value = oauth.CanvasOAuthTokens(
        access_token="access-1",
        refresh_token="refresh-1",
        expires_in=3600,
        canvas_user_id=7,
        canvas_user_name="Ada Instructor",
    )
    mock_get_session.return_value.__enter__.return_value = MagicMock()
    credential = _fake_credential(
        {oauth.CANVAS_BASE_URL_KEY: "https://school.instructure.com"},
        user_id=user_id,
    )
    mock_fetch_credential.return_value = credential

    response = api.lti_canvas_oauth_callback(
        code="code-1", state="state-1", error=None, error_description=None
    )

    assert '"status": "success"' in bytes(response.body).decode("utf-8")
    exchange_kwargs = mock_exchange.call_args.kwargs
    assert exchange_kwargs["code"] == "code-1"
    assert exchange_kwargs["redirect_uri"] == (
        "https://onyx.example.com/auth/lti/canvas-oauth/callback"
    )
    stored_json = mock_update_credential.call_args.args[1]
    assert stored_json[oauth.CANVAS_ACCESS_TOKEN_KEY] == "access-1"
    assert stored_json[oauth.CANVAS_REFRESH_TOKEN_KEY] == "refresh-1"
    assert stored_json[oauth.CANVAS_USER_NAME_KEY] == "Ada Instructor"
    assert stored_json[oauth.CANVAS_OAUTH_CLIENT_ID_KEY] == "client-1"
