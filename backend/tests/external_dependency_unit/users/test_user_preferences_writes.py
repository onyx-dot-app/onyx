"""The preference write owner refuses the shared anonymous account."""

from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import ANONYMOUS_USER_UUID
from onyx.db.user_preferences import upsert_user_preferences__no_commit
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


def test_anonymous_account_cannot_save_preferences(db_session: Session) -> None:
    with pytest.raises(OnyxError) as exc:
        upsert_user_preferences__no_commit(
            db_session, UUID(ANONYMOUS_USER_UUID), auto_scroll=False
        )
    assert exc.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    db_session.rollback()
