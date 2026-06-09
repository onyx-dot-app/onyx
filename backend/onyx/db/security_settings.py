"""Persistence for the singleton ``security_settings`` row.

One row per tenant schema (boolean PK pinned to ``true``). Every column is
an *override*: ``NULL`` == "fall back to env default".
"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from onyx.db.models import SecuritySettings as SecuritySettingsRow
from onyx.server.security.models import SecuritySettingsOverrides


def load_overrides(db_session: Session) -> SecuritySettingsOverrides:
    """Returns an empty overrides object (all-None) when no row exists."""
    row = db_session.execute(select(SecuritySettingsRow)).scalar_one_or_none()
    if row is None:
        return SecuritySettingsOverrides()
    return SecuritySettingsOverrides.model_validate(row, from_attributes=True)


def upsert_overrides(db_session: Session, overrides: SecuritySettingsOverrides) -> None:
    """Upsert the singleton row.

    We pass every column explicitly (not ``exclude_none``) so DO UPDATE
    actually clears fields the admin removed — leaving them out would keep
    the previously-set value.
    """
    payload = {
        name: getattr(overrides, name)
        for name in SecuritySettingsOverrides.model_fields
    }
    stmt = insert(SecuritySettingsRow).values(id=True, **payload)
    stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=payload)
    db_session.execute(stmt)
    db_session.commit()
