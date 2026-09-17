"""External-dependency unit test: Canvas OAuth refresh persists through the DB
credentials provider.

Runs against real Postgres + Redis. Canvas itself is mocked at the HTTP layer
(token endpoint + one course lookup); everything between the connector and the
`credential` row is real.
"""

import time
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.canvas import oauth
from onyx.connectors.canvas.connector import CanvasConnector
from onyx.connectors.credentials_provider import OnyxDBCredentialsProvider
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.db.credentials import create_credential
from onyx.db.credentials import fetch_credential_by_id
from onyx.server.documents.models import CredentialBase
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.conftest import create_test_user

CANVAS_URL = "https://school.instructure.com"
CLIENT_ID = "10000000000005"
CLIENT_SECRET = "shh"


def _json_response(status_code: int, payload: Any) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    response.headers = {"Link": ""}
    response.reason = "OK"
    return response


def _stored_json(db_session: Session, credential_id: int) -> dict[str, Any]:
    db_session.expire_all()
    credential = fetch_credential_by_id(credential_id, db_session)
    assert credential is not None and credential.credential_json is not None
    return dict(credential.credential_json.get_value(apply_mask=False))


def _create_oauth_credential(db_session: Session, expires_at: int) -> int:
    user = create_test_user(db_session, email_prefix=f"canvas_oauth_{uuid4().hex[:6]}")
    credential = create_credential(
        credential_data=CredentialBase(
            credential_json={
                oauth.CANVAS_ACCESS_TOKEN_KEY: "access-old",
                oauth.CANVAS_REFRESH_TOKEN_KEY: "refresh-1",
                oauth.CANVAS_TOKEN_EXPIRES_AT_KEY: expires_at,
                oauth.CANVAS_BASE_URL_KEY: CANVAS_URL,
                oauth.CANVAS_OAUTH_CLIENT_ID_KEY: CLIENT_ID,
            },
            admin_public=False,
            curator_public=False,
            source=DocumentSource.CANVAS,
            name=f"Canvas OAuth test {uuid4().hex[:6]}",
        ),
        user=user,
        db_session=db_session,
    )
    return credential.id


@pytest.fixture
def _oauth_client_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "onyx.connectors.canvas.connector.LTI_CANVAS_OAUTH_CLIENT_ID", CLIENT_ID
    )
    monkeypatch.setattr(
        "onyx.connectors.canvas.connector.LTI_CANVAS_OAUTH_CLIENT_SECRET",
        CLIENT_SECRET,
    )


@pytest.mark.usefixtures("_oauth_client_config")
@patch("onyx.connectors.canvas.oauth.requests.post")
@patch("onyx.connectors.canvas.client.rl_requests")
def test_expired_token_is_refreshed_and_persisted(
    mock_requests: MagicMock,
    mock_post: MagicMock,
    db_session: Session,
) -> None:
    credential_id = _create_oauth_credential(
        db_session, expires_at=int(time.time()) - 600
    )
    mock_post.return_value = _json_response(
        200, {"access_token": "access-new", "expires_in": 3600}
    )
    mock_requests.get.return_value = _json_response(
        200, {"id": 1, "name": "Intro", "course_code": "CS1"}
    )

    connector = CanvasConnector(canvas_base_url=CANVAS_URL, course_ids=[1])
    connector.set_credentials_provider(
        OnyxDBCredentialsProvider(
            get_current_tenant_id(), str(DocumentSource.CANVAS), credential_id
        )
    )

    stored = _stored_json(db_session, credential_id)
    assert stored[oauth.CANVAS_ACCESS_TOKEN_KEY] == "access-new"
    assert stored[oauth.CANVAS_REFRESH_TOKEN_KEY] == "refresh-1"
    assert stored[oauth.CANVAS_TOKEN_EXPIRES_AT_KEY] > int(time.time()) + 3000
    assert mock_requests.get.call_args.kwargs["headers"]["Authorization"] == (
        "Bearer access-new"
    )


@pytest.mark.usefixtures("_oauth_client_config")
@patch("onyx.connectors.canvas.oauth.requests.post")
@patch("onyx.connectors.canvas.client.rl_requests")
def test_revoked_refresh_token_marks_credential_invalid_in_db(
    mock_requests: MagicMock,
    mock_post: MagicMock,
    db_session: Session,
) -> None:
    credential_id = _create_oauth_credential(
        db_session, expires_at=int(time.time()) - 600
    )
    mock_post.return_value = _json_response(
        400, {"error": "invalid_grant", "error_description": "revoked"}
    )

    connector = CanvasConnector(canvas_base_url=CANVAS_URL, course_ids=[1])
    with pytest.raises(CredentialExpiredError):
        connector.set_credentials_provider(
            OnyxDBCredentialsProvider(
                get_current_tenant_id(), str(DocumentSource.CANVAS), credential_id
            )
        )

    stored = _stored_json(db_session, credential_id)
    assert oauth.canvas_credential_is_invalidated(stored)
    # The dead tokens are left in place for debugging; only the marker is added.
    assert stored[oauth.CANVAS_REFRESH_TOKEN_KEY] == "refresh-1"
    mock_requests.get.assert_not_called()
