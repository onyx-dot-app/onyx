import copy
from collections.abc import Sequence
from typing import Any, TypedDict, Unpack
from uuid import UUID

from sqlalchemy import Column, delete, desc, inspect, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.schema import ScalarElementColumnDefault

from onyx.configs.constants import ANONYMOUS_USER_UUID
from onyx.db.enums import AccountType, DefaultAppMode, ThemePreference
from onyx.db.integration_connection import delete_connections_for_user__no_commit
from onyx.db.models import (
    AccessToken,
    Assistant__UserSpecificConfig,
    Memory,
    User,
    UserPreferences,
)
from onyx.db.users import (
    assign_user_to_default_groups__no_commit,
    is_limited_user,
    release_personas_owned_by_user__no_commit,
    user_is_admin,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.models import ReasoningEffort
from onyx.server.manage.models import MemoryItem, UserSpecificAssistantPreference
from onyx.utils.logger import setup_logger

logger = setup_logger()


def deactivate_user(
    user: User,
    db_session: Session,
) -> None:
    """Deactivate a user, release the personas they own and delete their
    integration connections."""
    user.is_active = False
    release_personas_owned_by_user__no_commit(db_session, user.id)
    delete_connections_for_user__no_commit(db_session, user.id)
    db_session.add(user)
    db_session.commit()


def activate_user(
    user: User,
    db_session: Session,
) -> None:
    """Activate a user by setting is_active to True.

    Also reconciles default-group membership — the user may have been
    created while inactive or deactivated before the backfill migration.
    """
    user.is_active = True
    # That reconciliation is for STANDARD users only. A service account's groups
    # are chosen at API-key creation, and is_limited_user won't exclude one that
    # holds the derived write:chat, so reactivating a chat-only key would drop it
    # into Basic and hand it the whole basic bundle.
    # assign_user_to_default_groups__no_commit itself skips ANONYMOUS/BOT/EXT_PERM.
    if not is_limited_user(user) and user.account_type != AccountType.SERVICE_ACCOUNT:
        assign_user_to_default_groups__no_commit(
            db_session, user, is_admin=user_is_admin(user)
        )
    db_session.add(user)
    db_session.commit()


def get_latest_access_token_for_user(
    user_id: UUID,
    db_session: Session,
) -> AccessToken | None:
    """Get the most recent access token for a user."""
    try:
        result = db_session.execute(
            select(AccessToken)
            .where(AccessToken.user_id == user_id)  # ty: ignore[invalid-argument-type]
            .order_by(desc(Column("created_at")))
            .limit(1)
        )
        return result.scalar_one_or_none()
    except Exception as e:
        logger.error("Error fetching AccessToken: %s", e)
        return None


def update_users_craft_enabled(
    user_ids: list[UUID],
    craft_enabled: bool | None,
    db_session: Session,
) -> None:
    """Admin-controlled per-user Craft override; None clears the override
    (follow the workspace default)."""
    if not user_ids:
        return
    db_session.execute(
        update(User)
        .where(User.id.in_(user_ids))  # ty: ignore[unresolved-attribute]
        .values(craft_enabled=craft_enabled)
    )
    db_session.commit()


class UserPreferenceValues(TypedDict, total=False):
    """Values to save to a user's `UserPreferences` row. A missing key keeps
    the saved value; None clears a nullable column."""

    default_model: str | None
    temperature_override_enabled: bool
    temperature_default: float | None
    reasoning_effort_default: ReasoningEffort | None
    auto_scroll: bool | None
    shortcut_enabled: bool
    theme_preference: ThemePreference
    language: str | None
    chat_background: str | None
    default_app_mode: DefaultAppMode
    use_memories: bool
    enable_memory_tool: bool
    instructions: str | None
    chosen_assistants: list[int] | None
    visible_assistants: list[int]
    hidden_assistants: list[int]
    paste_as_tile: bool
    interrupt_on_send: bool
    voice_auto_send: bool
    voice_auto_playback: bool
    voice_playback_speed: float


def fetch_user_preferences(user: User, db_session: Session) -> UserPreferences:
    """The user's saved preferences. A user who has saved none gets an unsaved
    row that holds the column defaults. The shared anonymous account never
    saves preferences and never uses memories."""
    if not user.is_anonymous:
        saved = db_session.get(UserPreferences, user.id)
        if saved is not None:
            return saved
    defaults: dict[str, Any] = {
        column.key: copy.deepcopy(column.default.arg)
        for column in inspect(UserPreferences).columns
        if isinstance(column.default, ScalarElementColumnDefault)
    }
    if user.is_anonymous:
        defaults.update(use_memories=False, enable_memory_tool=False)
    return UserPreferences(user_id=user.id, **defaults)


def upsert_user_preferences__no_commit(
    db_session: Session, user_id: UUID, **values: Unpack[UserPreferenceValues]
) -> None:
    """Save the given values. The first save creates the user's row; columns
    not given get their defaults. The shared anonymous account cannot save
    preferences."""
    if user_id == UUID(ANONYMOUS_USER_UUID):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS, "Sign in to save settings."
        )
    if not values:
        return
    db_session.execute(
        pg_insert(UserPreferences)
        .values(user_id=user_id, **values)
        .on_conflict_do_update(index_elements=[UserPreferences.user_id], set_=values)
    )


