"""PAT create and revoke write audit events with the token id and scopes."""

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import Permission
from onyx.server.pat.api import create_token, delete_token
from onyx.server.pat.models import CreateTokenRequest
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.utils.audit import events_for

pytestmark = pytest.mark.usefixtures("tenant_context", "audit_stream")


def test_create_and_revoke_write_events(
    db_session: Session,
    make_test_user: MakeTestUser,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Teardown deletes the user, and the PAT with it (ON DELETE CASCADE).
    user = make_test_user("pat-audit")

    created = create_token(
        request=CreateTokenRequest(
            name="ci token", expiration_days=30, scopes=[Permission.READ_SEARCH]
        ),
        user=user,
        db_session=db_session,
    )
    delete_token(token_id=created.id, user=user, db_session=db_session)

    (create,) = events_for(caplog, "pat.create")
    assert create["resource_type"] == "pat"
    assert create["resource_id"] == str(created.id)
    assert create["actor"]["user_id"] == str(user.id)
    assert create["extra"] == {
        "name": "ci token",
        "expiration_days": 30,
        "scopes": [Permission.READ_SEARCH.value],
    }
    # The raw token never reaches the stream.
    assert created.token not in caplog.text

    (revoke,) = events_for(caplog, "pat.revoke")
    assert revoke["resource_id"] == str(created.id)
