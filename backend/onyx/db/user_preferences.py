from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Column
from sqlalchemy import delete
from sqlalchemy import desc
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.models import AccessToken
from onyx.db.models import Assistant__UserSpecificConfig
from onyx.db.models import Memory
from onyx.db.models import User
from onyx.server.manage.models import UserSpecificAssistantPreference
from onyx.utils.logger import setup_logger


logger = setup_logger()


def update_user_role(
    user: User,
    new_role: UserRole,
    db_session: Session,
) -> None:
    """Update a user's role in the database."""
    user.role = new_role
    db_session.commit()


def deactivate_user(
    user: User,
    db_session: Session,
) -> None:
    """Deactivate a user by setting is_active to False."""
    user.is_active = False
    db_session.add(user)
    db_session.commit()


def activate_user(
    user: User,
    db_session: Session,
) -> None:
    """Activate a user by setting is_active to True."""
    user.is_active = True
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
            .where(AccessToken.user_id == user_id)  # type: ignore
            .order_by(desc(Column("created_at")))
            .limit(1)
        )
        return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Error fetching AccessToken: {e}")
        return None


def update_user_temperature_override_enabled(
    user_id: UUID,
    temperature_override_enabled: bool,
    db_session: Session,
) -> None:
    """Update user's temperature override enabled setting."""
    db_session.execute(
        update(User)
        .where(User.id == user_id)  # type: ignore
        .values(temperature_override_enabled=temperature_override_enabled)
    )
    db_session.commit()


def update_user_shortcut_enabled(
    user_id: UUID,
    shortcut_enabled: bool,
    db_session: Session,
) -> None:
    """Update user's shortcut enabled setting."""
    db_session.execute(
        update(User)
        .where(User.id == user_id)  # type: ignore
        .values(shortcut_enabled=shortcut_enabled)
    )
    db_session.commit()


def update_user_auto_scroll(
    user_id: UUID,
    auto_scroll: bool | None,
    db_session: Session,
) -> None:
    """Update user's auto scroll setting."""
    db_session.execute(
        update(User)
        .where(User.id == user_id)  # type: ignore
        .values(auto_scroll=auto_scroll)
    )
    db_session.commit()


def update_user_default_model(
    user_id: UUID,
    default_model: str | None,
    db_session: Session,
) -> None:
    """Update user's default model setting."""
    db_session.execute(
        update(User)
        .where(User.id == user_id)  # type: ignore
        .values(default_model=default_model)
    )
    db_session.commit()


def update_user_personalization(
    user_id: UUID,
    *,
    personal_name: str | None,
    personal_role: str | None,
    use_memories: bool,
    memories: list[str],
    db_session: Session,
) -> None:
    db_session.execute(
        update(User)
        .where(User.id == user_id)  # type: ignore
        .values(
            personal_name=personal_name,
            personal_role=personal_role,
            use_memories=use_memories,
        )
    )

    db_session.execute(delete(Memory).where(Memory.user_id == user_id))

    if memories:
        db_session.add_all(
            [Memory(user_id=user_id, memory_text=memory) for memory in memories]
        )

    db_session.commit()


def get_memories_for_user(
    user_id: UUID,
    db_session: Session,
) -> Sequence[Memory]:
    return db_session.scalars(select(Memory).where(Memory.user_id == user_id)).all()


def update_user_pinned_assistants(
    user_id: UUID,
    pinned_assistants: list[int],
    db_session: Session,
) -> None:
    """Update user's pinned assistants list."""
    db_session.execute(
        update(User)
        .where(User.id == user_id)  # type: ignore
        .values(pinned_assistants=pinned_assistants)
    )
    db_session.commit()


def update_user_assistant_visibility(
    user_id: UUID,
    hidden_assistants: list[int] | None,
    visible_assistants: list[int] | None,
    chosen_assistants: list[int] | None,
    db_session: Session,
) -> None:
    """Update user's assistant visibility settings."""
    db_session.execute(
        update(User)
        .where(User.id == user_id)  # type: ignore
        .values(
            hidden_assistants=hidden_assistants,
            visible_assistants=visible_assistants,
            chosen_assistants=chosen_assistants,
        )
    )
    db_session.commit()


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
    """Update the disabled tools for a specific assistant for a specific user."""
    # First check if a config already exists
    result = db_session.execute(
        select(Assistant__UserSpecificConfig)
        .where(Assistant__UserSpecificConfig.assistant_id == assistant_id)
        .where(Assistant__UserSpecificConfig.user_id == user_id)
    )
    config = result.scalar_one_or_none()

    if config:
        # Update existing config
        config.disabled_tool_ids = new_assistant_preference.disabled_tool_ids
    else:
        # Create new config
        config = Assistant__UserSpecificConfig(
            assistant_id=assistant_id,
            user_id=user_id,
            disabled_tool_ids=new_assistant_preference.disabled_tool_ids,
        )
        db_session.add(config)

    db_session.commit()
