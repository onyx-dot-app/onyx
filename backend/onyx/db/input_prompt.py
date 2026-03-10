from collections.abc import Sequence
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlalchemy.orm import Session

from onyx.db.models import InputPrompt
from onyx.db.models import InputPrompt__User
from onyx.db.models import User
from onyx.db.persona import get_persona_by_id
from onyx.server.features.input_prompt.models import InputPromptSnapshot
from onyx.server.features.input_prompt.models import SyncPersonaInputPromptItem
from onyx.server.manage.models import UserInfo
from onyx.utils.logger import setup_logger

logger = setup_logger()


def insert_input_prompt(
    prompt: str,
    content: str,
    is_public: bool,
    user: User | None,
    persona_id: int | None,
    db_session: Session,
) -> InputPrompt:
    user_id = user.id if user else None

    # Use atomic INSERT ... ON CONFLICT DO NOTHING with RETURNING
    # to avoid race conditions with the uniqueness check
    stmt = pg_insert(InputPrompt).values(
        prompt=prompt,
        content=content,
        active=True,
        is_public=is_public,
        user_id=user_id,
        persona_id=persona_id,
    )

    # Use the appropriate constraint based on whether this is a user-owned or public prompt
    if user_id is not None:
        stmt = stmt.on_conflict_do_nothing(constraint="uq_inputprompt_prompt_user_id")
    elif persona_id is not None:
        stmt = stmt.on_conflict_do_nothing(
            constraint="uq_inputprompt_prompt_persona_id"
        )
    else:
        # Partial unique indexes cannot be targeted by constraint name;
        # must use index_elements + index_where
        stmt = stmt.on_conflict_do_nothing(
            index_elements=[InputPrompt.prompt],
            index_where=text(
                "is_public = TRUE AND user_id IS NULL AND persona_id IS NULL"
            ),
        )

    stmt = stmt.returning(InputPrompt)

    result = db_session.execute(stmt)
    input_prompt = result.scalar_one_or_none()

    if input_prompt is None:
        raise HTTPException(
            status_code=409,
            detail=f"A prompt shortcut with the name '{prompt}' already exists",
        )

    db_session.commit()
    return input_prompt


def update_input_prompt(
    user: User,
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

    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"A prompt shortcut with the name '{prompt}' already exists",
        )

    return input_prompt