def update_user_personalization(
    user_id: UUID,
    *,
    personal_name: str | None,
    personal_role: str | None,
    preferences: UserPreferenceValues,
    memories: list[MemoryItem],
    db_session: Session,
) -> None:
    db_session.execute(
        update(User)
        .where(User.id == user_id)  # ty: ignore[invalid-argument-type]
        .values(personal_name=personal_name, personal_role=personal_role)
    )
    upsert_user_preferences__no_commit(db_session, user_id, **preferences)

    # ID-based upsert: use real DB IDs from the frontend to match memories.
    incoming_ids = {m.id for m in memories if m.id is not None}

    # Delete existing rows not in the incoming set (scoped to user_id)
    existing_memories = list(
        db_session.scalars(select(Memory).where(Memory.user_id == user_id)).all()
    )
    existing_ids = {mem.id for mem in existing_memories}
    ids_to_delete = existing_ids - incoming_ids
    if ids_to_delete:
        db_session.execute(
            delete(Memory).where(
                Memory.id.in_(ids_to_delete),
                Memory.user_id == user_id,
            )
        )

    # Update existing rows whose IDs match
    existing_by_id = {mem.id: mem for mem in existing_memories}
    for item in memories:
        if item.id is not None and item.id in existing_by_id:
            existing_by_id[item.id].memory_text = item.content

    # Create new rows for items without an ID
    new_items = [m for m in memories if m.id is None]
    if new_items:
        db_session.add_all(
            [Memory(user_id=user_id, memory_text=item.content) for item in new_items]
        )

    db_session.commit()


def get_memories_for_user(
    user_id: UUID,
    db_session: Session,
) -> Sequence[Memory]:
    return db_session.scalars(
        select(Memory).where(Memory.user_id == user_id).order_by(Memory.id.desc())
    ).all()


def get_all_user_assistant_specific_configs(
    user_id: UUID,
    db_session: Session,
) -> Sequence[Assistant__UserSpecificConfig]:
    """Get the full user assistant specific config for a specific assistant and user."""
    return db_session.scalars(
        select(Assistant__UserSpecificConfig).where(
            Assistant__UserSpecificConfig.user_id == user_id
        )
    ).all()


def update_assistant_preferences(
    assistant_id: int,
    user_id: UUID,
    new_assistant_preference: UserSpecificAssistantPreference,
    db_session: Session,
) -> None:
    result = db_session.execute(
        select(Assistant__UserSpecificConfig)
        .where(Assistant__UserSpecificConfig.assistant_id == assistant_id)
        .where(Assistant__UserSpecificConfig.user_id == user_id)
    )
    config = result.scalar_one_or_none()

    if config:
        if new_assistant_preference.disabled_tool_ids is not None:
            config.disabled_tool_ids = new_assistant_preference.disabled_tool_ids
        if new_assistant_preference.disabled_integration_ids is not None:
            config.disabled_integration_ids = (
                new_assistant_preference.disabled_integration_ids
            )
    else:
        config = Assistant__UserSpecificConfig(
            assistant_id=assistant_id,
            user_id=user_id,
            disabled_tool_ids=new_assistant_preference.disabled_tool_ids or [],
            disabled_integration_ids=(
                new_assistant_preference.disabled_integration_ids or []
            ),
        )
        db_session.add(config)

    db_session.commit()
