"""External-app credential values are encrypted at rest.

``ExternalApp.organization_credentials`` and
``ExternalAppUserCredential.user_credentials`` store encrypted bytes (via the
same ``EncryptedJson`` pipeline as ``credential.credential_json``) rather than
plaintext JSONB. These tests assert the raw column is binary and that the ORM
transparently wraps/round-trips it through ``SensitiveValue``.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType
from onyx.db.models import User
from onyx.utils.sensitive import SensitiveValue
from tests.external_dependency_unit.craft.db_helpers import make_external_app
from tests.external_dependency_unit.craft.db_helpers import make_skill
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.craft.db_helpers import make_user_credential


def _raw_column_bytes(db_session: Session, query: str, **params: object) -> bytes:
    """Read a credential column straight from the driver, bypassing the ORM
    type decorator, so we see what's physically stored."""
    stored = db_session.execute(sa.text(query), params).scalar_one()
    # bytea comes back as memoryview/bytes depending on driver.
    return bytes(stored)


def test_organization_credentials_stored_encrypted(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    org_creds = {"api_key": "sk-super-secret"}
    app = make_external_app(
        db_session,
        skill=make_skill(db_session),
        auth_template={"X-Api-Key": "{api_key}"},
        organization_credentials=org_creds,
    )
    db_session.commit()

    # ORM side: wrapped in SensitiveValue, decrypts back to the original dict.
    assert isinstance(app.organization_credentials, SensitiveValue)
    assert app.organization_credentials.get_value(apply_mask=False) == org_creds

    # Storage side: a binary blob, not JSONB.
    raw = _raw_column_bytes(
        db_session,
        "SELECT organization_credentials FROM external_app WHERE id = :id",
        id=app.id,
    )
    assert isinstance(raw, bytes)


def test_user_credentials_stored_encrypted(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    user: User = make_user(db_session)
    app = make_external_app(
        db_session,
        skill=make_skill(db_session),
        auth_template={"Authorization": "Bearer {access_token}"},
        app_type=ExternalAppType.SLACK,
    )
    user_creds = {"access_token": "xoxb-super-secret"}
    cred = make_user_credential(
        db_session, app=app, user=user, user_credentials=user_creds
    )
    db_session.commit()

    assert isinstance(cred.user_credentials, SensitiveValue)
    assert cred.user_credentials.get_value(apply_mask=False) == user_creds

    raw = _raw_column_bytes(
        db_session,
        "SELECT user_credentials FROM external_app_user_credential WHERE id = :id",
        id=cred.id,
    )
    assert isinstance(raw, bytes)