def validate_user_prompt_authorization(user: User, input_prompt: InputPrompt) -> bool:
    prompt = InputPromptSnapshot.from_model(input_prompt=input_prompt)

    # Public prompts cannot be modified via the user API (only admins via admin endpoints)
    if prompt.is_public or prompt.user_id is None or prompt.persona_id is not None:
        return False

    # Anonymous users cannot modify user-owned prompts
    if user.is_anonymous:
        return False

    # User must own the prompt
    user_details = UserInfo.from_model(user)
    return str(user_details.id) == str(prompt.user_id)


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
    user: User,
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
    persona_id: int | None = None,
) -> list[InputPrompt]:
    """
    Returns all prompts belonging to the user or public prompts,
    excluding those the user has specifically disabled.
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
            # Return user-owned and public prompts
            ownership_filters = [
                InputPrompt.user_id == user_id,
                and_(
                    InputPrompt.is_public.is_(True),
                    InputPrompt.user_id.is_(None),
                    InputPrompt.persona_id.is_(None),
                ),
            ]
        else:
            # Return only user-owned prompts by default
            ownership_filters = [InputPrompt.user_id == user_id]

        if persona_id is not None:
            ownership_filters.append(InputPrompt.persona_id == persona_id)

        query = query.where(or_(*ownership_filters))

    else:
        # user_id is None - anonymous usage
        if include_public:
            query = query.where(InputPrompt.is_public)
        else:
            # No user and not requesting public prompts - return nothing
            return []

    if active is not None:
        query = query.where(InputPrompt.active == active)

    query = query.order_by(InputPrompt.id.asc())
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


def fetch_input_prompts_by_persona(
    db_session: Session,
    persona_id: int,
    active: bool | None = None,
) -> list[InputPrompt]:
    query = select(InputPrompt).where(
        InputPrompt.persona_id == persona_id,
        InputPrompt.is_public.is_(False),
    )
    if active is not None:
        query = query.where(InputPrompt.active == active)
    query = query.order_by(InputPrompt.id.asc())
    return list(db_session.scalars(query).all())


def insert_input_prompt_for_persona(
    prompt: str,
    content: str,
    active: bool,
    persona_id: int,
    user: User,
    db_session: Session,
) -> InputPrompt:
    _validate_persona_access(
        persona_id=persona_id, user=user, db_session=db_session, is_for_edit=True
    )
    input_prompt = insert_input_prompt(
        prompt=prompt,
        content=content,
        is_public=False,
        user=None,
        persona_id=persona_id,
        db_session=db_session,
    )
    if not active:
        input_prompt.active = False
        db_session.commit()
    return input_prompt


def sync_input_prompts_for_persona(
    user: User,
    persona_id: int,
    prompts: Sequence[SyncPersonaInputPromptItem],
    db_session: Session,
) -> list[InputPrompt]:
    _validate_persona_access(
        persona_id=persona_id, user=user, db_session=db_session, is_for_edit=True
    )
    existing_prompts = list(
        db_session.scalars(
            select(InputPrompt).where(
                InputPrompt.persona_id == persona_id,
                InputPrompt.is_public.is_(False),
            )
        ).all()
    )
    existing_by_id = {prompt.id: prompt for prompt in existing_prompts}
    incoming_ids: set[int] = set()

    try:
        for prompt in prompts:
            if prompt.id is None:
                db_session.add(
                    InputPrompt(
                        prompt=prompt.prompt,
                        content=prompt.content,
                        active=prompt.active,
                        is_public=False,
                        user_id=None,
                        persona_id=persona_id,
                    )
                )
                continue

            existing_prompt = existing_by_id.get(prompt.id)
            if existing_prompt is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Prompt id {prompt.id} does not belong to persona {persona_id}",
                )
            incoming_ids.add(prompt.id)
            existing_prompt.prompt = prompt.prompt
            existing_prompt.content = prompt.content
            existing_prompt.active = prompt.active

        for existing_prompt in existing_prompts:
            if existing_prompt.id not in incoming_ids:
                db_session.delete(existing_prompt)

        db_session.commit()
    except IntegrityError:
        db_session.rollback()
        raise HTTPException(
            status_code=409,
            detail="One or more prompt shortcut names already exist for this assistant",
        )

    return fetch_input_prompts_by_persona(
        db_session=db_session,
        persona_id=persona_id,
    )


def update_input_prompt_for_persona(
    user: User,
    persona_id: int,
    input_prompt_id: int,
    prompt: str,
    content: str,
    active: bool,
    db_session: Session,
) -> InputPrompt:
    _validate_persona_access(
        persona_id=persona_id, user=user, db_session=db_session, is_for_edit=True
    )
    input_prompt = db_session.scalar(
        select(InputPrompt).where(
            InputPrompt.id == input_prompt_id,
            InputPrompt.persona_id == persona_id,
        )
    )
    if input_prompt is None:
        raise ValueError(f"No persona input prompt with id {input_prompt_id}")

    input_prompt.prompt = prompt
    input_prompt.content = content
    input_prompt.active = active

    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"A prompt shortcut with the name '{prompt}' already exists",
        )

    return input_prompt


def remove_input_prompt_for_persona(
    user: User,
    persona_id: int,
    input_prompt_id: int,
    db_session: Session,
) -> None:
    _validate_persona_access(
        persona_id=persona_id, user=user, db_session=db_session, is_for_edit=True
    )
    input_prompt = db_session.scalar(
        select(InputPrompt).where(
            InputPrompt.id == input_prompt_id,
            InputPrompt.persona_id == persona_id,
        )
    )
    if input_prompt is None:
        raise ValueError(f"No persona input prompt with id {input_prompt_id}")

    db_session.delete(input_prompt)
    db_session.commit()


def _validate_persona_access(
    persona_id: int, user: User, db_session: Session, is_for_edit: bool
) -> None:
    try:
        get_persona_by_id(
            persona_id=persona_id,
            user=user,
            db_session=db_session,
            is_for_edit=is_for_edit,
        )
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
