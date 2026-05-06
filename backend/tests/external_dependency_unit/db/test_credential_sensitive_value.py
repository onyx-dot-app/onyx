"""Test that Credential with nested JSON round-trips through SensitiveValue correctly.

Exercises the full encrypt → store → read → decrypt → SensitiveValue path
with realistic nested OAuth credential data, and verifies SQLAlchemy dirty
tracking works with nested dict comparison.

Requires a running Postgres instance.
"""

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.models import Credential
from onyx.utils.sensitive import SensitiveValue

# NOTE: this is not the real shape of a Drive credential,
# but it is intended to test nested JSON credential handling

_NESTED_CRED_JSON = {
    "oauth_tokens": {
        "access_token": "ya29.abc123",
        "refresh_token": "1//xEg-def456",
    },
    "scopes": ["read", "write", "admin"],
    "client_config": {
        "client_id": "123.apps.googleusercontent.com",
        "client_secret": "GOCSPX-secret",
    },
}


def test_nested_credential_json_round_trip(db_session: Session) -> None:
    """Nested OAuth credential survives encrypt → store → read → decrypt."""
    credential = Credential(
        source=DocumentSource.GOOGLE_DRIVE,
        credential_json=_NESTED_CRED_JSON,
    )
    db_session.add(credential)
    db_session.flush()

    # Immediate read (no DB round-trip) — tests the set event wrapping
    assert isinstance(credential.credential_json, SensitiveValue)
    assert credential.credential_json.get_value(apply_mask=False) == _NESTED_CRED_JSON

    # DB round-trip — tests process_result_value
    db_session.expire(credential)
    reloaded = credential.credential_json
    assert isinstance(reloaded, SensitiveValue)
    assert reloaded.get_value(apply_mask=False) == _NESTED_CRED_JSON

    db_session.rollback()


def test_reassign_same_nested_json_not_dirty(db_session: Session) -> None:
    """Re-assigning the same nested dict should not mark the session dirty."""
    credential = Credential(
        source=DocumentSource.GOOGLE_DRIVE,
        credential_json=_NESTED_CRED_JSON,
    )
    db_session.add(credential)
    db_session.flush()

    # Clear dirty state from the insert
    db_session.expire(credential)
    _ = credential.credential_json  # force reload

    # Re-assign identical value
    credential.credential_json = _NESTED_CRED_JSON  # ty: ignore[invalid-assignment]
    assert not db_session.is_modified(credential)

    db_session.rollback()


def test_assign_different_nested_json_is_dirty(db_session: Session) -> None:
    """Assigning a different nested dict should mark the session dirty."""
    credential = Credential(
        source=DocumentSource.GOOGLE_DRIVE,
        credential_json=_NESTED_CRED_JSON,
    )
    db_session.add(credential)
    db_session.flush()

    db_session.expire(credential)
    _ = credential.credential_json  # force reload

    modified_cred = {**_NESTED_CRED_JSON, "scopes": ["read"]}
    credential.credential_json = modified_cred  # ty: ignore[invalid-assignment]
    assert db_session.is_modified(credential)

    db_session.rollback()
