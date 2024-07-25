from collections.abc import Sequence
from functools import lru_cache
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import not_
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import Session

from danswer.auth.schemas import UserRole
from danswer.configs.chat_configs import BING_API_KEY
from danswer.db.constants import SLACK_BOT_PERSONA_PREFIX
from danswer.db.engine import get_sqlalchemy_engine
from danswer.db.models import DocumentSet
from danswer.db.models import Persona
from danswer.db.models import Persona__User
from danswer.db.models import Persona__UserGroup
from danswer.db.models import Prompt
from danswer.db.models import StarterMessage
from danswer.db.models import Tool
from danswer.db.models import User
from danswer.db.models import User__UserGroup
from danswer.search.enums import RecencyBiasSetting
from danswer.server.features.persona.models import CreatePersonaRequest
from danswer.server.features.persona.models import PersonaSnapshot
from danswer.utils.logger import setup_logger
from danswer.utils.variable_functionality import fetch_versioned_implementation

logger = setup_logger()


def make_persona_private(
    persona_id: int,
    user_ids: list[UUID] | None,
    group_ids: list[int] | None,
    db_session: Session,
) -> None:
    if user_ids is not None:
        db_session.query(Persona__User).filter(
            Persona__User.persona_id == persona_id
        ).delete(synchronize_session="fetch")

        for user_uuid in user_ids:
            db_session.add(Persona__User(persona_id=persona_id, user_id=user_uuid))

        db_session.commit()

    # May cause error if someone switches down to MIT from EE
    if group_ids:
        raise NotImplementedError("Danswer MIT does not support private Personas")


def create_update_persona(
    persona_id: int | None,
    create_persona_request: CreatePersonaRequest,
    user: User | None,
    db_session: Session,
) -> PersonaSnapshot:
    """Higher level function than upsert_persona, although either is valid to use."""
    # Permission to actually use these is checked later
    try:
        persona = upsert_persona(
            persona_id=persona_id,
            user=user,
            name=create_persona_request.name,
            description=create_persona_request.description,
            num_chunks=create_persona_request.num_chunks,
            llm_relevance_filter=create_persona_request.llm_relevance_filter,
            llm_filter_extraction=create_persona_request.llm_filter_extraction,
            recency_bias=create_persona_request.recency_bias,
            prompt_ids=create_persona_request.prompt_ids,
            tool_ids=create_persona_request.tool_ids,
            document_set_ids=create_persona_request.document_set_ids,
            llm_model_provider_override=create_persona_request.llm_model_provider_override,
            llm_model_version_override=create_persona_request.llm_model_version_override,
            starter_messages=create_persona_request.starter_messages,
            is_public=create_persona_request.is_public,
            db_session=db_session,
        )

        versioned_make_persona_private = fetch_versioned_implementation(
            "danswer.db.persona", "make_persona_private"
        )

        # Privatize Persona
        versioned_make_persona_private(
            persona_id=persona.id,
            user_ids=create_persona_request.users,
            group_ids=create_persona_request.groups,
            db_session=db_session,
        )

    except ValueError as e:
        logger.exception("Failed to create persona")
        raise HTTPException(status_code=400, detail=str(e))
    return PersonaSnapshot.from_model(persona)


def update_persona_shared_users(
    persona_id: int,
    user_ids: list[UUID],
    user: User | None,
    db_session: Session,
) -> None:
    """Simplified version of `create_update_persona` which only touches the
    accessibility rather than any of the logic (e.g. prompt, connected data sources,
    etc.)."""
    persona = fetch_persona_by_id(db_session=db_session, persona_id=persona_id)
    if not persona:
        raise HTTPException(
            status_code=404, detail=f"Persona with ID {persona_id} not found"
        )

    check_user_can_edit_persona(user=user, persona=persona)

    if persona.is_public:
        raise HTTPException(status_code=400, detail="Cannot share public persona")

    versioned_make_persona_private = fetch_versioned_implementation(
        "danswer.db.persona", "make_persona_private"
    )

    # Privatize Persona
    versioned_make_persona_private(
        persona_id=persona_id,
        user_ids=user_ids,
        group_ids=None,
        db_session=db_session,
    )


def fetch_persona_by_id(db_session: Session, persona_id: int) -> Persona | None:
    return db_session.scalar(select(Persona).where(Persona.id == persona_id))


