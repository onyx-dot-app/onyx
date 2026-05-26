from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
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


@patch("onyx.server.lti.api.get_document_counts_for_cc_pairs")
@patch("onyx.server.lti.api.get_latest_index_attempt_for_cc_pair_id")
@patch("onyx.server.lti.api.fetch_canvas_cc_pair_for_lti_course")
def test_lti_course_connector_status_uses_indexed_document_relationship(
    mock_fetch_cc_pair: MagicMock,
    mock_latest_attempt: MagicMock,
    mock_document_counts: MagicMock,
) -> None:
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
