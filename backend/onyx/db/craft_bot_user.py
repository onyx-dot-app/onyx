from fastapi_users.password import PasswordHelper
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.configs.constants import DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN
from onyx.db.enums import AccountType
from onyx.db.models import User
from onyx.db.users import assign_user_to_default_groups__no_commit

# Ends with the same sentinel domain as API-key dummy users, so every
# existing "exclude API key users" filter (listing endpoints, admin UI,
# live user counts) hides the bot for free.
CRAFT_BOT_EMAIL = f"craft-slackbot@{DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN}"


def get_or_create_craft_bot_user(db_session: Session) -> User:
    """Return this tenant's Craft Slackbot service-account user, creating it
    on first call. One bot user per tenant (tenant scoping comes from the
    caller's schema, same as every other tenant-scoped query).

    BASIC role + SERVICE_ACCOUNT account type: no admin capability, but
    (unlike BOT/EXT_PERM_USER) still eligible for default-group assignment
    and further group membership, so admins can widen its search ACL later.
    No login is possible: the password hash is a random, discarded secret.
    """
    existing = db_session.scalar(
        select(User).where(User.email == CRAFT_BOT_EMAIL)  # ty: ignore[invalid-argument-type]
    )
    if existing is not None:
        return existing

    password_helper = PasswordHelper()
    bot_user = User(
        email=CRAFT_BOT_EMAIL,
        hashed_password=password_helper.hash(password_helper.generate()),
        is_active=True,
        is_superuser=False,
        is_verified=True,
        role=UserRole.BASIC,
        account_type=AccountType.SERVICE_ACCOUNT,
    )
    # Savepoint so a lost concurrent-create race only rolls back this insert,
    # not the caller's other pending work in the same session.
    savepoint = db_session.begin_nested()
    try:
        db_session.add(bot_user)
        savepoint.commit()
    except IntegrityError:
        savepoint.rollback()
        existing = db_session.scalar(
            select(User).where(User.email == CRAFT_BOT_EMAIL)  # ty: ignore[invalid-argument-type]
        )
        if existing is None:
            raise
        return existing

    assign_user_to_default_groups__no_commit(db_session, bot_user, is_admin=False)
    db_session.commit()
    return bot_user
