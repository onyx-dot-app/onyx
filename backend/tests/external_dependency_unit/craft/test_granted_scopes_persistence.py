"""Persisting the OAuth grant onto ``ExternalAppUserCredential.granted_scopes``
via ``upsert_external_app_user_credential`` (ENG-4261).

The connect flow records the authoritative grant (a list, or ``None`` for
"unknown" — both overwrite); refresh and credential-form saves omit the
argument (``UNSET``) and must leave a prior grant untouched."""

from __future__ import annotations

import time

from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType
from onyx.db.external_app import get_external_app_user_credential
from onyx.db.external_app import upsert_external_app_user_credential
from onyx.db.models import ExternalApp
from tests.external_dependency_unit.craft.db_helpers import make_external_app
from tests.external_dependency_unit.craft.db_helpers import make_skill
from tests.external_dependency_unit.craft.db_helpers import make_user

_BEARER = {"Authorization": "Bearer {access_token}"}


def _hubspot_app(db_session: Session) -> ExternalApp:
    return make_external_app(
        db_session,
        skill=make_skill(db_session),
        auth_template=_BEARER,
        app_type=ExternalAppType.HUBSPOT,
    )


def test_connect_records_granted_scopes(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    app = _hubspot_app(db_session)

    upsert_external_app_user_credential(
        db_session,
        external_app_id=app.id,
        user_id=user.id,
        user_credentials={"access_token": "t"},
        granted_scopes=["crm.read", "crm.write"],
    )

    cred = get_external_app_user_credential(
        db_session, external_app_id=app.id, user_id=user.id
    )
    assert cred is not None
    assert cred.granted_scopes == ["crm.read", "crm.write"]


def test_missing_scopes_leaves_grant_unknown(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    """A new row written without a grant argument is NULL — not an empty list —
    so downstream can tell "unknown" from "granted none"."""
    user = make_user(db_session)
    app = _hubspot_app(db_session)

    upsert_external_app_user_credential(
        db_session,
        external_app_id=app.id,
        user_id=user.id,
        user_credentials={"access_token": "t"},
    )

    cred = get_external_app_user_credential(
        db_session, external_app_id=app.id, user_id=user.id
    )
    assert cred is not None
    assert cred.granted_scopes is None


def test_refresh_preserves_existing_grant(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    """A later upsert that omits ``granted_scopes`` (the refresh / form path)
    rotates the credential but must not wipe the stored grant."""
    user = make_user(db_session)
    app = _hubspot_app(db_session)

    upsert_external_app_user_credential(
        db_session,
        external_app_id=app.id,
        user_id=user.id,
        user_credentials={"access_token": "t1"},
        granted_scopes=["crm.read", "crm.write"],
    )
    upsert_external_app_user_credential(
        db_session,
        external_app_id=app.id,
        user_id=user.id,
        user_credentials={"access_token": "t2"},
    )

    cred = get_external_app_user_credential(
        db_session, external_app_id=app.id, user_id=user.id
    )
    assert cred is not None
    assert cred.user_credentials.get_value(apply_mask=False)["access_token"] == "t2"
    assert cred.granted_scopes == ["crm.read", "crm.write"]


def test_reconnect_with_unknown_grant_clears_stale_scopes(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    """A reconnect whose scope extraction failed passes ``granted_scopes=None``
    and must clear the prior grant to NULL — a fresh authorize can change the
    grant, so keeping the old scopes would be stale."""
    user = make_user(db_session)
    app = _hubspot_app(db_session)

    upsert_external_app_user_credential(
        db_session,
        external_app_id=app.id,
        user_id=user.id,
        user_credentials={"access_token": "t1"},
        granted_scopes=["crm.read", "crm.write"],
    )
    upsert_external_app_user_credential(
        db_session,
        external_app_id=app.id,
        user_id=user.id,
        user_credentials={"access_token": "t2"},
        granted_scopes=None,
    )

    cred = get_external_app_user_credential(
        db_session, external_app_id=app.id, user_id=user.id
    )
    assert cred is not None
    assert cred.granted_scopes is None


def test_reconnect_bumps_updated_at(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    """A conflict-update refreshes `updated_at` (the hand-built ON CONFLICT
    clause sets it explicitly, since the column `onupdate` doesn't fire)."""
    user = make_user(db_session)
    app = _hubspot_app(db_session)

    first = upsert_external_app_user_credential(
        db_session,
        external_app_id=app.id,
        user_id=user.id,
        user_credentials={"access_token": "t1"},
    )
    # The conflict path returns the identity-mapped instance without
    # repopulating it from RETURNING, so reload to read the DB's real values.
    db_session.refresh(first)
    original_created_at = first.created_at
    original_updated_at = first.updated_at

    # `now()` is transaction-start time; a brief gap guarantees the second
    # transaction's timestamp is strictly later, so the assertion isn't flaky.
    time.sleep(0.05)

    second = upsert_external_app_user_credential(
        db_session,
        external_app_id=app.id,
        user_id=user.id,
        user_credentials={"access_token": "t2"},
    )
    db_session.refresh(second)

    assert second.updated_at > original_updated_at
    # created_at is untouched — this is an update, not a re-insert.
    assert second.created_at == original_created_at


def test_reconnect_overwrites_grant(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    """Reconnecting (a fresh grant) replaces the stored scopes wholesale."""
    user = make_user(db_session)
    app = _hubspot_app(db_session)

    upsert_external_app_user_credential(
        db_session,
        external_app_id=app.id,
        user_id=user.id,
        user_credentials={"access_token": "t"},
        granted_scopes=["crm.read"],
    )
    upsert_external_app_user_credential(
        db_session,
        external_app_id=app.id,
        user_id=user.id,
        user_credentials={"access_token": "t"},
        granted_scopes=["crm.read", "crm.write", "crm.delete"],
    )

    cred = get_external_app_user_credential(
        db_session, external_app_id=app.id, user_id=user.id
    )
    assert cred is not None
    assert cred.granted_scopes == ["crm.read", "crm.write", "crm.delete"]
