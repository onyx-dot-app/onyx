import re
from datetime import datetime
from datetime import timezone

import jwt
from email_validator import EmailNotValidError
from email_validator import EmailUndeliverableError
from email_validator import validate_email
from fastapi import APIRouter
from fastapi import Body
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import status
from psycopg2.errors import UniqueViolation
from pydantic import BaseModel
from sqlalchemy import Column
from sqlalchemy import desc
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from danswer.auth.invited_users import get_invited_users
from danswer.auth.invited_users import write_invited_users
from danswer.auth.noauth_user import fetch_no_auth_user
from danswer.auth.noauth_user import set_no_auth_user_preferences
from danswer.auth.schemas import UserRole
from danswer.auth.schemas import UserStatus
from danswer.auth.users import current_admin_user
from danswer.auth.users import current_curator_or_admin_user
from danswer.auth.users import current_user
from danswer.auth.users import optional_user
from danswer.configs.app_configs import AUTH_TYPE
from danswer.configs.app_configs import ENABLE_EMAIL_INVITES
from danswer.configs.app_configs import MULTI_TENANT
from danswer.configs.app_configs import SESSION_EXPIRE_TIME_SECONDS
from danswer.configs.app_configs import VALID_EMAIL_DOMAINS
from danswer.configs.constants import AuthType
from danswer.db.auth import get_total_users
from danswer.db.engine import CURRENT_TENANT_ID_CONTEXTVAR
from danswer.db.engine import get_session
from danswer.db.models import AccessToken
from danswer.db.models import DocumentSet__User
from danswer.db.models import Persona__User
from danswer.db.models import SamlAccount
from danswer.db.models import User
from danswer.db.models import User__UserGroup
from danswer.db.users import get_user_by_email
from danswer.db.users import list_users
from danswer.key_value_store.factory import get_kv_store
from danswer.server.manage.models import AllUsersResponse
from danswer.server.manage.models import UserByEmail
from danswer.server.manage.models import UserInfo
from danswer.server.manage.models import UserPreferences
from danswer.server.manage.models import UserRoleResponse
from danswer.server.manage.models import UserRoleUpdateRequest
from danswer.server.models import FullUserSnapshot
from danswer.server.models import InvitedUserSnapshot
from danswer.server.models import MinimalUserSnapshot
from danswer.server.utils import send_user_email_invite
from danswer.utils.logger import setup_logger
from ee.danswer.db.api_key import is_api_key_email_address
from ee.danswer.db.external_perm import delete_user__ext_group_for_user__no_commit
from ee.danswer.db.user_group import remove_curator_status__no_commit
from ee.danswer.server.tenants.billing import register_tenant_users
from ee.danswer.server.tenants.provisioning import add_users_to_tenant
from ee.danswer.server.tenants.provisioning import remove_users_from_tenant

logger = setup_logger()

router = APIRouter()


USERS_PAGE_SIZE = 10


