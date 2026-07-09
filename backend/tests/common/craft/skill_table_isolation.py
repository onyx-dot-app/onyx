"""Skill/external-app table snapshot helpers for Craft tests."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import class_mapper
from sqlalchemy.orm import Session

from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppPolicy
from onyx.db.models import ExternalAppUserCredential
from onyx.db.models import Skill
from onyx.db.models import Skill__User
from onyx.db.models import Skill__UserGroup

# Parent -> child order (FKs all point child -> parent). Restore/insert in this
# order; delete in reverse so FK constraints stay satisfied.
_SKILL_ISOLATION_MODELS: tuple[type[Any], ...] = (
    Skill,
    ExternalApp,
    Skill__User,
    Skill__UserGroup,
    ExternalAppPolicy,
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
            {key: getattr(row, key) for key in keys}
            for row in session.execute(select(model)).scalars().all()
        ]
    return snapshot


def restore_skill_tables(
    session: Session, snapshot: dict[type[Any], list[dict[str, Any]]]
) -> None:
    # Delete rows created during the test (children first so FKs stay valid).
    for model in reversed(_SKILL_ISOLATION_MODELS):
        pk_keys = _pk_keys(model)
        baseline_pks = {tuple(row[key] for key in pk_keys) for row in snapshot[model]}
        for row in session.execute(select(model)).scalars().all():
            if tuple(getattr(row, key) for key in pk_keys) not in baseline_pks:
                session.delete(row)
        session.flush()

    # Re-insert baseline rows the test deleted and restore any it mutated
    # (parents first). ``merge`` keys on PK: insert when absent, update when
    # present.
    for model in _SKILL_ISOLATION_MODELS:
        for row in snapshot[model]:
            session.merge(model(**row))
        session.flush()

    session.commit()