def get_prompts(
    user_id: UUID | None,
    db_session: Session,
    include_default: bool = True,
    include_deleted: bool = False,
) -> Sequence[Prompt]:
    stmt = select(Prompt).where(
        or_(Prompt.user_id == user_id, Prompt.user_id.is_(None))
    )

    if not include_default:
        stmt = stmt.where(Prompt.default_prompt.is_(False))
    if not include_deleted:
        stmt = stmt.where(Prompt.deleted.is_(False))

    return db_session.scalars(stmt).all()


def get_personas(
    # if user_id is `None` assume the user is an admin or auth is disabled
    user_id: UUID | None,
    db_session: Session,
    include_default: bool = True,
    include_slack_bot_personas: bool = False,
    include_deleted: bool = False,
) -> Sequence[Persona]:
    stmt = select(Persona).distinct()
    if user_id is not None:
        # Subquery to find all groups the user belongs to
        user_groups_subquery = (
            select(User__UserGroup.user_group_id)
            .where(User__UserGroup.user_id == user_id)
            .subquery()
        )

        # Include personas where the user is directly related or part of a user group that has access
        access_conditions = or_(
            Persona.is_public == True,  # noqa: E712
            Persona.id.in_(  # User has access through list of users with access
                select(Persona__User.persona_id).where(Persona__User.user_id == user_id)
            ),
            Persona.id.in_(  # User is part of a group that has access
                select(Persona__UserGroup.persona_id).where(
                    Persona__UserGroup.user_group_id.in_(user_groups_subquery)  # type: ignore
                )
            ),
        )
        stmt = stmt.where(access_conditions)

    if not include_default:
        stmt = stmt.where(Persona.default_persona.is_(False))
    if not include_slack_bot_personas:
        stmt = stmt.where(not_(Persona.name.startswith(SLACK_BOT_PERSONA_PREFIX)))
    if not include_deleted:
        stmt = stmt.where(Persona.deleted.is_(False))

    return db_session.scalars(stmt).all()


def mark_persona_as_deleted(
    persona_id: int,
    user: User | None,
    db_session: Session,
) -> None:
    persona = get_persona_by_id(persona_id=persona_id, user=user, db_session=db_session)
    persona.deleted = True
    db_session.commit()


def mark_persona_as_not_deleted(
    persona_id: int,
    user: User | None,
    db_session: Session,
) -> None:
    persona = get_persona_by_id(
        persona_id=persona_id, user=user, db_session=db_session, include_deleted=True
    )
    if persona.deleted:
        persona.deleted = False
        db_session.commit()
    else:
        raise ValueError(f"Persona with ID {persona_id} is not deleted.")


def mark_delete_persona_by_name(
    persona_name: str, db_session: Session, is_default: bool = True
) -> None:
    stmt = (
        update(Persona)
        .where(Persona.name == persona_name, Persona.default_persona == is_default)
        .values(deleted=True)
    )

    db_session.execute(stmt)
    db_session.commit()


def update_all_personas_display_priority(
    display_priority_map: dict[int, int],
    db_session: Session,
) -> None:
    """Updates the display priority of all lives Personas"""
    personas = get_personas(user_id=None, db_session=db_session)
    available_persona_ids = {persona.id for persona in personas}
    if available_persona_ids != set(display_priority_map.keys()):
        raise ValueError("Invalid persona IDs provided")

    for persona in personas:
        persona.display_priority = display_priority_map[persona.id]

    db_session.commit()


def upsert_prompt(
    user: User | None,
    name: str,
    description: str,
    system_prompt: str,
    task_prompt: str,
    include_citations: bool,
    datetime_aware: bool,
    personas: list[Persona] | None,
    db_session: Session,
    prompt_id: int | None = None,
    default_prompt: bool = True,
    commit: bool = True,
) -> Prompt:
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

    if commit:
        db_session.commit()
    else:
        # Flush the session so that the Prompt has an ID
        db_session.flush()

    return prompt


