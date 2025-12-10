from fastapi import HTTPException
from sqlalchemy import select, Select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, aliased

from onyx.auth.schemas import UserRole
from onyx.db.enums import ValidatorType
from onyx.db.models import (
    Persona,
    Persona__UserGroup,
    User,
    User__UserGroup,
    Validator,
)
from onyx.server.features.guardrails.core.schemas_validator import (
    ValidatorCreate,
    ValidatorUpdate,
)


def _add_user_filters(
    stmt: Select,
    user: User,
) -> Select:
    """Применяет фильтры к запросу валидаторов (проверка прав доступа)"""

    # ADMIN и GLOBAL_CURATOR видят все валидаторы
    admin_roles = [UserRole.ADMIN, UserRole.GLOBAL_CURATOR]
    if user and user.role in admin_roles:
        return stmt

    stmt = stmt.distinct()
    Persona__UG = aliased(Persona__UserGroup)
    User__UG = aliased(User__UserGroup)

    stmt = (
        stmt.outerjoin(Validator.personas)
        .outerjoin(
            Persona__UG,
            Persona__UG.persona_id == Persona.id,
        )
        .outerjoin(
            User__UG,
            User__UG.user_group_id == Persona__UG.user_group_id,
        )
    )

    where_clause = (User__UG.user_id == user.id) & (User__UG.is_curator == True)
    where_clause |= Validator.user_id == user.id

    return stmt.where(where_clause)


def get_validator_by_id_for_user(
    db_session: Session,
    validator_id: int,
    user: User | None,
) -> Validator:
    """Получает пользовательский валидатор по ID
    с предварительной проверкой прав доступа"""

    stmt = (
        select(Validator)
        .where(
            Validator.id == validator_id,
            Validator.user_id.is_not(None)
        )
        .options(
            joinedload(Validator.user),
        )
    )

    stmt = _add_user_filters(stmt=stmt, user=user)
    validator = db_session.scalars(stmt).unique().one_or_none()

    if not validator:
        raise HTTPException(
            status_code=404,
            detail=f"Валидатор с ID {validator_id} не найден или у вас нет прав доступа.",
        )

    return validator


def get_validators_for_user(
    db_session: Session,
    user: User | None,
) -> list[Validator]:
    """Получает список пользовательских валидаторов
    с предварительной проверкой прав доступа
    """

    stmt = select(Validator).options(
        joinedload(Validator.user),
    ).where(Validator.user_id.is_not(None))

    stmt = _add_user_filters(stmt=stmt, user=user)

    stmt = stmt.order_by(Validator.id.asc())

    return list(db_session.scalars(stmt).unique().all())


def create_validator(
    db_session: Session,
    user: User | None,
    validator_create: ValidatorCreate,
) -> Validator:
    """Создает новый валидатор"""

    if validator_create.include_llm:
        if not validator_create.llm_provider_id:
            raise HTTPException(
                status_code=400,
                detail="Необходимо выбрать LLM-провайдер для валидатора!"
            )

    new_validator = Validator(
        name=validator_create.name,
        description=validator_create.description,
        validator_type=validator_create.validator_type,
        config=validator_create.config,
        include_llm=validator_create.include_llm,
        llm_provider_id=validator_create.llm_provider_id,
        user_id=user.id,
    )

    try:
        db_session.add(new_validator)
        db_session.commit()
    except IntegrityError as e:
        db_session.rollback()
        if "uq_validator_name" in str(e):
            raise HTTPException(
                status_code=400,
                detail=f"Валидатор с таким названием уже существует!"
            )

    return new_validator


def update_validator(
    db_session: Session,
    user: User | None,
    validator_id: int,
    validator_update: ValidatorUpdate,
) -> Validator:
    """Обновляет существующий валидатор
    с предварительной проверкой прав доступа
    """

    validator = get_validator_by_id_for_user(
        db_session=db_session, validator_id=validator_id, user=user
    )

    if validator.include_llm:
        if not validator_update.llm_provider_id:
            raise HTTPException(
                status_code=400,
                detail="Необходимо выбрать LLM-провайдер для валидатора!"
            )

        validator.llm_provider_id = validator_update.llm_provider_id

    validator.name = validator_update.name
    validator.description = validator_update.description
    validator.config = validator_update.config
    validator.llm_provider_id = validator_update.llm_provider_id

    try:
        db_session.commit()
        db_session.refresh(validator)
    except IntegrityError as e:
        db_session.rollback()
        if "uq_validator_name" in str(e):
            raise HTTPException(
                status_code=400,
                detail=f"Валидатор с таким названием уже существует!"
            )

    return validator


def delete_validator(
    db_session: Session,
    user: User | None,
    validator_id: int,
) -> None:
    """Удаляет валидатор с предварительной проверкой прав доступа"""

    validator = get_validator_by_id_for_user(
        db_session=db_session, validator_id=validator_id, user=user
    )
    db_session.delete(validator)
    db_session.commit()


def get_validators_templates(db_session: Session) -> list[Validator]:
    """Получает список системных шаблонов валидаторов"""

    return list(
        db_session.scalars(
            select(Validator).where(Validator.user_id.is_(None))
        ).all()
    )
