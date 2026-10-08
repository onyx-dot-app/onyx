"""Skill/external-app table snapshot helpers for Craft tests."""

from __future__ import annotations

from typing import Any

from sqlalchemy import LargeBinary, literal, select
from sqlalchemy.orm import Session, class_mapper

from onyx.db.models import (
    ExternalApp,
    ExternalAppUserCredential,
    GatedActionPolicy,
    GatedApp,
    Skill,
    Skill__User,
    Skill__UserGroup,
    _EncryptedBase,
)
from onyx.utils.sensitive import SensitiveValue

# Parent -> child order (FKs all point child -> parent). Restore/insert in this
# order; delete in reverse so FK constraints stay satisfied.
_SKILL_ISOLATION_MODELS: tuple[type[Any], ...] = (
    Skill,
    ExternalApp,
    GatedApp,
    Skill__User,
    Skill__UserGroup,
    GatedActionPolicy,
    ExternalAppUserCredential,
)


def _column_keys(model: type[Any]) -> list[str]:
    return [attr.key for attr in class_mapper(model).column_attrs]


def _pk_keys(model: type[Any]) -> list[str]:
    mapper = class_mapper(model)
    pk_columns = set(mapper.primary_key)
    return [
        attr.key
        for attr in mapper.column_attrs
        if any(column in pk_columns for column in attr.columns)
    ]


def snapshot_skill_tables(
    session: Session,
) -> dict[type[Any], list[dict[str, Any]]]:
    snapshot: dict[type[Any], list[dict[str, Any]]] = {}
    for model in _SKILL_ISOLATION_MODELS:
        keys = _column_keys(model)
        snapshot[model] = [
            {key: getattr(row, key) for key in keys}  # ods: ignore[getattr]
            for row in session.execute(select(model)).scalars().all()
        ]
    return snapshot


def _raw_snapshot_value(value: Any) -> Any:
    """Reduce a snapshot value to something storable without decryption.

    ``SensitiveValue`` wraps encrypted bytes; pulling out ``_encrypted_bytes``
    writes the blob back exactly as it was read, so a row encrypted with a
    different ``ENCRYPTION_KEY_SECRET`` is restored untouched instead of
    failing to decrypt.
    """
    if isinstance(value, SensitiveValue):
        return value._encrypted_bytes  # noqa: SLF001
    return value


def _raw_row(model: type[Any], row: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    """Snapshot row keyed by physical column name, sensitive values reduced.

    Returns the row and the set of binary (encrypted) column names, which
    must be bound as ``LargeBinary`` literals so the ``EncryptedJson``/
    ``EncryptedString`` decorators never touch them (they re-encrypt or
    decrypt on bind).
    """
    mapper = class_mapper(model)
    raw: dict[str, Any] = {}
    encrypted: set[str] = set()
    for key in _column_keys(model):
        col = mapper.attrs[key].columns[0]
        value = _raw_snapshot_value(row[key])
        raw[col.name] = value
        if isinstance(col.type, _EncryptedBase):
            encrypted.add(col.name)
    return raw, encrypted


def restore_skill_tables(
    session: Session, snapshot: dict[type[Any], list[dict[str, Any]]]
) -> None:
    """Restore the snapshot using raw table statements.

    Bypassing the ORM unit of work is deliberate: ``merge`` compares the
    loaded row against the snapshot, which decrypts ``EncryptedJson``
    credential columns. On a DB whose rows were encrypted with a different
    ``ENCRYPTION_KEY_SECRET`` (e.g. a kind dev cluster), that comparison
    raises ``UnicodeDecodeError`` during teardown of an otherwise-passing
    test. Raw statements restore the stored bytes verbatim — no decryption,
    no comparison.
    """
    # Delete rows created during the test (children first so FKs stay valid).
    for model in reversed(_SKILL_ISOLATION_MODELS):
        pk_keys = _pk_keys(model)
        baseline_pks = {tuple(row[key] for key in pk_keys) for row in snapshot[model]}
        for row in session.execute(select(model)).scalars().all():
            if (
                tuple(getattr(row, key) for key in pk_keys)  # ods: ignore[getattr]
                not in baseline_pks
            ):
                session.delete(row)
        session.flush()

    # Re-insert baseline rows the test deleted and restore any it mutated
    # (parents first). Updating an unmodified row with its own snapshot
    # values is a harmless no-op, so no mutation tracking is needed.
    for model in _SKILL_ISOLATION_MODELS:
        tbl = model.__table__
        pk_keys = _pk_keys(model)
        pk_col_names = {
            class_mapper(model).attrs[key].columns[0].name for key in pk_keys
        }
        for row in snapshot[model]:
            raw_row, encrypted_cols = _raw_row(model, row)
            # Encrypted columns hold raw encrypted bytes; bind them as
            # LargeBinary literals so the column decorator never re-encrypts
            # or decrypts them.
            raw_row = {
                col_name: (
                    literal(value, type_=LargeBinary())
                    if col_name in encrypted_cols and value is not None
                    else value
                )
                for col_name, value in raw_row.items()
            }
            where = [tbl.c[col_name] == raw_row[col_name] for col_name in pk_col_names]
            if session.execute(tbl.select().where(*where)).first() is not None:
                set_values = {
                    col_name: value
                    for col_name, value in raw_row.items()
                    if col_name not in pk_col_names
                }
                if set_values:
                    session.execute(tbl.update().where(*where).values(set_values))
            else:
                session.execute(tbl.insert().values(raw_row))
        session.flush()

    session.commit()