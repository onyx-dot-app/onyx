"""Reads and writes for the agents a user has pinned to their sidebar.

Pins used to live in a `pinned_assistants` JSONB array on `user`, which bought
ordering-by-position and nothing else. It had no referential integrity, so a
deleted agent left a dangling id, and the write path validated nothing at all.
They are rows now, with the ordering the array carried by position moved into
`display_order`.
"""

from uuid import UUID

from sqlalchemy import Insert, delete, func, insert, literal, nulls_last, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.db.models import Persona, User, User__PinnedPersona
from onyx.db.persona import user_can_access_persona
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_pinned_persona_ids(db_session: Session, user_id: UUID) -> list[int]:
    """The user's pinned agent ids, in the order they should be shown."""
    return list(
        db_session.scalars(
            select(User__PinnedPersona.persona_id)
            .where(User__PinnedPersona.user_id == user_id)
            .order_by(User__PinnedPersona.display_order.asc())
        ).all()
    )


def set_pinned_personas(
    db_session: Session,
    user: User,
    persona_ids: list[int],
) -> None:
    """Replace the user's pins with `persona_ids`, in the order given.

    Ids the user cannot access are dropped rather than rejected. A foreign key
    stops a *nonexistent* agent from being pinned but says nothing about
    authorization, and the two failures are not worth distinguishing to a
    caller: both mean "that is not yours to pin". Duplicates collapse to their
    first position.
    """
    seen: set[int] = set()
    accepted: list[int] = []
    for persona_id in persona_ids:
        if persona_id in seen:
            continue
        seen.add(persona_id)
        if not user_can_access_persona(
            db_session=db_session, persona_id=persona_id, user=user
        ):
            logger.warning(
                "Ignoring pin of persona %s for user %s: no access",
                persona_id,
                user.id,
            )
            continue
        accepted.append(persona_id)

    db_session.execute(
        delete(User__PinnedPersona).where(User__PinnedPersona.user_id == user.id)
    )
    db_session.add_all(
        [
            User__PinnedPersona(
                user_id=user.id,
                persona_id=persona_id,
                display_order=order,
            )
            for order, persona_id in enumerate(accepted)
        ]
    )
    db_session.commit()


def build_seed_pinned_personas_stmt(user_id: UUID) -> Insert:
    """Insert this user's starting pins, straight from the featured agents.

    One statement rather than a read followed by inserts, so a user is never
    half-seeded and the whole thing rides on the creating transaction.

    The rule is "featured and viewable by this user". Viewable means public,
    shared directly, or shared with one of the user's groups - but seeding runs
    at the instant the user row is created, and both share tables key on
    `user.id`, so the latter two are empty by construction. The rule reduces
    exactly, not approximately, to `is_public`.

    Resist generalising this to the shared persona access filter. It returns the
    same rows for everyone except admins, who bypass it entirely and would be
    seeded with featured agents that are private to other people. Revisit only
    if invitations ever gain the ability to place a user in groups before that
    user exists.

    The built-in Assistant is excluded: the sidebar never renders id 0, so
    pinning it leaves a row the user can neither see nor remove.
    """
    featured = (
        select(
            # Typed from the column itself: an untyped literal renders as
            # text, and asyncpg will not coerce that to uuid.
            literal(user_id, User__PinnedPersona.user_id.type).label("user_id"),
            Persona.id.label("persona_id"),
            (
                func.row_number().over(
                    order_by=[
                        nulls_last(Persona.display_priority.asc()),
                        Persona.id.asc(),
                    ]
                )
                - 1
            ).label("display_order"),
        )
        .where(
            Persona.id != DEFAULT_PERSONA_ID,
            Persona.is_featured.is_(True),
            Persona.is_public.is_(True),
            Persona.is_listed.is_(True),
            Persona.deleted.is_(False),
        )
        .subquery()
    )

    return insert(User__PinnedPersona).from_select(
        ["user_id", "persona_id", "display_order"],
        select(featured.c.user_id, featured.c.persona_id, featured.c.display_order),
    )


async def seed_pinned_personas_from_featured(
    db_session: AsyncSession,
    user: User,
) -> None:
    """Give a newly created user the admin's featured agents as their pins.

    This runs once, when the account is created, and never again: an admin who
    features an agent later is setting a starting point for future users, not
    editing the sidebars of existing ones. A user who registers before anything
    is featured therefore starts with nothing, which is the admin having curated
    too late rather than a failure here.
    """
    await db_session.execute(build_seed_pinned_personas_stmt(user.id))
    await db_session.commit()
