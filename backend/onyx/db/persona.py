from collections.abc import Sequence
from datetime import datetime
from functools import lru_cache
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import not_
from sqlalchemy import or_
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import aliased
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.configs.chat_configs import BING_API_KEY
from onyx.configs.chat_configs import CONTEXT_CHUNKS_ABOVE
from onyx.configs.chat_configs import CONTEXT_CHUNKS_BELOW
from onyx.context.search.enums import RecencyBiasSetting
from onyx.db.constants import SLACK_BOT_PERSONA_PREFIX
from onyx.db.engine import get_sqlalchemy_engine
from onyx.db.models import DocumentSet
from onyx.db.models import Persona
from onyx.db.models import Persona__User
from onyx.db.models import Persona__UserGroup
from onyx.db.models import PersonaCategory
from onyx.db.models import Prompt
from onyx.db.models import StarterMessage
from onyx.db.models import Tool
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
from onyx.server.features.persona.models import CreatePersonaRequest
from onyx.server.features.persona.models import PersonaSnapshot
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_versioned_implementation

logger = setup_logger()


def _add_user_filters(
    stmt: Select, user: User | None, get_editable: bool = True
) -> Select:
    # If user is None, assume the user is an admin or auth is disabled
    if user is None or user.role == UserRole.ADMIN:
        return stmt

    Persona__UG = aliased(Persona__UserGroup)
    User__UG = aliased(User__UserGroup)
    """
    Here we select cc_pairs by relation:
    User -> User__UserGroup -> Persona__UserGroup -> Persona
    """
    stmt = (
        stmt.outerjoin(Persona__UG)
        .outerjoin(
            User__UserGroup,
            User__UserGroup.user_group_id == Persona__UG.user_group_id,
        )
        .outerjoin(
            Persona__User,
            Persona__User.persona_id == Persona.id,
        )
    )
    """
    Filter Personas by:
    - if the user is in the user_group that owns the Persona
    - if the user is not a global_curator, they must also have a curator relationship
    to the user_group
    - if editing is being done, we also filter out Personas that are owned by groups
    that the user isn't a curator for
    - if we are not editing, we show all Personas in the groups the user is a curator
    for (as well as public Personas)
    - if we are not editing, we return all Personas directly connected to the user
    """
    where_clause = User__UserGroup.user_id == user.id
    if user.role == UserRole.CURATOR and get_editable:
        where_clause &= User__UserGroup.is_curator == True  # noqa: E712
    if get_editable:
        user_groups = select(User__UG.user_group_id).where(User__UG.user_id == user.id)
        if user.role == UserRole.CURATOR:
            user_groups = user_groups.where(User__UG.is_curator == True)  # noqa: E712
        where_clause &= (
            ~exists()
            .where(Persona__UG.persona_id == Persona.id)
            .where(~Persona__UG.user_group_id.in_(user_groups))
            .correlate(Persona)
        )
    else:
        where_clause |= Persona.is_public == True  # noqa: E712
        where_clause &= Persona.is_visible == True  # noqa: E712
        where_clause |= Persona__User.user_id == user.id
    where_clause |= Persona.user_id == user.id

    return stmt.where(where_clause)


# fetch_persona_by_id is used to fetch a persona by its ID. It is used to fetch a persona by its ID.


def fetch_persona_by_id(
    db_session: Session, persona_id: int, user: User | None, get_editable: bool = True
) -> Persona:
    stmt = select(Persona).where(Persona.id == persona_id).distinct()
    stmt = _add_user_filters(stmt=stmt, user=user, get_editable=get_editable)
    persona = db_session.scalars(stmt).one_or_none()
    if not persona:
        raise HTTPException(
            status_code=403,
            detail=f"Persona with ID {persona_id} does not exist or user is not authorized to access it",
        )
    return persona


def get_best_persona_id_for_user(
    db_session: Session, user: User | None, persona_id: int | None = None
) -> int | None:
    if persona_id is not None:
        stmt = select(Persona).where(Persona.id == persona_id).distinct()
        stmt = _add_user_filters(
            stmt=stmt,
            user=user,
            # We don't want to filter by editable here, we just want to see if the
            # persona is usable by the user
            get_editable=False,
        )
        persona = db_session.scalars(stmt).one_or_none()
        if persona:
            return persona.id

    # If the persona is not found, or the slack bot is using doc sets instead of personas,
    # we need to find the best persona for the user
    # This is the persona with the highest display priority that the user has access to
    stmt = select(Persona).order_by(Persona.display_priority.desc()).distinct()
    stmt = _add_user_filters(stmt=stmt, user=user, get_editable=True)
    persona = db_session.scalars(stmt).one_or_none()
    return persona.id if persona else None