def upsert_persona(
    user: User | None,
    name: str,
    description: str,
    num_chunks: float,
    llm_relevance_filter: bool,
    llm_filter_extraction: bool,
    recency_bias: RecencyBiasSetting,
    llm_model_provider_override: str | None,
    llm_model_version_override: str | None,
    starter_messages: list[StarterMessage] | None,
    is_public: bool,
    db_session: Session,
    prompt_ids: list[int] | None = None,
    document_set_ids: list[int] | None = None,
    tool_ids: list[int] | None = None,
    persona_id: int | None = None,
    default_persona: bool = False,
    commit: bool = True,
) -> Persona:
    if persona_id is not None:
        persona = db_session.query(Persona).filter_by(id=persona_id).first()
    else:
        persona = get_persona_by_name(
            persona_name=name, user=user, db_session=db_session
        )

    # Fetch and attach tools by IDs
    tools = None
    if tool_ids is not None:
        tools = db_session.query(Tool).filter(Tool.id.in_(tool_ids)).all()
        if not tools and tool_ids:
            raise ValueError("Tools not found")

    # Fetch and attach document_sets by IDs
    document_sets = None
    if document_set_ids is not None:
        document_sets = (
            db_session.query(DocumentSet)
            .filter(DocumentSet.id.in_(document_set_ids))
            .all()
        )
        if not document_sets and document_set_ids:
            raise ValueError("document_sets not found")

    # Fetch and attach prompts by IDs
    prompts = None
    if prompt_ids is not None:
        prompts = db_session.query(Prompt).filter(Prompt.id.in_(prompt_ids)).all()
        if not prompts and prompt_ids:
            raise ValueError("prompts not found")

    # ensure all specified tools are valid
    if tools:
        validate_persona_tools(tools)

    if persona:
        if not default_persona and persona.default_persona:
            raise ValueError("Cannot update default persona with non-default.")

        check_user_can_edit_persona(user=user, persona=persona)

        persona.name = name
        persona.description = description
        persona.num_chunks = num_chunks
        persona.llm_relevance_filter = llm_relevance_filter
        persona.llm_filter_extraction = llm_filter_extraction
        persona.recency_bias = recency_bias
        persona.default_persona = default_persona
        persona.llm_model_provider_override = llm_model_provider_override
        persona.llm_model_version_override = llm_model_version_override
        persona.starter_messages = starter_messages
        persona.deleted = False  # Un-delete if previously deleted
        persona.is_public = is_public

        # Do not delete any associations manually added unless
        # a new updated list is provided
        if document_sets is not None:
            persona.document_sets.clear()
            persona.document_sets = document_sets or []

        if prompts is not None:
            persona.prompts.clear()
            persona.prompts = prompts or []

        if tools is not None:
            persona.tools = tools or []

    else:
        persona = Persona(
            id=persona_id,
            user_id=user.id if user else None,
            is_public=is_public,
            name=name,
            description=description,
            num_chunks=num_chunks,
            llm_relevance_filter=llm_relevance_filter,
            llm_filter_extraction=llm_filter_extraction,
            recency_bias=recency_bias,
            default_persona=default_persona,
            prompts=prompts or [],
            document_sets=document_sets or [],
            llm_model_provider_override=llm_model_provider_override,
            llm_model_version_override=llm_model_version_override,
            starter_messages=starter_messages,
            tools=tools or [],
        )
        db_session.add(persona)

    if commit:
        db_session.commit()
    else:
        # flush the session so that the persona has an ID
        db_session.flush()

    return persona


def mark_prompt_as_deleted(
    prompt_id: int,
    user: User | None,
    db_session: Session,
) -> None:
    prompt = get_prompt_by_id(prompt_id=prompt_id, user=user, db_session=db_session)
    prompt.deleted = True
    db_session.commit()


def delete_old_default_personas(
    db_session: Session,
) -> None:
    """Note, this locks out the Summarize and Paraphrase personas for now
    Need a more graceful fix later or those need to never have IDs"""
    stmt = (
        update(Persona)
        .where(Persona.default_persona, Persona.id > 0)
        .values(deleted=True, name=func.concat(Persona.name, "_old"))
    )

    db_session.execute(stmt)
    db_session.commit()


def update_persona_visibility(
    persona_id: int,
    is_visible: bool,
    db_session: Session,
) -> None:
    persona = get_persona_by_id(persona_id=persona_id, user=None, db_session=db_session)
    persona.is_visible = is_visible
    db_session.commit()


def validate_persona_tools(tools: list[Tool]) -> None:
    for tool in tools:
        if tool.name == "InternetSearchTool" and not BING_API_KEY:
            raise ValueError(
                "Bing API key not found, please contact your Danswer admin to get it added!"
            )


def check_user_can_edit_persona(user: User | None, persona: Persona) -> None:
    # if user is None, assume that no-auth is turned on
    if user is None:
        return

    # admins can edit everything
    if user.role == UserRole.ADMIN:
        return

    # otherwise, make sure user owns persona
    if persona.user_id != user.id:
        raise HTTPException(
            status_code=403,
            detail=f"User not authorized to edit persona with ID {persona.id}",
        )