@router.patch("/manage/set-user-role")
def set_user_role(
    user_role_update_request: UserRoleUpdateRequest,
    current_user: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    user_to_update = get_user_by_email(
        email=user_role_update_request.user_email, db_session=db_session
    )
    if not user_to_update:
        raise HTTPException(status_code=404, detail="User not found")

    if user_role_update_request.new_role == UserRole.CURATOR:
        raise HTTPException(
            status_code=400,
            detail="Curator role must be set via the User Group Menu",
        )

    if user_to_update.role == user_role_update_request.new_role:
        return

    if current_user.id == user_to_update.id:
        raise HTTPException(
            status_code=400,
            detail="An admin cannot demote themselves from admin role!",
        )

    if user_to_update.role == UserRole.CURATOR:
        remove_curator_status__no_commit(db_session, user_to_update)

    user_to_update.role = user_role_update_request.new_role.value

    db_session.commit()


@router.get("/manage/users")
def list_all_users(
    q: str | None = None,
    accepted_page: int | None = None,
    invited_page: int | None = None,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> AllUsersResponse:
    if not q:
        q = ""

    users = [
        user
        for user in list_users(db_session, email_filter_string=q, user=user)
        if not is_api_key_email_address(user.email)
    ]
    accepted_emails = {user.email for user in users}
    invited_emails = get_invited_users()
    if q:
        invited_emails = [
            email for email in invited_emails if re.search(r"{}".format(q), email, re.I)
        ]

    accepted_count = len(accepted_emails)
    invited_count = len(invited_emails)

    # If any of q, accepted_page, or invited_page is None, return all users
    if accepted_page is None or invited_page is None:
        return AllUsersResponse(
            accepted=[
                FullUserSnapshot(
                    id=user.id,
                    email=user.email,
                    role=user.role,
                    status=(
                        UserStatus.LIVE if user.is_active else UserStatus.DEACTIVATED
                    ),
                )
                for user in users
            ],
            invited=[InvitedUserSnapshot(email=email) for email in invited_emails],
            accepted_pages=1,
            invited_pages=1,
        )

    # Otherwise, return paginated results
    return AllUsersResponse(
        accepted=[
            FullUserSnapshot(
                id=user.id,
                email=user.email,
                role=user.role,
                status=UserStatus.LIVE if user.is_active else UserStatus.DEACTIVATED,
            )
            for user in users
        ][accepted_page * USERS_PAGE_SIZE : (accepted_page + 1) * USERS_PAGE_SIZE],
        invited=[InvitedUserSnapshot(email=email) for email in invited_emails][
            invited_page * USERS_PAGE_SIZE : (invited_page + 1) * USERS_PAGE_SIZE
        ],
        accepted_pages=accepted_count // USERS_PAGE_SIZE + 1,
        invited_pages=invited_count // USERS_PAGE_SIZE + 1,
    )


@router.put("/manage/admin/users")
def bulk_invite_users(
    emails: list[str] = Body(..., embed=True),
    current_user: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> int:
    """emails are string validated. If any email fails validation, no emails are
    invited and an exception is raised."""

    if current_user is None:
        raise HTTPException(
            status_code=400, detail="Auth is disabled, cannot invite users"
        )

    tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get()

    normalized_emails = []
    try:
        for email in emails:
            email_info = validate_email(email)
            normalized_emails.append(email_info.normalized)  # type: ignore

    except (EmailUndeliverableError, EmailNotValidError):
        raise HTTPException(
            status_code=400,
            detail="One or more emails in the list are invalid",
        )

    if MULTI_TENANT:
        try:
            add_users_to_tenant(normalized_emails, tenant_id)
        except IntegrityError as e:
            if isinstance(e.orig, UniqueViolation):
                raise HTTPException(
                    status_code=400,
                    detail="User has already been invited to a Danswer organization",
                )
            raise

    initial_invited_users = get_invited_users()

    all_emails = list(set(normalized_emails) | set(initial_invited_users))
    number_of_invited_users = write_invited_users(all_emails)

    if not MULTI_TENANT:
        return number_of_invited_users
    try:
        logger.info("Registering tenant users")
        register_tenant_users(
            CURRENT_TENANT_ID_CONTEXTVAR.get(), get_total_users(db_session)
        )
        if ENABLE_EMAIL_INVITES:
            try:
                for email in all_emails:
                    send_user_email_invite(email, current_user)
            except Exception as e:
                logger.error(f"Error sending email invite to invited users: {e}")

        return number_of_invited_users
    except Exception as e:
        logger.error(f"Failed to register tenant users: {str(e)}")
        logger.info(
            "Reverting changes: removing users from tenant and resetting invited users"
        )
        write_invited_users(initial_invited_users)  # Reset to original state
        remove_users_from_tenant(normalized_emails, tenant_id)
        raise e


@router.patch("/manage/admin/remove-invited-user")
def remove_invited_user(
    user_email: UserByEmail,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> int:
    user_emails = get_invited_users()
    remaining_users = [user for user in user_emails if user != user_email.user_email]

    tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get()
    remove_users_from_tenant([user_email.user_email], tenant_id)
    number_of_invited_users = write_invited_users(remaining_users)

    try:
        if MULTI_TENANT:
            register_tenant_users(
                CURRENT_TENANT_ID_CONTEXTVAR.get(), get_total_users(db_session)
            )
    except Exception:
        logger.error(
            "Request to update number of seats taken in control plane failed. "
            "This may cause synchronization issues/out of date enforcement of seat limits."
        )
        raise

    return number_of_invited_users


@router.patch("/manage/admin/deactivate-user")
def deactivate_user(
    user_email: UserByEmail,
    current_user: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    if current_user is None:
        raise HTTPException(
            status_code=400, detail="Auth is disabled, cannot deactivate user"
        )

    if current_user.email == user_email.user_email:
        raise HTTPException(status_code=400, detail="You cannot deactivate yourself")

    user_to_deactivate = get_user_by_email(
        email=user_email.user_email, db_session=db_session
    )

    if not user_to_deactivate:
        raise HTTPException(status_code=404, detail="User not found")

    if user_to_deactivate.is_active is False:
        logger.warning("{} is already deactivated".format(user_to_deactivate.email))

    user_to_deactivate.is_active = False
    db_session.add(user_to_deactivate)
    db_session.commit()


@router.delete("/manage/admin/delete-user")
async def delete_user(
    user_email: UserByEmail,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    user_to_delete = get_user_by_email(
        email=user_email.user_email, db_session=db_session
    )
    if not user_to_delete:
        raise HTTPException(status_code=404, detail="User not found")

    if user_to_delete.is_active is True:
        logger.warning(
            "{} must be deactivated before deleting".format(user_to_delete.email)
        )
        raise HTTPException(
            status_code=400, detail="User must be deactivated before deleting"
        )

    # Detach the user from the current session
    db_session.expunge(user_to_delete)

    try:
        for oauth_account in user_to_delete.oauth_accounts:
            db_session.delete(oauth_account)

        delete_user__ext_group_for_user__no_commit(
            db_session=db_session,
            user_id=user_to_delete.id,
        )
        db_session.query(SamlAccount).filter(
            SamlAccount.user_id == user_to_delete.id
        ).delete()
        db_session.query(DocumentSet__User).filter(
            DocumentSet__User.user_id == user_to_delete.id
        ).delete()
        db_session.query(Persona__User).filter(
            Persona__User.user_id == user_to_delete.id
        ).delete()
        db_session.query(User__UserGroup).filter(
            User__UserGroup.user_id == user_to_delete.id
        ).delete()
        db_session.delete(user_to_delete)
        db_session.commit()

        # NOTE: edge case may exist with race conditions
        # with this `invited user` scheme generally.
        user_emails = get_invited_users()
        remaining_users = [
            user for user in user_emails if user != user_email.user_email
        ]
        write_invited_users(remaining_users)

        logger.info(f"Deleted user {user_to_delete.email}")
    except Exception as e:
        import traceback

        full_traceback = traceback.format_exc()
        logger.error(f"Full stack trace:\n{full_traceback}")
        db_session.rollback()
        logger.error(f"Error deleting user {user_to_delete.email}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error deleting user")


@router.patch("/manage/admin/activate-user")
def activate_user(
    user_email: UserByEmail,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    user_to_activate = get_user_by_email(
        email=user_email.user_email, db_session=db_session
    )
    if not user_to_activate:
        raise HTTPException(status_code=404, detail="User not found")

    if user_to_activate.is_active is True:
        logger.warning("{} is already activated".format(user_to_activate.email))

    user_to_activate.is_active = True
    db_session.add(user_to_activate)
    db_session.commit()


@router.get("/manage/admin/valid-domains")
def get_valid_domains(
    _: User | None = Depends(current_admin_user),
) -> list[str]:
    return VALID_EMAIL_DOMAINS


"""Endpoints for all"""


@router.get("/users")
def list_all_users_basic_info(
    _: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[MinimalUserSnapshot]:
    users = list_users(db_session)
    return [MinimalUserSnapshot(id=user.id, email=user.email) for user in users]


@router.get("/get-user-role")
async def get_user_role(user: User = Depends(current_user)) -> UserRoleResponse:
    if user is None:
        raise ValueError("Invalid or missing user.")
    return UserRoleResponse(role=user.role)


def get_current_token_expiration_jwt(
    user: User | None, request: Request
) -> datetime | None:
    if user is None:
        return None

    try:
        # Get the JWT from the cookie
        jwt_token = request.cookies.get("fastapiusersauth")
        if not jwt_token:
            logger.error("No JWT token found in cookies")
            return None

        # Decode the JWT
        decoded_token = jwt.decode(jwt_token, options={"verify_signature": False})

        # Get the 'exp' (expiration) claim from the token
        exp = decoded_token.get("exp")
        if exp:
            return datetime.fromtimestamp(exp)
        else:
            logger.error("No 'exp' claim found in JWT")
            return None

    except Exception as e:
        logger.error(f"Error decoding JWT: {e}")
        return None


def get_current_token_creation(
    user: User | None, db_session: Session
) -> datetime | None:
    if user is None:
        return None
    try:
        result = db_session.execute(
            select(AccessToken)
            .where(AccessToken.user_id == user.id)  # type: ignore
            .order_by(desc(Column("created_at")))
            .limit(1)
        )
        access_token = result.scalar_one_or_none()

        if access_token:
            return access_token.created_at
        else:
            logger.error("No AccessToken found for user")
            return None

    except Exception as e:
        logger.error(f"Error fetching AccessToken: {e}")
        return None


@router.get("/me")
def verify_user_logged_in(
    user: User | None = Depends(optional_user),
    db_session: Session = Depends(get_session),
) -> UserInfo:
    # NOTE: this does not use `current_user` / `current_admin_user` because we don't want
    # to enforce user verification here - the frontend always wants to get the info about
    # the current user regardless of if they are currently verified
    if user is None:
        # if auth type is disabled, return a dummy user with preferences from
        # the key-value store
        if AUTH_TYPE == AuthType.DISABLED:
            store = get_kv_store()
            return fetch_no_auth_user(store)

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User Not Authenticated"
        )

    if user.oidc_expiry and user.oidc_expiry < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. User's OIDC token has expired.",
        )

    token_created_at = (
        None if MULTI_TENANT else get_current_token_creation(user, db_session)
    )
    user_info = UserInfo.from_model(
        user,
        current_token_created_at=token_created_at,
        expiry_length=SESSION_EXPIRE_TIME_SECONDS,
    )

    return user_info


"""APIs to adjust user preferences"""


class ChosenDefaultModelRequest(BaseModel):
    default_model: str | None = None


@router.patch("/user/default-model")
def update_user_default_model(
    request: ChosenDefaultModelRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    if user is None:
        if AUTH_TYPE == AuthType.DISABLED:
            store = get_kv_store()
            no_auth_user = fetch_no_auth_user(store)
            no_auth_user.preferences.default_model = request.default_model
            set_no_auth_user_preferences(store, no_auth_user.preferences)
            return
        else:
            raise RuntimeError("This should never happen")

    db_session.execute(
        update(User)
        .where(User.id == user.id)  # type: ignore
        .values(default_model=request.default_model)
    )
    db_session.commit()


class ChosenAssistantsRequest(BaseModel):
    chosen_assistants: list[int]


@router.patch("/user/assistant-list")
def update_user_assistant_list(
    request: ChosenAssistantsRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    if user is None:
        if AUTH_TYPE == AuthType.DISABLED:
            store = get_kv_store()

            no_auth_user = fetch_no_auth_user(store)
            no_auth_user.preferences.chosen_assistants = request.chosen_assistants
            set_no_auth_user_preferences(store, no_auth_user.preferences)
            return
        else:
            raise RuntimeError("This should never happen")

    db_session.execute(
        update(User)
        .where(User.id == user.id)  # type: ignore
        .values(chosen_assistants=request.chosen_assistants)
    )
    db_session.commit()


def update_assistant_list(
    preferences: UserPreferences, assistant_id: int, show: bool
) -> UserPreferences:
    visible_assistants = preferences.visible_assistants or []
    hidden_assistants = preferences.hidden_assistants or []
    chosen_assistants = preferences.chosen_assistants or []

    if show:
        if assistant_id not in visible_assistants:
            visible_assistants.append(assistant_id)
        if assistant_id in hidden_assistants:
            hidden_assistants.remove(assistant_id)
        if assistant_id not in chosen_assistants:
            chosen_assistants.append(assistant_id)
    else:
        if assistant_id in visible_assistants:
            visible_assistants.remove(assistant_id)
        if assistant_id not in hidden_assistants:
            hidden_assistants.append(assistant_id)
        if assistant_id in chosen_assistants:
            chosen_assistants.remove(assistant_id)

    preferences.visible_assistants = visible_assistants
    preferences.hidden_assistants = hidden_assistants
    preferences.chosen_assistants = chosen_assistants
    return preferences


@router.patch("/user/assistant-list/update/{assistant_id}")
def update_user_assistant_visibility(
    assistant_id: int,
    show: bool,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    if user is None:
        if AUTH_TYPE == AuthType.DISABLED:
            store = get_kv_store()
            no_auth_user = fetch_no_auth_user(store)
            preferences = no_auth_user.preferences
            updated_preferences = update_assistant_list(preferences, assistant_id, show)
            set_no_auth_user_preferences(store, updated_preferences)
            return
        else:
            raise RuntimeError("This should never happen")

    user_preferences = UserInfo.from_model(user).preferences
    updated_preferences = update_assistant_list(user_preferences, assistant_id, show)

    db_session.execute(
        update(User)
        .where(User.id == user.id)  # type: ignore
        .values(
            hidden_assistants=updated_preferences.hidden_assistants,
            visible_assistants=updated_preferences.visible_assistants,
            chosen_assistants=updated_preferences.chosen_assistants,
        )
    )
    db_session.commit()