def _get_persona_by_name(
    persona_name: str, user: User | None, db_session: Session
) -> Persona | None:
    """Admins can see all, regular users can only fetch their own.
    If user is None, assume the user is an admin or auth is disabled."""
    stmt = select(Persona).where(Persona.name == persona_name)
    if user and user.role != UserRole.ADMIN:
        stmt = stmt.where(Persona.user_id == user.id)
    result = db_session.execute(stmt).scalar_one_or_none()
    return result


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
        raise NotImplementedError("Onyx MIT does not support private Personas")


def create_update_persona(
    persona_id: int | None,
    create_persona_request: CreatePersonaRequest,
    user: User | None,
    db_session: Session,
) -> PersonaSnapshot:
    """Higher level function than upsert_persona, although either is valid to use."""
    # Permission to actually use these is checked later

    try:
        persona_data = {
            "persona_id": persona_id,
            "user": user,
            "db_session": db_session,
            **create_persona_request.model_dump(exclude={"users", "groups"}),
        }

        persona = upsert_persona(**persona_data)

        versioned_make_persona_private = fetch_versioned_implementation(
            "onyx.db.persona", "make_persona_private"
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
    persona = fetch_persona_by_id(
        db_session=db_session, persona_id=persona_id, user=user, get_editable=True
    )

    if persona.is_public:
        raise HTTPException(status_code=400, detail="Cannot share public persona")

    versioned_make_persona_private = fetch_versioned_implementation(
        "onyx.db.persona", "make_persona_private"
    )

    # Privatize Persona
    versioned_make_persona_private(
        persona_id=persona_id,
        user_ids=user_ids,
        group_ids=None,
        db_session=db_session,
    )


def update_persona_public_status(
    persona_id: int,
    is_public: bool,
    db_session: Session,
    user: User | None,
) -> None:
    persona = fetch_persona_by_id(
        db_session=db_session, persona_id=persona_id, user=user, get_editable=True
    )
    if user and user.role != UserRole.ADMIN and persona.user_id != user.id:
        raise ValueError("You don't have permission to modify this persona")

    persona.is_public = is_public
    db_session.commit()


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
    # if user is `None` assume the user is an admin or auth is disabled
    user: User | None,
    db_session: Session,
    get_editable: bool = True,
    include_default: bool = True,
    include_slack_bot_personas: bool = False,
    include_deleted: bool = False,
    joinedload_all: bool = False,
) -> Sequence[Persona]:
    stmt = select(Persona).distinct()
    stmt = _add_user_filters(stmt=stmt, user=user, get_editable=get_editable)
    if not include_default:
        stmt = stmt.where(Persona.builtin_persona.is_(False))
    if not include_slack_bot_personas:
        stmt = stmt.where(not_(Persona.name.startswith(SLACK_BOT_PERSONA_PREFIX)))
    if not include_deleted:
        stmt = stmt.where(Persona.deleted.is_(False))

    if joinedload_all:
        stmt = stmt.options(
            joinedload(Persona.prompts),
            joinedload(Persona.tools),
            joinedload(Persona.document_sets),
            joinedload(Persona.groups),
            joinedload(Persona.users),
        )

    return db_session.execute(stmt).unique().scalars().all()


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
        .where(Persona.name == persona_name, Persona.builtin_persona == is_default)
        .values(deleted=True)
    )

    db_session.execute(stmt)
    db_session.commit()


