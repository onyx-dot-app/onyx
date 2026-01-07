from collections.abc import Sequence
from datetime import datetime
from enum import Enum
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import not_
from sqlalchemy import or_
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import aliased
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.configs.app_configs import CURATORS_CANNOT_VIEW_OR_EDIT_NON_OWNED_ASSISTANTS
from onyx.configs.app_configs import DISABLE_AUTH
from onyx.configs.chat_configs import CONTEXT_CHUNKS_ABOVE
from onyx.configs.chat_configs import CONTEXT_CHUNKS_BELOW
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.configs.constants import NotificationType
from onyx.context.search.enums import RecencyBiasSetting
from onyx.db.constants import SLACK_BOT_PERSONA_PREFIX
from onyx.db.models import DocumentSet
from onyx.db.models import Persona
from onyx.db.models import Persona__User
from onyx.db.models import Persona__UserGroup
from onyx.db.models import PersonaLabel
from onyx.db.models import StarterMessage
from onyx.db.models import Tool
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserFile
from onyx.db.models import UserGroup
from onyx.db.notification import create_notification
from onyx.server.features.persona.models import FullPersonaSnapshot
from onyx.server.features.persona.models import MinimalPersonaSnapshot
from onyx.server.features.persona.models import PersonaSharedNotificationData
from onyx.server.features.persona.models import PersonaSnapshot
from onyx.server.features.persona.models import PersonaUpsertRequest
from onyx.server.features.tool.tool_visibility import should_expose_tool_to_fe
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_versioned_implementation

logger = setup_logger()


def get_default_behavior_persona(db_session: Session) -> Persona | None:
    stmt = select(Persona).where(Persona.id == DEFAULT_PERSONA_ID)
    return db_session.scalars(stmt).first()


class PersonaLoadType(Enum):
    NONE = "none"
    MINIMAL = "minimal"
    FULL = "full"


def _add_user_filters(
    stmt: Select[tuple[Persona]], user: User | None, get_editable: bool = True
) -> Select[tuple[Persona]]:
    # If user is None and auth is disabled, assume the user is an admin
    if (user is None and DISABLE_AUTH) or (user and user.role == UserRole.ADMIN):
        return stmt

    stmt = stmt.distinct()
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

    # If user is None, this is an anonymous user and we should only show public Personas
    if user is None:
        where_clause = Persona.is_public == True  # noqa: E712
        return stmt.where(where_clause)

    # If curator ownership restriction is enabled, curators can only access their own assistants
    if CURATORS_CANNOT_VIEW_OR_EDIT_NON_OWNED_ASSISTANTS and user.role in [
        UserRole.CURATOR,
        UserRole.GLOBAL_CURATOR,
    ]:
        where_clause = (Persona.user_id == user.id) | (Persona.user_id.is_(None))
        return stmt.where(where_clause)

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
        # Group the public persona conditions
        public_condition = (Persona.is_public == True) & (  # noqa: E712
            Persona.is_visible == True  # noqa: E712
        )

        where_clause |= public_condition
        where_clause |= Persona__User.user_id == user.id

    where_clause |= Persona.user_id == user.id

    return stmt.where(where_clause)


