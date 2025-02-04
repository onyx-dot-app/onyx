from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.models import Persona
from onyx.db.models import Prompt
from onyx.db.models import User
from onyx.utils.logger import setup_logger


# Note: As prompts are fairly innocuous/harmless, there are no protections
# to prevent users from messing with prompts of other users.

logger = setup_logger()


def _get_default_prompt(db_session: Session) -> Prompt:
    stmt = select(Prompt).where(Prompt.id == 0)
    result = db_session.execute(stmt)
    prompt = result.scalar_one_or_none()

    if prompt is None:
        raise RuntimeError("Default Prompt not found")

    return prompt


def get_default_prompt(db_session: Session) -> Prompt:
    return _get_default_prompt(db_session)


def get_prompts_by_ids(prompt_ids: list[int], db_session: Session) -> list[Prompt]:
    """Unsafe, can fetch prompts from all users"""
    if not prompt_ids:
        return []
    prompts = db_session.scalars(
        select(Prompt).where(Prompt.id.in_(prompt_ids)).where(Prompt.deleted.is_(False))
    ).all()

    return list(prompts)


def get_prompt_by_name(
    prompt_name: str, user: User | None, db_session: Session
) -> Prompt | None:
    stmt = select(Prompt).where(Prompt.name == prompt_name)

    # if user is not specified OR they are an admin, they should
    # have access to all prompts, so this where clause is not needed
    if user and user.role != UserRole.ADMIN:
        stmt = stmt.where(Prompt.user_id == user.id)

    # Order by ID to ensure consistent result when multiple prompts exist
    stmt = stmt.order_by(Prompt.id).limit(1)
    result = db_session.execute(stmt).scalar_one_or_none()
    return result


def build_prompt_name_from_persona_name(persona_name: str) -> str:
    return f"default-prompt__{persona_name}"


def upsert_prompt(
    db_session: Session,
    user: User | None,
    name: str,
    system_prompt: str,
    task_prompt: str,
    datetime_aware: bool,
    prompt_id: int | None = None,
    personas: list[Persona] | None = None,
    include_citations: bool = False,
    default_prompt: bool = True,
    # Support backwards compatibility
    description: str | None = None,
) -> Prompt:
    if description is None:
        description = f"Default prompt for {name}"

    if prompt_id is not None:
        prompt = db_session.query(Prompt).filter_by(id=prompt_id).first()
    else:
        prompt = get_prompt_by_name(prompt_name=name, user=user, db_session=db_session)

    if prompt:
        if not default_prompt and prompt.default_prompt:
            raise ValueError("Cannot update default prompt with non-default.")

        prompt.name = name
        prompt.description = description
        prompt.system_prompt = system_prompt
        prompt.task_prompt = task_prompt
        prompt.include_citations = include_citations
        prompt.datetime_aware = datetime_aware
        prompt.default_prompt = default_prompt

        if personas is not None:
            prompt.personas.clear()
            prompt.personas = personas

    else:
        prompt = Prompt(
            id=prompt_id,
            user_id=user.id if user else None,
            name=name,
            description=description,
            system_prompt=system_prompt,
            task_prompt=task_prompt,
            include_citations=include_citations,
            datetime_aware=datetime_aware,
            default_prompt=default_prompt,
            personas=personas or [],
        )
        db_session.add(prompt)

    # Flush the session so that the Prompt has an ID
    db_session.flush()

    return prompt