def update_all_personas_display_priority(
    display_priority_map: dict[int, int],
    db_session: Session,
) -> None:
    """Updates the display priority of all lives Personas"""
    personas = get_personas(user=None, db_session=db_session)
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
    commit: bool = True,
    icon_color: str | None = None,
    icon_shape: int | None = None,
    uploaded_image_id: str | None = None,
    display_priority: int | None = None,
    is_visible: bool = True,
    remove_image: bool | None = None,
    search_start_date: datetime | None = None,
    builtin_persona: bool = False,
    is_default_persona: bool = False,
    category_id: int | None = None,
    chunks_above: int = CONTEXT_CHUNKS_ABOVE,
    chunks_below: int = CONTEXT_CHUNKS_BELOW,
) -> Persona:
    """
    NOTE: This operation cannot update persona configuration options that
    are core to the persona, such as its display priority and
    whether or not the assistant is a built-in / default assistant
    """

    if persona_id is not None:
        existing_persona = db_session.query(Persona).filter_by(id=persona_id).first()
    else:
        existing_persona = _get_persona_by_name(
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

    if prompts is not None and len(prompts) == 0:
        raise ValueError(
            f"Invalid Persona config, no valid prompts "
            f"specified. Specified IDs were: '{prompt_ids}'"
        )

    # ensure all specified tools are valid
    if tools:
        validate_persona_tools(tools)

    if existing_persona:
        # Built-in personas can only be updated through YAML configuration.
        # This ensures that core system personas are not modified unintentionally.
        if existing_persona.builtin_persona and not builtin_persona:
            raise ValueError("Cannot update builtin persona with non-builtin.")

        # this checks if the user has permission to edit the persona
        # will raise an Exception if the user does not have permission
        existing_persona = fetch_persona_by_id(
            db_session=db_session,
            persona_id=existing_persona.id,
            user=user,
            get_editable=True,
        )

        # The following update excludes `default`, `built-in`, and display priority.
        # Display priority is handled separately in the `display-priority` endpoint.
        # `default` and `built-in` properties can only be set when creating a persona.
        existing_persona.name = name
        existing_persona.description = description
        existing_persona.num_chunks = num_chunks
        existing_persona.chunks_above = chunks_above
        existing_persona.chunks_below = chunks_below
        existing_persona.llm_relevance_filter = llm_relevance_filter
        existing_persona.llm_filter_extraction = llm_filter_extraction
        existing_persona.recency_bias = recency_bias
        existing_persona.llm_model_provider_override = llm_model_provider_override
        existing_persona.llm_model_version_override = llm_model_version_override
        existing_persona.starter_messages = starter_messages
        existing_persona.deleted = False  # Un-delete if previously deleted
        existing_persona.is_public = is_public
        existing_persona.icon_color = icon_color
        existing_persona.icon_shape = icon_shape
        if remove_image or uploaded_image_id:
            existing_persona.uploaded_image_id = uploaded_image_id
        existing_persona.is_visible = is_visible
        existing_persona.search_start_date = search_start_date
        existing_persona.category_id = category_id
        # Do not delete any associations manually added unless
        # a new updated list is provided
        if document_sets is not None:
            existing_persona.document_sets.clear()
            existing_persona.document_sets = document_sets or []

        if prompts is not None:
            existing_persona.prompts.clear()
            existing_persona.prompts = prompts

        if tools is not None:
            existing_persona.tools = tools or []

        # We should only update display priority if it is not already set
        if existing_persona.display_priority is None:
            existing_persona.display_priority = display_priority

        persona = existing_persona

    else:
        if not prompts:
            raise ValueError(
                "Invalid Persona config. "
                "Must specify at least one prompt for a new persona."
            )

        new_persona = Persona(
            id=persona_id,
            user_id=user.id if user else None,
            is_public=is_public,
            name=name,
            description=description,
            num_chunks=num_chunks,
            chunks_above=chunks_above,
            chunks_below=chunks_below,
            llm_relevance_filter=llm_relevance_filter,
            llm_filter_extraction=llm_filter_extraction,
            recency_bias=recency_bias,
            builtin_persona=builtin_persona,
            prompts=prompts,
            document_sets=document_sets or [],
            llm_model_provider_override=llm_model_provider_override,
            llm_model_version_override=llm_model_version_override,
            starter_messages=starter_messages,
            tools=tools or [],
            icon_shape=icon_shape,
            icon_color=icon_color,
            uploaded_image_id=uploaded_image_id,
            display_priority=display_priority,
            is_visible=is_visible,
            search_start_date=search_start_date,
            is_default_persona=is_default_persona,
            category_id=category_id,
        )
        db_session.add(new_persona)
        persona = new_persona
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
        .where(Persona.builtin_persona, Persona.id > 0)
        .values(deleted=True, name=func.concat(Persona.name, "_old"))
    )

    db_session.execute(stmt)
    db_session.commit()


