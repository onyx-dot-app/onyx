from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import aliased
from sqlalchemy.orm import Session

from onyx.configs.app_configs import AUTH_TYPE
from onyx.configs.constants import AuthType
from onyx.db.models import InputPrompt
from onyx.db.models import InputPrompt__User
from onyx.db.models import User
from onyx.server.features.input_prompt.models import InputPromptSnapshot
from onyx.server.manage.models import UserInfo
from onyx.utils.logger import setup_logger

logger = setup_logger()


def insert_input_prompt_if_not_exists(
    user: User | None,
    input_prompt_id: int | None,
    prompt: str,
    content: str,
    active: bool,
    is_public: bool,
    db_session: Session,
    commit: bool = True,
) -> InputPrompt:
    if input_prompt_id is not None:
        input_prompt = (
            db_session.query(InputPrompt).filter_by(id=input_prompt_id).first()
        )
    else:
        query = db_session.query(InputPrompt).filter(InputPrompt.prompt == prompt)
        if user:
            query = query.filter(InputPrompt.user_id == user.id)
        else:
            query = query.filter(InputPrompt.user_id.is_(None))
        input_prompt = query.first()

    if input_prompt is None:
        input_prompt = InputPrompt(
            id=input_prompt_id,
            prompt=prompt,
            content=content,
            active=active,
            is_public=is_public or user is None,
            user_id=user.id if user else None,
        )
        db_session.add(input_prompt)

    if commit:
        db_session.commit()

    return input_prompt


def insert_input_prompt(
    prompt: str,
    content: str,
    is_public: bool,
    user: User | None,
    db_session: Session,
) -> InputPrompt:
    input_prompt = InputPrompt(
        prompt=prompt,
        content=content,
        active=True,
        is_public=is_public,
        user_id=user.id if user is not None else None,
    )
    db_session.add(input_prompt)
    db_session.commit()

    return input_prompt


def update_input_prompt(
    user: User | None,
    input_prompt_id: int,
    prompt: str,
    content: str,
    active: bool,
    db_session: Session,
) -> InputPrompt:
    input_prompt = db_session.scalar(
        select(InputPrompt).where(InputPrompt.id == input_prompt_id)
    )
    if input_prompt is None:
        raise ValueError(f"No input prompt with id {input_prompt_id}")

    if not validate_user_prompt_authorization(user, input_prompt):
        raise HTTPException(status_code=401, detail="You don't own this prompt")

    input_prompt.prompt = prompt
    input_prompt.content = content
    input_prompt.active = active

    db_session.commit()
    return input_prompt


def validate_user_prompt_authorization(
    user: User | None, input_prompt: InputPrompt
) -> bool:
    prompt = InputPromptSnapshot.from_model(input_prompt=input_prompt)

    if prompt.user_id is not None:
        if user is None:
            return False

        user_details = UserInfo.from_model(user)
        if str(user_details.id) != str(prompt.user_id):
            return False
    return True


def remove_public_input_prompt(input_prompt_id: int, db_session: Session) -> None:
    input_prompt = db_session.scalar(
        select(InputPrompt).where(InputPrompt.id == input_prompt_id)
    )

    if input_prompt is None:
        raise ValueError(f"No input prompt with id {input_prompt_id}")

    if not input_prompt.is_public:
        raise HTTPException(status_code=400, detail="This prompt is not public")

    db_session.delete(input_prompt)
    db_session.commit()


def remove_input_prompt(
    user: User | None,
    input_prompt_id: int,
    db_session: Session,
    delete_public: bool = False,
) -> None:
    input_prompt = db_session.scalar(
        select(InputPrompt).where(InputPrompt.id == input_prompt_id)
    )
    if input_prompt is None:
        raise ValueError(f"No input prompt with id {input_prompt_id}")

    if input_prompt.is_public and not delete_public:
        raise HTTPException(
            status_code=400, detail="Cannot delete public prompts with this method"
        )

    if not validate_user_prompt_authorization(user, input_prompt):
        raise HTTPException(status_code=401, detail="You do not own this prompt")

    db_session.delete(input_prompt)
    db_session.commit()


def fetch_input_prompt_by_id(
    id: int, user_id: UUID | None, db_session: Session
) -> InputPrompt:
    query = select(InputPrompt).where(InputPrompt.id == id)

    if user_id:
        query = query.where(
            (InputPrompt.user_id == user_id) | (InputPrompt.user_id is None)
        )
    else:
        # If no user_id is provided, only fetch prompts without a user_id (aka public)
        query = query.where(InputPrompt.user_id == None)  # noqa

    result = db_session.scalar(query)

    if result is None:
        raise HTTPException(422, "No input prompt found")

    return result


def fetch_public_input_prompts(
    db_session: Session,
) -> list[InputPrompt]:
    query = select(InputPrompt).where(InputPrompt.is_public)
    return list(db_session.scalars(query).all())


def fetch_input_prompts_by_user(
    db_session: Session,
    user_id: UUID | None,
    active: bool | None = None,
    include_public: bool = False,
) -> list[InputPrompt]:
    """
    Returns all prompts belonging to the user or public prompts,
    excluding those the user has specifically disabled.
    Also, if `user_id` is None and AUTH_TYPE is DISABLED, then all prompts are returned.
    """

    query = select(InputPrompt)

    if user_id is not None:
        # If we have a user, left join to InputPrompt__User to check "disabled"
        IPU = aliased(InputPrompt__User)
        query = query.join(
            IPU,
            (IPU.input_prompt_id == InputPrompt.id) & (IPU.user_id == user_id),
            isouter=True,
        )

        # Exclude disabled prompts
        query = query.where(or_(IPU.disabled.is_(None), IPU.disabled.is_(False)))

        if include_public:
            # Return both user-owned and public prompts
            query = query.where(
                or_(
                    InputPrompt.user_id == user_id,
                    InputPrompt.is_public,
                )
            )
        else:
            # Return only user-owned prompts
            query = query.where(InputPrompt.user_id == user_id)

    else:
        # user_id is None
        if AUTH_TYPE == AuthType.DISABLED:
            # If auth is disabled, return all prompts
            query = query.where(True)  # type: ignore
        elif include_public:
            # Anonymous usage
            query = query.where(InputPrompt.is_public)

        # Default to returning all prompts

    if active is not None:
        query = query.where(InputPrompt.active == active)

    return list(db_session.scalars(query).all())


def disable_input_prompt_for_user(
    input_prompt_id: int,
    user_id: UUID,
    db_session: Session,
) -> None:
    """
    Sets (or creates) a record in InputPrompt__User with disabled=True
    so that this prompt is hidden for the user.
    """
    ipu = (
        db_session.query(InputPrompt__User)
        .filter_by(input_prompt_id=input_prompt_id, user_id=user_id)
        .first()
    )

    if ipu is None:
        # Create a new association row
        ipu = InputPrompt__User(
            input_prompt_id=input_prompt_id, user_id=user_id, disabled=True
        )
        db_session.add(ipu)
    else:
        # Just update the existing record
        ipu.disabled = True

    db_session.commit()