def fetch_persona_by_id_for_user(
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
    creator_user_id: UUID | None,
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
            if user_uuid != creator_user_id:
                create_notification(
                    user_id=user_uuid,
                    notif_type=NotificationType.PERSONA_SHARED,
                    title="A new agent was shared with you!",
                    db_session=db_session,
                    additional_data=PersonaSharedNotificationData(
                        persona_id=persona_id,
                    ).model_dump(),
                )

        db_session.commit()

    # May cause error if someone switches down to MIT from EE
    if group_ids:
        raise NotImplementedError("Onyx MIT does not support private Personas")


def create_update_persona(
    persona_id: int | None,
    create_persona_request: PersonaUpsertRequest,
    user: User | None,
    db_session: Session,
) -> FullPersonaSnapshot:
    """Higher level function than upsert_persona, although either is valid to use."""
    # Permission to actually use these is checked later

    try:
        # Default persona validation
        if create_persona_request.is_default_persona:
            if not create_persona_request.is_public:
                raise ValueError("Cannot make a default persona non public")

            if user:
                # Curators can edit default personas, but not make them
                if (
                    user.role == UserRole.CURATOR
                    or user.role == UserRole.GLOBAL_CURATOR
                ):
                    pass
                elif user.role != UserRole.ADMIN:
                    raise ValueError("Only admins can make a default persona")

        # Convert incoming string UUIDs to UUID objects for DB operations
        converted_user_file_ids = None
        if create_persona_request.user_file_ids is not None:
            try:
                converted_user_file_ids = [
                    UUID(str_id) for str_id in create_persona_request.user_file_ids
                ]
            except Exception:
                raise ValueError("Invalid user_file_ids; must be UUID strings")

        persona = upsert_persona(
            persona_id=persona_id,
            user=user,
            db_session=db_session,
            description=create_persona_request.description,
            name=create_persona_request.name,
            document_set_ids=create_persona_request.document_set_ids,
            tool_ids=create_persona_request.tool_ids,
            is_public=create_persona_request.is_public,
            recency_bias=create_persona_request.recency_bias,
            llm_model_provider_override=create_persona_request.llm_model_provider_override,
            llm_model_version_override=create_persona_request.llm_model_version_override,
            starter_messages=create_persona_request.starter_messages,
            system_prompt=create_persona_request.system_prompt,
            task_prompt=create_persona_request.task_prompt,
            datetime_aware=create_persona_request.datetime_aware,
            replace_base_system_prompt=create_persona_request.replace_base_system_prompt,
            uploaded_image_id=create_persona_request.uploaded_image_id,
            icon_name=create_persona_request.icon_name,
            display_priority=create_persona_request.display_priority,
            remove_image=create_persona_request.remove_image,
            search_start_date=create_persona_request.search_start_date,
            label_ids=create_persona_request.label_ids,
            num_chunks=create_persona_request.num_chunks,
            llm_relevance_filter=create_persona_request.llm_relevance_filter,
            llm_filter_extraction=create_persona_request.llm_filter_extraction,
            is_default_persona=create_persona_request.is_default_persona,
            user_file_ids=converted_user_file_ids,
        )

        versioned_make_persona_private = fetch_versioned_implementation(
            "onyx.db.persona", "make_persona_private"
        )

        # Privatize Persona
        versioned_make_persona_private(
            persona_id=persona.id,
            creator_user_id=user.id if user else None,
            user_ids=create_persona_request.users,
            group_ids=create_persona_request.groups,
            db_session=db_session,
        )

    except ValueError as e:
        logger.exception("Failed to create persona")
        raise HTTPException(status_code=400, detail=str(e))

    return FullPersonaSnapshot.from_model(persona)


def update_persona_shared_users(
    persona_id: int,
    user_ids: list[UUID],
    user: User | None,
    db_session: Session,
) -> None:
    """Simplified version of `create_update_persona` which only touches the
    accessibility rather than any of the logic (e.g. prompt, connected data sources,
    etc.)."""
    persona = fetch_persona_by_id_for_user(
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
        creator_user_id=user.id if user else None,
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
    persona = fetch_persona_by_id_for_user(
        db_session=db_session, persona_id=persona_id, user=user, get_editable=True
    )
    if user and user.role != UserRole.ADMIN and persona.user_id != user.id:
        raise ValueError("You don't have permission to modify this persona")

    persona.is_public = is_public
    db_session.commit()


def _build_persona_filters(
    stmt: Select[tuple[Persona]],
    include_default: bool,
    include_slack_bot_personas: bool,
    include_deleted: bool,
) -> Select[tuple[Persona]]:
    """Filters which Personas are included in the query.

    Args:
        stmt: The base query to filter.
        include_default: If True, includes builtin/default personas.
        include_slack_bot_personas: If True, includes Slack bot personas.
        include_deleted: If True, includes deleted personas.

    Returns:
        The modified query with the filters applied.
    """
    if not include_default:
        stmt = stmt.where(Persona.builtin_persona.is_(False))
    if not include_slack_bot_personas:
        stmt = stmt.where(not_(Persona.name.startswith(SLACK_BOT_PERSONA_PREFIX)))
    if not include_deleted:
        stmt = stmt.where(Persona.deleted.is_(False))
    return stmt


def get_minimal_persona_snapshots_for_user(
    user: User | None,
    db_session: Session,
    get_editable: bool = True,
    include_default: bool = True,
    include_slack_bot_personas: bool = False,
    include_deleted: bool = False,
) -> list[MinimalPersonaSnapshot]:
    stmt = select(Persona)
    stmt = _add_user_filters(stmt, user, get_editable)
    stmt = _build_persona_filters(
        stmt, include_default, include_slack_bot_personas, include_deleted
    )
    stmt = stmt.options(
        selectinload(Persona.tools),
        selectinload(Persona.labels),
        selectinload(Persona.document_sets),
        selectinload(Persona.user),
    )
    results = db_session.scalars(stmt).all()
    return [MinimalPersonaSnapshot.from_model(persona) for persona in results]


def get_persona_snapshots_for_user(
    # if user is `None` assume the user is an admin or auth is disabled
    user: User | None,
    db_session: Session,
    get_editable: bool = True,
    include_default: bool = True,
    include_slack_bot_personas: bool = False,
    include_deleted: bool = False,
) -> list[PersonaSnapshot]:
    stmt = select(Persona)
    stmt = _add_user_filters(stmt, user, get_editable)
    stmt = _build_persona_filters(
        stmt, include_default, include_slack_bot_personas, include_deleted
    )
    stmt = stmt.options(
        selectinload(Persona.tools),
        selectinload(Persona.labels),
        selectinload(Persona.document_sets),
        selectinload(Persona.user),
        selectinload(Persona.user_files),
        selectinload(Persona.users),
        selectinload(Persona.groups),
    )

    results = db_session.scalars(stmt).all()
    return [PersonaSnapshot.from_model(persona) for persona in results]


def get_persona_count_for_user(
    user: User | None,
    db_session: Session,
    get_editable: bool = True,
    include_default: bool = True,
    include_slack_bot_personas: bool = False,
    include_deleted: bool = False,
) -> int:
    """Counts the total number of personas accessible to the user.

    Args:
        user: The user to filter personas for. If None and auth is disabled,
            assumes the user is an admin. Otherwise, if None shows only public
            personas.
        db_session: Database session for executing queries.
        get_editable: If True, only returns personas the user can edit.
        include_default: If True, includes builtin/default personas.
        include_slack_bot_personas: If True, includes Slack bot personas.
        include_deleted: If True, includes deleted personas.

    Returns:
        Total count of personas matching the filters and user permissions.
    """
    stmt = _build_persona_base_query(
        user=user,
        get_editable=get_editable,
        include_default=include_default,
        include_slack_bot_personas=include_slack_bot_personas,
        include_deleted=include_deleted,
    )
    # Convert to count query.
    count_stmt = stmt.with_only_columns(func.count(func.distinct(Persona.id))).order_by(
        None
    )
    return db_session.scalar(count_stmt) or 0


def get_minimal_persona_snapshots_paginated(
    user: User | None,
    db_session: Session,
    page_num: int,
    page_size: int,
    get_editable: bool = True,
    include_default: bool = True,
    include_slack_bot_personas: bool = False,
    include_deleted: bool = False,
) -> list[MinimalPersonaSnapshot]:
    """Gets a single page of minimal persona snapshots with ordering.

    Personas are ordered by display_priority (ASC, nulls last) then by ID (ASC
    distance from 0).

    Args:
        user: The user to filter personas for. If None and auth is disabled,
            assumes the user is an admin. Otherwise, if None shows only public
            personas.
        db_session: Database session for executing queries.
        page_num: Zero-indexed page number (e.g., 0 for the first page).
        page_size: Number of items per page.
        get_editable: If True, only returns personas the user can edit.
        include_default: If True, includes builtin/default personas.
        include_slack_bot_personas: If True, includes Slack bot personas.
        include_deleted: If True, includes deleted personas.

    Returns:
        List of MinimalPersonaSnapshot objects for the requested page, ordered
        by display_priority (nulls last) then ID.
    """
    stmt = _get_paginated_persona_query(
        user,
        page_num,
        page_size,
        get_editable,
        include_default,
        include_slack_bot_personas,
        include_deleted,
    )
    # Do eager loading of columns we know MinimalPersonaSnapshot.from_model will
    # need.
    stmt = stmt.options(
        selectinload(Persona.tools),
        selectinload(Persona.labels),
        selectinload(Persona.document_sets),
        selectinload(Persona.user),
    )

    results = db_session.scalars(stmt).all()
    return [MinimalPersonaSnapshot.from_model(persona) for persona in results]


def get_persona_snapshots_paginated(
    user: User | None,
    db_session: Session,
    page_num: int,
    page_size: int,
    get_editable: bool = True,
    include_default: bool = True,
    include_slack_bot_personas: bool = False,
    include_deleted: bool = False,
) -> list[PersonaSnapshot]:
    """Gets a single page of persona snapshots (admin view) with ordering.

    Personas are ordered by display_priority (ASC, nulls last) then by ID (ASC
    distance from 0).

    This function returns PersonaSnapshot objects which contain more detailed
    information than MinimalPersonaSnapshot, used for admin views.

    Args:
        user: The user to filter personas for. If None and auth is disabled,
            assumes the user is an admin. Otherwise, if None shows only public
            personas.
        db_session: Database session for executing queries.
        page_num: Zero-indexed page number (e.g., 0 for the first page).
        page_size: Number of items per page.
        get_editable: If True, only returns personas the user can edit.
        include_default: If True, includes builtin/default personas.
        include_slack_bot_personas: If True, includes Slack bot personas.
        include_deleted: If True, includes deleted personas.

    Returns:
        List of PersonaSnapshot objects for the requested page, ordered by
        display_priority (nulls last) then ID.
    """
    stmt = _get_paginated_persona_query(
        user,
        page_num,
        page_size,
        get_editable,
        include_default,
        include_slack_bot_personas,
        include_deleted,
    )
    # Do eager loading of columns we know PersonaSnapshot.from_model will need.
    stmt = stmt.options(
        selectinload(Persona.tools),
        selectinload(Persona.labels),
        selectinload(Persona.document_sets),
        selectinload(Persona.user),
        selectinload(Persona.user_files),
        selectinload(Persona.users),
        selectinload(Persona.groups),
    )

    results = db_session.scalars(stmt).all()
    return [PersonaSnapshot.from_model(persona) for persona in results]


def _get_paginated_persona_query(
    user: User | None,
    page_num: int,
    page_size: int,
    get_editable: bool = True,
    include_default: bool = True,
    include_slack_bot_personas: bool = False,
    include_deleted: bool = False,
) -> Select[tuple[Persona]]:
    """Builds a paginated query on personas ordered on display_priority and id.

    Personas are ordered by display_priority (ASC, nulls last) then by ID (ASC
    distance from 0) to match the frontend personaComparator() logic.

    Args:
        user: The user to filter personas for. If None and auth is disabled,
            assumes the user is an admin. Otherwise, if None shows only public
            personas.
        page_num: Zero-indexed page number (e.g., 0 for the first page).
        page_size: Number of items per page.
        get_editable: If True, only returns personas the user can edit.
        include_default: If True, includes builtin/default personas.
        include_slack_bot_personas: If True, includes Slack bot personas.
        include_deleted: If True, includes deleted personas.

    Returns:
        SQLAlchemy Select statement with all filters, ordering, and pagination
        applied.
    """
    stmt = _build_persona_base_query(
        user=user,
        get_editable=get_editable,
        include_default=include_default,
        include_slack_bot_personas=include_slack_bot_personas,
        include_deleted=include_deleted,
    )
    # Add the abs(id) expression to the SELECT list (required for DISTINCT +
    # ORDER BY).
    stmt = stmt.add_columns(func.abs(Persona.id).label("abs_id"))
    # Apply ordering.
    stmt = stmt.order_by(
        Persona.display_priority.asc().nullslast(),
        func.abs(Persona.id).asc(),
    )
    # Apply pagination.
    stmt = stmt.offset(page_num * page_size).limit(page_size)
    return stmt


def _build_persona_base_query(
    user: User | None,
    get_editable: bool = True,
    include_default: bool = True,
    include_slack_bot_personas: bool = False,
    include_deleted: bool = False,
) -> Select[tuple[Persona]]:
    """Builds a base persona query with all user and persona filters applied.

    This helper constructs a filtered query that can then be customized for
    counting, pagination, or full retrieval.

    Args:
        user: The user to filter personas for. If None and auth is disabled,
            assumes the user is an admin. Otherwise, if None shows only public
            personas.
        get_editable: If True, only returns personas the user can edit.
        include_default: If True, includes builtin/default personas.
        include_slack_bot_personas: If True, includes Slack bot personas.
        include_deleted: If True, includes deleted personas.

    Returns:
        SQLAlchemy Select statement with all filters applied.
    """
    stmt = select(Persona)
    stmt = _add_user_filters(stmt, user, get_editable)
    stmt = _build_persona_filters(
        stmt, include_default, include_slack_bot_personas, include_deleted
    )
    return stmt


def get_raw_personas_for_user(
    user: User | None,
    db_session: Session,
    get_editable: bool = True,
    include_default: bool = True,
    include_slack_bot_personas: bool = False,
    include_deleted: bool = False,
) -> Sequence[Persona]:
    stmt = _build_persona_base_query(
        user, get_editable, include_default, include_slack_bot_personas, include_deleted
    )
    return db_session.scalars(stmt).all()


def get_personas(db_session: Session) -> Sequence[Persona]:
    """WARNING: Unsafe, can fetch personas from all users."""
    stmt = select(Persona).distinct()
    stmt = stmt.where(not_(Persona.name.startswith(SLACK_BOT_PERSONA_PREFIX)))
    stmt = stmt.where(Persona.deleted.is_(False))
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


def update_personas_display_priority(
    display_priority_map: dict[int, int],
    db_session: Session,
    user: User | None,
    commit_db_txn: bool = False,
) -> None:
    """Updates the display priorities of the specified Personas.

    Args:
        display_priority_map: A map of persona IDs to intended display
            priorities.
        db_session: Database session for executing queries.
        user: The user to filter personas for. If None and auth is disabled,
            assumes the user is an admin. Otherwise, if None shows only public
            personas.
        commit_db_txn: If True, commits the database transaction after
            updating the display priorities. Defaults to False.

    Raises:
        ValueError: The caller tried to update a persona for which the user does
            not have access.
    """
    # No-op to save a query if it is not necessary.
    if len(display_priority_map) == 0:
        return

    personas = get_raw_personas_for_user(
        user,
        db_session,
        get_editable=False,
        include_default=True,
        include_slack_bot_personas=True,
        include_deleted=True,
    )
    available_personas_map: dict[int, Persona] = {
        persona.id: persona for persona in personas
    }

    for persona_id, priority in display_priority_map.items():
        if persona_id not in available_personas_map:
            raise ValueError(
                f"Invalid persona ID provided: Persona with ID {persona_id} was not found for this user."
            )

        available_personas_map[persona_id].display_priority = priority

    if commit_db_txn:
        db_session.commit()


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
    # Embedded prompt fields
    system_prompt: str | None,
    task_prompt: str | None,
    datetime_aware: bool | None,
    is_public: bool,
    db_session: Session,
    document_set_ids: list[int] | None = None,
    tool_ids: list[int] | None = None,
    persona_id: int | None = None,
    commit: bool = True,
    uploaded_image_id: str | None = None,
    icon_name: str | None = None,
    display_priority: int | None = None,
    is_visible: bool = True,
    remove_image: bool | None = None,
    search_start_date: datetime | None = None,
    builtin_persona: bool = False,
    is_default_persona: bool | None = None,
    label_ids: list[int] | None = None,
    user_file_ids: list[UUID] | None = None,
    chunks_above: int = CONTEXT_CHUNKS_ABOVE,
    chunks_below: int = CONTEXT_CHUNKS_BELOW,
    replace_base_system_prompt: bool = False,
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

        # Check for duplicate names when creating new personas
        # Deleted personas are allowed to be overwritten
        if existing_persona and not existing_persona.deleted:
            raise ValueError(
                f"Assistant with name '{name}' already exists. Please rename your assistant."
            )

    if existing_persona:
        # this checks if the user has permission to edit the persona
        # will raise an Exception if the user does not have permission
        existing_persona = fetch_persona_by_id_for_user(
            db_session=db_session,
            persona_id=existing_persona.id,
            user=user,
            get_editable=True,
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

    # Fetch and attach user_files by IDs
    user_files = None
    if user_file_ids is not None:
        user_files = (
            db_session.query(UserFile).filter(UserFile.id.in_(user_file_ids)).all()
        )
        if not user_files and user_file_ids:
            raise ValueError("user_files not found")

    labels = None
    if label_ids is not None:
        labels = (
            db_session.query(PersonaLabel).filter(PersonaLabel.id.in_(label_ids)).all()
        )

    # ensure all specified tools are valid
    if tools:
        validate_persona_tools(tools, db_session)

    if existing_persona:
        # Built-in personas can only be updated through YAML configuration.
        # This ensures that core system personas are not modified unintentionally.
        if existing_persona.builtin_persona and not builtin_persona:
            raise ValueError("Cannot update builtin persona with non-builtin.")

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
        if remove_image or uploaded_image_id:
            existing_persona.uploaded_image_id = uploaded_image_id
        existing_persona.icon_name = icon_name
        existing_persona.is_visible = is_visible
        existing_persona.search_start_date = search_start_date
        existing_persona.labels = labels or []
        existing_persona.is_default_persona = (
            is_default_persona
            if is_default_persona is not None
            else existing_persona.is_default_persona
        )
        # Update embedded prompt fields if provided
        if system_prompt is not None:
            existing_persona.system_prompt = system_prompt
        if task_prompt is not None:
            existing_persona.task_prompt = task_prompt
        if datetime_aware is not None:
            existing_persona.datetime_aware = datetime_aware
        existing_persona.replace_base_system_prompt = replace_base_system_prompt

        # Do not delete any associations manually added unless
        # a new updated list is provided
        if document_sets is not None:
            existing_persona.document_sets.clear()
            existing_persona.document_sets = document_sets or []

        # Note: prompts are now embedded in personas - no separate prompts relationship

        if tools is not None:
            existing_persona.tools = tools or []

        if user_file_ids is not None:
            existing_persona.user_files.clear()
            existing_persona.user_files = user_files or []

        # We should only update display priority if it is not already set
        if existing_persona.display_priority is None:
            existing_persona.display_priority = display_priority

        persona = existing_persona

    else:
        # Create new persona - prompt configuration will be set separately if needed
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
            system_prompt=system_prompt or "",
            task_prompt=task_prompt or "",
            datetime_aware=(datetime_aware if datetime_aware is not None else True),
            replace_base_system_prompt=replace_base_system_prompt,
            document_sets=document_sets or [],
            llm_model_provider_override=llm_model_provider_override,
            llm_model_version_override=llm_model_version_override,
            starter_messages=starter_messages,
            tools=tools or [],
            uploaded_image_id=uploaded_image_id,
            icon_name=icon_name,
            display_priority=display_priority,
            is_visible=is_visible,
            search_start_date=search_start_date,
            is_default_persona=(
                is_default_persona if is_default_persona is not None else False
            ),
            user_files=user_files or [],
            labels=labels or [],
        )
        db_session.add(new_persona)
        persona = new_persona
    if commit:
        db_session.commit()
    else:
        # flush the session so that the persona has an ID
        db_session.flush()

    return persona


def delete_old_default_personas(
    db_session: Session,
) -> None:
    """Note, this locks out the Summarize and Paraphrase personas for now
    Need a more graceful fix later or those need to never have IDs.

    This function is idempotent, so it can be run multiple times without issue.
    """
    OLD_SUFFIX = "_old"
    stmt = (
        update(Persona)
        .where(
            Persona.builtin_persona,
            Persona.id > 0,
            or_(
                Persona.deleted.is_(False),
                not_(Persona.name.endswith(OLD_SUFFIX)),
            ),
        )
        .values(deleted=True, name=func.concat(Persona.name, OLD_SUFFIX))
    )

    db_session.execute(stmt)
    db_session.commit()


def update_persona_is_default(
    persona_id: int,
    is_default: bool,
    db_session: Session,
    user: User | None = None,
) -> None:
    persona = fetch_persona_by_id_for_user(
        db_session=db_session, persona_id=persona_id, user=user, get_editable=True
    )

    if not persona.is_public:
        persona.is_public = True

    persona.is_default_persona = is_default
    db_session.commit()


def update_persona_visibility(
    persona_id: int,
    is_visible: bool,
    db_session: Session,
    user: User | None = None,
) -> None:
    persona = fetch_persona_by_id_for_user(
        db_session=db_session, persona_id=persona_id, user=user, get_editable=True
    )

    persona.is_visible = is_visible
    db_session.commit()


def validate_persona_tools(tools: list[Tool], db_session: Session) -> None:
    # local import to avoid circular import. DB layer should not depend on tools layer.
    from onyx.tools.built_in_tools import get_built_in_tool_by_id

    for tool in tools:
        if tool.in_code_tool_id is not None:
            tool_cls = get_built_in_tool_by_id(tool.in_code_tool_id)
            if not tool_cls.is_available(db_session):
                raise ValueError(f"Tool {tool.in_code_tool_id} is not available")


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
    """WARNING: Unsafe, can fetch personas from all users."""
    if not persona_ids:
        return []
    personas = db_session.scalars(
        select(Persona).where(Persona.id.in_(persona_ids))
    ).all()

    return personas


def delete_persona_by_name(
    persona_name: str, db_session: Session, is_default: bool = True
) -> None:
    stmt = (
        update(Persona)
        .where(Persona.name == persona_name, Persona.builtin_persona == is_default)
        .values(deleted=True)
    )

    db_session.execute(stmt)
    db_session.commit()


def get_assistant_labels(db_session: Session) -> list[PersonaLabel]:
    return db_session.query(PersonaLabel).all()


def create_assistant_label(db_session: Session, name: str) -> PersonaLabel:
    label = PersonaLabel(name=name)
    db_session.add(label)
    db_session.commit()
    return label


def update_persona_label(
    label_id: int,
    label_name: str,
    db_session: Session,
) -> None:
    persona_label = (
        db_session.query(PersonaLabel).filter(PersonaLabel.id == label_id).one_or_none()
    )
    if persona_label is None:
        raise ValueError(f"Persona label with ID {label_id} does not exist")
    persona_label.name = label_name
    db_session.commit()


def delete_persona_label(label_id: int, db_session: Session) -> None:
    db_session.query(PersonaLabel).filter(PersonaLabel.id == label_id).delete()
    db_session.commit()


def persona_has_search_tool(persona_id: int, db_session: Session) -> bool:
    persona = (
        db_session.query(Persona)
        .options(selectinload(Persona.tools))
        .filter(Persona.id == persona_id)
        .one_or_none()
    )
    if persona is None:
        raise ValueError(f"Persona with ID {persona_id} does not exist")
    return any(tool.in_code_tool_id == "run_search" for tool in persona.tools)


def get_default_assistant(db_session: Session) -> Persona | None:
    """Fetch the default assistant (persona with builtin_persona=True)."""
    return (
        db_session.query(Persona)
        .options(selectinload(Persona.tools))
        .filter(Persona.builtin_persona.is_(True))
        # NOTE: need to add this since we had prior builtin personas
        # that have since been deleted
        .filter(Persona.deleted.is_(False))
        .one_or_none()
    )


def update_default_assistant_configuration(
    db_session: Session,
    tool_ids: list[int] | None = None,
    system_prompt: str | None = None,
    update_system_prompt: bool = False,
) -> Persona:
    """Update only tools and system_prompt for the default assistant.

    Args:
        db_session: Database session
        tool_ids: List of tool IDs to enable (if None, tools are not updated)
        system_prompt: New system prompt value (None means use default)
        update_system_prompt: If True, update the system_prompt field (allows setting to None)

    Returns:
        Updated Persona object

    Raises:
        ValueError: If default assistant not found or invalid tool IDs provided
    """
    # Get the default assistant
    persona = get_default_assistant(db_session)
    if not persona:
        raise ValueError("Default assistant not found")

    # Update system prompt if explicitly requested
    if update_system_prompt:
        persona.system_prompt = system_prompt

    # Update tools if provided
    if tool_ids is not None:
        # Clear existing tool associations
        persona.tools = []

        # Add new tool associations
        for tool_id in tool_ids:
            tool = db_session.query(Tool).filter(Tool.id == tool_id).one_or_none()
            if not tool:
                raise ValueError(f"Tool with ID {tool_id} not found")

            if not should_expose_tool_to_fe(tool):
                raise ValueError(f"Tool with ID {tool_id} cannot be assigned")

            if not tool.enabled:
                raise ValueError(
                    f"Enable tool {tool.display_name or tool.name} before assigning it"
                )

            persona.tools.append(tool)

    db_session.commit()
    return persona


def user_can_access_persona(
    db_session: Session, persona_id: int, user: User | None, get_editable: bool = False
) -> bool:
    """Check if a user has access to a specific persona.

    Args:
        db_session: Database session
        persona_id: ID of the persona to check
        user: User to check access for
        get_editable: If True, check for edit access; if False, check for view access

    Returns:
        True if user can access the persona, False otherwise
    """
    stmt = select(Persona).where(Persona.id == persona_id, Persona.deleted.is_(False))
    stmt = _add_user_filters(stmt, user, get_editable=get_editable)
    return db_session.scalar(stmt) is not None
