from collections.abc import Sequence
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.db.models import User, Validator, Persona__Validator
from onyx.server.features.guardrails.core.schemas_validator import (
    ValidatorCreate,
    ValidatorUpdate,
)


def get_validators_templates(db_session: Session) -> Sequence[Validator]:
    """Получить список шаблонов валидаторов"""

    stmt = select(Validator).where(Validator.user_id.is_(None))
    validators_templates: Sequence[Validator] = db_session.scalars(stmt).all()

    return validators_templates


def create_validator(
    db_session: Session,
    user: User | None,
    validator_create: ValidatorCreate,
) -> Validator:
    """Создать валидатор"""

    validator = Validator(
        user_id=user.id,
        name=validator_create.name,
        description=validator_create.description,
        validator_type=validator_create.validator_type,
        config=validator_create.config,
    )

    db_session.add(validator)
    db_session.commit()

    return validator


def get_validators(db_session: Session) -> Sequence[Validator]:
    """Получить список пользовательских валидаторов"""

    stmt = select(Validator).where(Validator.user_id.is_not(None))
    validators_templates: Sequence[Validator] = db_session.scalars(stmt).all()

    return validators_templates


def update_validator(
    db_session: Session,
    validator_id: int,
    validator_update: ValidatorUpdate,
) -> Validator | None:
    """Обновить валидатор"""

    validator = get_validator_by_id(
        db_session=db_session, validator_id=validator_id
    )

    validator.name = validator_update.name
    validator.description = validator_update.description
    validator.config = validator_update.config
    validator.updated_at = datetime.now(timezone.utc)

    db_session.commit()

    return validator


def delete_validator(
    db_session: Session, validator_id: int
) -> None:
    """Удалить валидатор по ID"""

    stmt = delete(Validator).where(Validator.id == validator_id)
    db_session.execute(stmt)

    stmt = delete(Persona__Validator).where(Persona__Validator.validator_id == validator_id)
    db_session.execute(stmt)

    db_session.commit()


def get_validator_by_id(
    db_session: Session, validator_id: int
) -> Validator | None:
    """Получить валидатор по ID"""

    stmt = select(Validator).where(Validator.id == validator_id)
    validator = db_session.scalars(stmt).one_or_none()

    if validator is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Validator with ID {validator_id} not found",
        )

    return validator
