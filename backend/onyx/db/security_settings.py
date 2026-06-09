"""Persistence for the singleton ``security_settings`` row.

Per CLAUDE.md, all DB access lives under ``backend/onyx/db``; the runtime
store in ``onyx.server.security.store`` delegates here.

The table holds at most one row per tenant schema (boolean PK pinned to
``true``). Every column is an *override*: ``NULL`` means "use the env-derived
default" — same semantic as an absent key in the prior JSONB blob.
"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from onyx.db.models import SecuritySettings as SecuritySettingsRow
from onyx.server.security.models import SecuritySettingsOverrides

# Column names backing each override field. Kept in sync with
# ``SecuritySettingsOverrides`` / the ORM model; the runtime PUT path needs to
# null out columns when an admin clears a previously-set override, which is
# easier to express explicitly than via reflection.
_OVERRIDE_COLUMNS: tuple[str, ...] = (
    "user_directory_admin_only",
    "track_external_idp_expiry",
    "mask_credential_prefix",
    "valid_email_domains",
    "password_min_length",
    "password_max_length",
    "password_require_uppercase",
    "password_require_lowercase",
    "password_require_digit",
    "password_require_special_char",
)


def load_overrides(db_session: Session) -> SecuritySettingsOverrides:
    """Read the singleton row for the current tenant. Returns an empty
    overrides object when no row exists (the loader treats this as "all env
    defaults").
    """
    row = db_session.execute(select(SecuritySettingsRow)).scalar_one_or_none()
    if row is None:
        return SecuritySettingsOverrides()
    return SecuritySettingsOverrides.model_validate(row, from_attributes=True)


def upsert_overrides(db_session: Session, overrides: SecuritySettingsOverrides) -> None:
    """Upsert the singleton row.

    ``None`` on the overrides model writes ``NULL`` on the column (admin
    cleared the override → loader falls back to env). We pass every column
    explicitly so DO UPDATE actually clears fields the admin removed; relying
    on ``exclude_none=True`` would leave previously-set columns untouched.
    Caller holds the Redis lock that serializes read-modify-write across
    processes.
    """
    payload = {col: getattr(overrides, col) for col in _OVERRIDE_COLUMNS}
    stmt = insert(SecuritySettingsRow).values(id=True, **payload)
    stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=payload)
    db_session.execute(stmt)
    db_session.commit()
