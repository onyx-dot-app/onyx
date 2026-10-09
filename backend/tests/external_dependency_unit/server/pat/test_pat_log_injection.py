"""Log-injection regression test for PAT creation.

``create_token`` logged the user-supplied token name with ``'%s'``, so CR/LF in
the name could forge lines in the shared log stream. It now logs the name with
``%r``, which escapes control characters.
"""

from unittest.mock import patch

from sqlalchemy.orm import Session

from onyx.server.pat.api import create_token
from onyx.server.pat.models import CreateTokenRequest
from tests.external_dependency_unit.conftest import create_test_user


def test_create_token_escapes_name_in_logs(db_session: Session) -> None:
    user = create_test_user(db_session, "pat-user")
    request = CreateTokenRequest(name="legit\nINJECTED admin deleted tenant")

    with patch("onyx.server.pat.api.logger") as mock_logger:
        create_token(request=request, user=user, db_session=db_session)

    mock_logger.info.assert_called_once()
    fmt, *args = mock_logger.info.call_args.args

    # The untrusted name must be repr'd, not interpolated raw.
    assert "%r" in fmt

    # The fully-rendered log line carries no raw newline from the name.
    assert "\n" not in (fmt % tuple(args))