def get_prompts_by_ids(prompt_ids: list[int], db_session: Session) -> Sequence[Prompt]:
    """Unsafe, can fetch prompts from all users"""
    if not prompt_ids:
        return []
    prompts = db_session.scalars(select(Prompt).where(Prompt.id.in_(prompt_ids))).all()

    return prompts


def get_prompt_by_id(
    prompt_id: int,
    user: User | None,
    db_session: Session,
    include_deleted: bool = False,
) -> Prompt:
    stmt = select(Prompt).where(Prompt.id == prompt_id)

    # if user is not specified OR they are an admin, they should
    # have access to all prompts, so this where clause is not needed
    if user and user.role != UserRole.ADMIN:
        stmt = stmt.where(or_(Prompt.user_id == user.id, Prompt.user_id.is_(None)))

    if not include_deleted:
        stmt = stmt.where(Prompt.deleted.is_(False))

    result = db_session.execute(stmt)
    prompt = result.scalar_one_or_none()

    if prompt is None:
        raise ValueError(
            f"Prompt with ID {prompt_id} does not exist or does not belong to user"
        )

    return prompt


def _get_default_prompt(db_session: Session) -> Prompt:
    stmt = select(Prompt).where(Prompt.id == 0)
    result = db_session.execute(stmt)
    prompt = result.scalar_one_or_none()

    if prompt is None:
        raise RuntimeError("Default Prompt not found")

    return prompt


def get_default_prompt(db_session: Session) -> Prompt:
    return _get_default_prompt(db_session)


@lru_cache()
def get_default_prompt__read_only() -> Prompt:
    """Due to the way lru_cache / SQLAlchemy works, this can cause issues
    when trying to attach the returned `Prompt` object to a `Persona`. If you are
    doing anything other than reading, you should use the `get_default_prompt`
    method instead."""
    with Session(get_sqlalchemy_engine()) as db_session:
        return _get_default_prompt(db_session)


def get_persona_by_id(
    persona_id: int,
    # if user is `None` assume the user is an admin or auth is disabled
    user: User | None,
    db_session: Session,
    include_deleted: bool = False,
    is_for_edit: bool = True,  # NOTE: assume true for safety
) -> Persona:
    stmt = select(Persona).where(Persona.id == persona_id)

    or_conditions = []

    # if user is an admin, they should have access to all Personas
    if user is not None and user.role != UserRole.ADMIN:
        or_conditions.extend([Persona.user_id == user.id, Persona.user_id.is_(None)])

        # if we aren't editing, also give access to all public personas
        if not is_for_edit:
            or_conditions.append(Persona.is_public.is_(True))

    if or_conditions:
        stmt = stmt.where(or_(*or_conditions))

    if not include_deleted:
        stmt = stmt.where(Persona.deleted.is_(False))

    result = db_session.execute(stmt)
    persona = result.scalar_one_or_none()

    if persona is None:
        raise ValueError(
            f"Persona with ID {persona_id} does not exist or does not belong to user"
        )

    return persona


def get_personas_by_ids(
    persona_ids: list[int], db_session: Session
) -> Sequence[Persona]:
    """Unsafe, can fetch personas from all users"""
    if not persona_ids:
        return []
    personas = db_session.scalars(
        select(Persona).where(Persona.id.in_(persona_ids))
    ).all()

    return personas


def get_prompt_by_name(
    prompt_name: str, user: User | None, db_session: Session
) -> Prompt | None:
    stmt = select(Prompt).where(Prompt.name == prompt_name)

    # if user is not specified OR they are an admin, they should
    # have access to all prompts, so this where clause is not needed
    if user and user.role != UserRole.ADMIN:
        stmt = stmt.where(Prompt.user_id == user.id)

    result = db_session.execute(stmt).scalar_one_or_none()
    return result


def get_persona_by_name(
    persona_name: str, user: User | None, db_session: Session
) -> Persona | None:
    """Admins can see all, regular users can only fetch their own.
    If user is None, assume the user is an admin or auth is disabled."""
    stmt = select(Persona).where(Persona.name == persona_name)
    if user and user.role != UserRole.ADMIN:
        stmt = stmt.where(Persona.user_id == user.id)
    result = db_session.execute(stmt).scalar_one_or_none()
    return result


def delete_persona_by_name(
    persona_name: str, db_session: Session, is_default: bool = True
) -> None:
    stmt = delete(Persona).where(
        Persona.name == persona_name, Persona.default_persona == is_default
    )

    db_session.execute(stmt)

    db_session.commit()