def update_persona_visibility(
    persona_id: int,
    is_visible: bool,
    db_session: Session,
    user: User | None = None,
) -> None:
    persona = fetch_persona_by_id(
        db_session=db_session, persona_id=persona_id, user=user, get_editable=True
    )

    persona.is_visible = is_visible
    db_session.commit()


def validate_persona_tools(tools: list[Tool]) -> None:
    for tool in tools:
        if tool.name == "InternetSearchTool" and not BING_API_KEY:
            raise ValueError(
                "Bing API key not found, please contact your Onyx admin to get it added!"
            )


def get_prompts_by_ids(prompt_ids: list[int], db_session: Session) -> list[Prompt]:
    """Unsafe, can fetch prompts from all users"""
    if not prompt_ids:
        return []
    prompts = db_session.scalars(
        select(Prompt).where(Prompt.id.in_(prompt_ids)).where(Prompt.deleted.is_(False))
    ).all()

    return list(prompts)


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


# TODO: since this gets called with every chat message, could it be more efficient to pregenerate
# a direct mapping indicating whether a user has access to a specific persona?
def get_persona_by_id(
    persona_id: int,
    # if user is `None` assume the user is an admin or auth is disabled
    user: User | None,
    db_session: Session,
    include_deleted: bool = False,
    is_for_edit: bool = True,  # NOTE: assume true for safety
) -> Persona:
    persona_stmt = (
        select(Persona)
        .distinct()
        .outerjoin(Persona.groups)
        .outerjoin(Persona.users)
        .outerjoin(UserGroup.user_group_relationships)
        .where(Persona.id == persona_id)
    )

    if not include_deleted:
        persona_stmt = persona_stmt.where(Persona.deleted.is_(False))

    if not user or user.role == UserRole.ADMIN:
        result = db_session.execute(persona_stmt)
        persona = result.scalar_one_or_none()
        if persona is None:
            raise ValueError(f"Persona with ID {persona_id} does not exist")
        return persona

    # or check if user owns persona
    or_conditions = Persona.user_id == user.id
    # allow access if persona user id is None
    or_conditions |= Persona.user_id == None  # noqa: E711
    if not is_for_edit:
        # if the user is in a group related to the persona
        or_conditions |= User__UserGroup.user_id == user.id
        # if the user is in the .users of the persona
        or_conditions |= User.id == user.id
        or_conditions |= Persona.is_public == True  # noqa: E712
    elif user.role == UserRole.GLOBAL_CURATOR:
        # global curators can edit personas for the groups they are in
        or_conditions |= User__UserGroup.user_id == user.id
    elif user.role == UserRole.CURATOR:
        # curators can edit personas for the groups they are curators of
        or_conditions |= (User__UserGroup.user_id == user.id) & (
            User__UserGroup.is_curator == True  # noqa: E712
        )

    persona_stmt = persona_stmt.where(or_conditions)
    result = db_session.execute(persona_stmt)
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

    # Order by ID to ensure consistent result when multiple prompts exist
    stmt = stmt.order_by(Prompt.id).limit(1)
    result = db_session.execute(stmt).scalar_one_or_none()
    return result


def delete_persona_by_name(
    persona_name: str, db_session: Session, is_default: bool = True
) -> None:
    stmt = delete(Persona).where(
        Persona.name == persona_name, Persona.builtin_persona == is_default
    )

    db_session.execute(stmt)
    db_session.commit()


def get_assistant_categories(db_session: Session) -> list[PersonaCategory]:
    return db_session.query(PersonaCategory).all()


def create_assistant_category(
    db_session: Session, name: str, description: str
) -> PersonaCategory:
    category = PersonaCategory(name=name, description=description)
    db_session.add(category)
    db_session.commit()
    return category


def update_persona_category(
    category_id: int,
    category_description: str,
    category_name: str,
    db_session: Session,
) -> None:
    persona_category = (
        db_session.query(PersonaCategory)
        .filter(PersonaCategory.id == category_id)
        .one_or_none()
    )
    if persona_category is None:
        raise ValueError(f"Persona category with ID {category_id} does not exist")
    persona_category.description = category_description
    persona_category.name = category_name
    db_session.commit()


def delete_persona_category(category_id: int, db_session: Session) -> None:
    db_session.query(PersonaCategory).filter(PersonaCategory.id == category_id).delete()
    db_session.commit()
