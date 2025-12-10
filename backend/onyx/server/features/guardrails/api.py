from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from onyx.auth.users import current_curator_or_admin_user
from onyx.db import crud_validator
from onyx.db.engine import get_session
from onyx.db.models import User
from onyx.server.features.guardrails.core.schemas_validator import (
    ValidatorResponse,
    ValidatorCreate,
    ValidatorUpdate,
)

router = APIRouter(tags=["Validators"])


@router.get(
    "/validators/templates",
    summary="Получить список шаблонов валидаторов",
)
def get_validators_templates(
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> list[ValidatorResponse]:
    """Получить список шаблонов валидаторов"""

    return [
        ValidatorResponse.from_model(validator)
        for validator in crud_validator.get_validators_templates(
            db_session=db_session,
        )
    ]


@router.post(
    "/validators",
    summary="Создать валидатор",
    response_model=ValidatorResponse,
)
def create_validator(
    validator_create: ValidatorCreate,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> ValidatorResponse:
    """Создать валидатор"""

    validator = crud_validator.create_validator(
        db_session=db_session,
        user=user,
        validator_create=validator_create,
    )

    return ValidatorResponse.from_model(validator)


@router.get(
    "/validators",
    summary="Получить список пользовательских валидаторов",
)
def get_validators(
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> list[ValidatorResponse]:
    """Получить список пользовательских валидаторов"""

    return [
        ValidatorResponse.from_model(validator)
        for validator in crud_validator.get_validators_for_user(
            db_session=db_session, user=user
        )
    ]


@router.put(
    "/validators/{validator_id}",
    summary="Обновить валидатор",
    response_model=ValidatorResponse,
)
def update_validator(
    validator_id: Annotated[int, Path(ge=1)],
    validator_update: ValidatorUpdate,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> ValidatorResponse:
    """Обновить валидатор"""

    validator = crud_validator.update_validator(
        db_session=db_session,
        user=user,
        validator_id=validator_id,
        validator_update=validator_update
    )

    return ValidatorResponse.from_model(validator)


@router.delete(
    "/validators/{validator_id}",
    summary="Удалить валидатор по ID",
    status_code=204,
)
def delete_validator_by_id(
    validator_id: Annotated[int, Path(ge=1)],
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    """Удалить валидатор по ID"""

    crud_validator.delete_validator(
        db_session=db_session, user=user, validator_id=validator_id
    )


@router.get(
    "/validators/{validator_id}",
    summary="Получить валидатор по ID",
    response_model=ValidatorResponse,
)
def get_validator_by_id(
    validator_id: int,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> ValidatorResponse:
    """Получить валидатор по ID"""

    validator = crud_validator.get_validator_by_id_for_user(
        db_session=db_session,
        validator_id=validator_id,
        user=user,
    )

    return ValidatorResponse.from_model(validator)

