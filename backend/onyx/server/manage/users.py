import csv
import io
import re
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import cast

from email_validator import EmailNotValidError
from email_validator import EmailUndeliverableError
from email_validator import validate_email
from fastapi import APIRouter
from fastapi import Body
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.email_utils import send_user_email_invite
from onyx.auth.invited_users import get_invited_users
from onyx.auth.invited_users import remove_user_from_invited_users
from onyx.auth.invited_users import write_invited_users
from onyx.auth.noauth_user import fetch_no_auth_user
from onyx.auth.noauth_user import set_no_auth_user_personalization
from onyx.auth.noauth_user import set_no_auth_user_preferences
from onyx.auth.schemas import UserRole
from onyx.auth.users import anonymous_user_enabled
from onyx.auth.users import current_admin_user
from onyx.auth.users import current_curator_or_admin_user
from onyx.auth.users import current_user
from onyx.auth.users import optional_user
from onyx.configs.app_configs import AUTH_BACKEND
from onyx.configs.app_configs import AUTH_TYPE
from onyx.configs.app_configs import AuthBackend
from onyx.configs.app_configs import DEV_MODE
from onyx.configs.app_configs import ENABLE_EMAIL_INVITES
from onyx.configs.app_configs import REDIS_AUTH_KEY_PREFIX
from onyx.configs.app_configs import SESSION_EXPIRE_TIME_SECONDS
from onyx.configs.app_configs import VALID_EMAIL_DOMAINS
from onyx.configs.constants import AuthType
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.db.api_key import is_api_key_email_address
from onyx.db.auth import get_live_users_count
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import UserFileStatus
from onyx.db.models import User
from onyx.db.models import UserFile
from onyx.db.user_preferences import activate_user
from onyx.db.user_preferences import deactivate_user
from onyx.db.user_preferences import get_all_user_assistant_specific_configs
from onyx.db.user_preferences import get_latest_access_token_for_user
from onyx.db.user_preferences import update_assistant_preferences
from onyx.db.user_preferences import update_user_assistant_visibility
from onyx.db.user_preferences import update_user_auto_scroll
from onyx.db.user_preferences import update_user_default_model
from onyx.db.user_preferences import update_user_personalization
from onyx.db.user_preferences import update_user_pinned_assistants
from onyx.db.user_preferences import update_user_role
from onyx.db.user_preferences import update_user_shortcut_enabled
from onyx.db.user_preferences import update_user_temperature_override_enabled
from onyx.db.users import delete_user_from_db
from onyx.db.users import get_all_users
from onyx.db.users import get_page_of_filtered_users
from onyx.db.users import get_total_filtered_users_count
from onyx.db.users import get_user_by_email
from onyx.db.users import validate_user_role_update
from onyx.key_value_store.factory import get_kv_store
from onyx.redis.redis_pool import get_raw_redis_client
from onyx.server.documents.models import PaginatedReturn
from onyx.server.features.projects.models import UserFileSnapshot
from onyx.server.manage.models import AllUsersResponse
from onyx.server.manage.models import AutoScrollRequest
from onyx.server.manage.models import PersonalizationUpdateRequest
from onyx.server.manage.models import TenantInfo
from onyx.server.manage.models import TenantSnapshot
from onyx.server.manage.models import UserByEmail
from onyx.server.manage.models import UserInfo
from onyx.server.manage.models import UserPreferences
from onyx.server.manage.models import UserRoleResponse
from onyx.server.manage.models import UserRoleUpdateRequest
from onyx.server.manage.models import UserSpecificAssistantPreference
from onyx.server.manage.models import UserSpecificAssistantPreferences
from onyx.server.models import FullUserSnapshot
from onyx.server.models import InvitedUserSnapshot
from onyx.server.models import MinimalUserSnapshot
from onyx.server.utils import BasicAuthenticationError
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation_with_fallback,
)
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

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

    current_role = user_to_update.role
    requested_role = user_role_update_request.new_role
    if requested_role == current_role:
        return

    # This will raise an exception if the role update is invalid
    validate_user_role_update(
        requested_role=requested_role,
        current_role=current_role,
        explicit_override=user_role_update_request.explicit_override,
    )

    if user_to_update.id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="An admin cannot demote themselves from admin role!",
        )

    if requested_role == UserRole.CURATOR:
        # Remove all curator db relationships before changing role
        fetch_ee_implementation_or_noop(
            "onyx.db.user_group",
            "remove_curator_status__no_commit",
        )(db_session, user_to_update)

    update_user_role(user_to_update, requested_role, db_session)


class TestUpsertRequest(BaseModel):
    email: str


@router.post("/manage/users/test-upsert-user")
async def test_upsert_user(
    request: TestUpsertRequest,
    _: User = Depends(current_admin_user),
) -> None | FullUserSnapshot:
    """Test endpoint for upsert_saml_user. Only used for integration testing."""
    user = await fetch_ee_implementation_or_noop(
        "onyx.server.saml", "upsert_saml_user", None
    )(email=request.email)
    return FullUserSnapshot.from_user_model(user) if user else None


@router.get("/manage/users/accepted")
def list_accepted_users(
    q: str | None = Query(default=None),
    page_num: int = Query(0, ge=0),
    page_size: int = Query(10, ge=1, le=1000),
    roles: list[UserRole] = Query(default=[]),
    is_active: bool | None = Query(default=None),
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> PaginatedReturn[FullUserSnapshot]:
    filtered_accepted_users = get_page_of_filtered_users(
        db_session=db_session,
        page_size=page_size,
        page_num=page_num,
        email_filter_string=q,
        is_active_filter=is_active,
        roles_filter=roles,
    )

    total_accepted_users_count = get_total_filtered_users_count(
        db_session=db_session,
        email_filter_string=q,
        is_active_filter=is_active,
        roles_filter=roles,
    )

    if not filtered_accepted_users:
        logger.info("No users found")
        return PaginatedReturn(
            items=[],
            total_items=0,
        )

    return PaginatedReturn(
        items=[
            FullUserSnapshot.from_user_model(user) for user in filtered_accepted_users
        ],
        total_items=total_accepted_users_count,
    )


@router.get("/manage/users/invited")
def list_invited_users(
    _: User | None = Depends(current_admin_user),
) -> list[InvitedUserSnapshot]:
    invited_emails = get_invited_users()

    return [InvitedUserSnapshot(email=email) for email in invited_emails]


@router.get("/manage/users")
def list_all_users(
    q: str | None = None,
    accepted_page: int | None = None,
    slack_users_page: int | None = None,
    invited_page: int | None = None,
    include_api_keys: bool = False,
    _: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> AllUsersResponse:
    users = [
        user
        for user in get_all_users(db_session, email_filter_string=q)
        if (include_api_keys or not is_api_key_email_address(user.email))
    ]

    slack_users = [user for user in users if user.role == UserRole.SLACK_USER]
    accepted_users = [user for user in users if user.role != UserRole.SLACK_USER]

    accepted_emails = {user.email for user in accepted_users}
    slack_users_emails = {user.email for user in slack_users}
    invited_emails = get_invited_users()
    if q:
        invited_emails = [
            email for email in invited_emails if re.search(r"{}".format(q), email, re.I)
        ]

    accepted_count = len(accepted_emails)
    slack_users_count = len(slack_users_emails)
    invited_count = len(invited_emails)

    # If any of q, accepted_page, or invited_page is None, return all users
    if accepted_page is None or invited_page is None or slack_users_page is None:
        return AllUsersResponse(
            accepted=[
                FullUserSnapshot(
                    id=user.id,
                    email=user.email,
                    role=user.role,
                    is_active=user.is_active,
                    password_configured=user.password_configured,
                )
                for user in accepted_users
            ],
            slack_users=[
                FullUserSnapshot(
                    id=user.id,
                    email=user.email,
                    role=user.role,
                    is_active=user.is_active,
                    password_configured=user.password_configured,
                )
                for user in slack_users
            ],
            invited=[InvitedUserSnapshot(email=email) for email in invited_emails],
            accepted_pages=1,
            invited_pages=1,
            slack_users_pages=1,
        )

    # Otherwise, return paginated results
    return AllUsersResponse(
        accepted=[
            FullUserSnapshot(
                id=user.id,
                email=user.email,
                role=user.role,
                is_active=user.is_active,
                password_configured=user.password_configured,
            )
            for user in accepted_users
        ][accepted_page * USERS_PAGE_SIZE : (accepted_page + 1) * USERS_PAGE_SIZE],
        slack_users=[
            FullUserSnapshot(
                id=user.id,
                email=user.email,
                role=user.role,
                is_active=user.is_active,
                password_configured=user.password_configured,
            )
            for user in slack_users
        ][
            slack_users_page
            * USERS_PAGE_SIZE : (slack_users_page + 1)
            * USERS_PAGE_SIZE
        ],
        invited=[InvitedUserSnapshot(email=email) for email in invited_emails][
            invited_page * USERS_PAGE_SIZE : (invited_page + 1) * USERS_PAGE_SIZE
        ],
        accepted_pages=(accepted_count + USERS_PAGE_SIZE - 1) // USERS_PAGE_SIZE,
        invited_pages=(invited_count + USERS_PAGE_SIZE - 1) // USERS_PAGE_SIZE,
        slack_users_pages=(slack_users_count + USERS_PAGE_SIZE - 1) // USERS_PAGE_SIZE,
    )


@router.get("/manage/users/download")
def download_users_csv(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> StreamingResponse:
    """Download all users as a CSV file."""
    # Get all users from the database
    users = get_all_users(db_session)

    # Create CSV content in memory
    output = io.StringIO()
    writer = csv.writer(output)

    # Write CSV header
    writer.writerow(["Email", "Role", "Status"])

    # Write user data
    for user in users:
        writer.writerow(
            [
                user.email,
                user.role.value if user.role else "",
                "Active" if user.is_active else "Inactive",
            ]
        )

    # Prepare the CSV content for download
    csv_content = output.getvalue()
    output.close()

    return StreamingResponse(
        io.BytesIO(csv_content.encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment;"},
    )


@router.put("/manage/admin/users")
def bulk_invite_users(
    emails: list[str] = Body(..., embed=True),
    current_user: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> int:
    """emails are string validated. If any email fails validation, no emails are
    invited and an exception is raised."""
    tenant_id = get_current_tenant_id()

    if current_user is None:
        raise HTTPException(
            status_code=400, detail="Auth is disabled, cannot invite users"
        )

    new_invited_emails = []
    email: str

    try:
        for email in emails:
            email_info = validate_email(email)
            new_invited_emails.append(email_info.normalized)

    except (EmailUndeliverableError, EmailNotValidError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid email address: {email} - {str(e)}",
        )

    if MULTI_TENANT:
        try:
            fetch_ee_implementation_or_noop(
                "onyx.server.tenants.provisioning", "add_users_to_tenant", None
            )(new_invited_emails, tenant_id)

        except Exception as e:
            logger.error(f"Failed to add users to tenant {tenant_id}: {str(e)}")

    initial_invited_users = get_invited_users()

    all_emails = list(set(new_invited_emails) | set(initial_invited_users))
    number_of_invited_users = write_invited_users(all_emails)

    # send out email invitations if enabled
    if ENABLE_EMAIL_INVITES:
        try:
            for email in new_invited_emails:
                send_user_email_invite(email, current_user, AUTH_TYPE)
        except Exception as e:
            logger.error(f"Error sending email invite to invited users: {e}")

    if not MULTI_TENANT or DEV_MODE:
        return number_of_invited_users

    # for billing purposes, write to the control plane about the number of new users
    try:
        logger.info("Registering tenant users")
        fetch_ee_implementation_or_noop(
            "onyx.server.tenants.billing", "register_tenant_users", None
        )(tenant_id, get_live_users_count(db_session))

        return number_of_invited_users
    except Exception as e:
        logger.error(f"Failed to register tenant users: {str(e)}")
        logger.info(
            "Reverting changes: removing users from tenant and resetting invited users"
        )
        write_invited_users(initial_invited_users)  # Reset to original state
        fetch_ee_implementation_or_noop(
            "onyx.server.tenants.user_mapping", "remove_users_from_tenant", None
        )(new_invited_emails, tenant_id)
        raise e


@router.patch("/manage/admin/remove-invited-user")
def remove_invited_user(
    user_email: UserByEmail,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> int:
    tenant_id = get_current_tenant_id()
    if MULTI_TENANT:
        fetch_ee_implementation_or_noop(
            "onyx.server.tenants.user_mapping", "remove_users_from_tenant", None
        )([user_email.user_email], tenant_id)
    number_of_invited_users = remove_user_from_invited_users(user_email.user_email)

    try:
        if MULTI_TENANT and not DEV_MODE:
            fetch_ee_implementation_or_noop(
                "onyx.server.tenants.billing", "register_tenant_users", None
            )(tenant_id, get_live_users_count(db_session))
    except Exception:
        logger.error(
            "Request to update number of seats taken in control plane failed. "
            "This may cause synchronization issues/out of date enforcement of seat limits."
        )
        raise

    return number_of_invited_users


@router.patch("/manage/admin/deactivate-user")
def deactivate_user_api(
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

    deactivate_user(user_to_deactivate, db_session)


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
        tenant_id = get_current_tenant_id()
        fetch_ee_implementation_or_noop(
            "onyx.server.tenants.user_mapping", "remove_users_from_tenant", None
        )([user_email.user_email], tenant_id)
        delete_user_from_db(user_to_delete, db_session)
        logger.info(f"Deleted user {user_to_delete.email}")

    except Exception as e:
        db_session.rollback()
        logger.error(f"Error deleting user {user_to_delete.email}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error deleting user")


@router.patch("/manage/admin/activate-user")
def activate_user_api(
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

    activate_user(user_to_activate, db_session)


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
    users = get_all_users(db_session)
    return [MinimalUserSnapshot(id=user.id, email=user.email) for user in users]


@router.get("/get-user-role")
async def get_user_role(user: User = Depends(current_user)) -> UserRoleResponse:
    if user is None:
        raise ValueError("Invalid or missing user.")
    return UserRoleResponse(role=user.role)


def get_current_auth_token_creation_redis(
    user: User | None, request: Request
) -> datetime | None:
    """Calculate the token creation time from Redis TTL information.

    This function retrieves the authentication token from cookies,
    checks its TTL in Redis, and calculates when the token was created.
    Despite the function name, it returns the token creation time, not the expiration time.
    """
    if user is None:
        return None
    try:
        # Get the token from the request
        token = request.cookies.get(FASTAPI_USERS_AUTH_COOKIE_NAME)
        if not token:
            logger.debug("No auth token cookie found")
            return None

        # Get the Redis client
        redis = get_raw_redis_client()
        redis_key = REDIS_AUTH_KEY_PREFIX + token

        # Get the TTL of the token
        ttl = cast(int, redis.ttl(redis_key))
        if ttl <= 0:
            logger.error("Token has expired or doesn't exist in Redis")
            return None

        # Calculate the creation time based on TTL and session expiry
        # Current time minus (total session length minus remaining TTL)
        current_time = datetime.now(timezone.utc)
        token_creation_time = current_time - timedelta(
            seconds=(SESSION_EXPIRE_TIME_SECONDS - ttl)
        )

        return token_creation_time

    except Exception as e:
        logger.error(f"Error retrieving token expiration from Redis: {e}")
        return None


def get_current_token_creation(
    user: User | None, db_session: Session
) -> datetime | None:
    if user is None:
        return None

    access_token = get_latest_access_token_for_user(user.id, db_session)
    if access_token:
        return access_token.created_at
    else:
        logger.error("No AccessToken found for user")
        return None


@router.get("/me")
def verify_user_logged_in(
    request: Request,
    user: User | None = Depends(optional_user),
    db_session: Session = Depends(get_session),
) -> UserInfo:
    tenant_id = get_current_tenant_id()

    # NOTE: this does not use `current_user` / `current_admin_user` because we don't want
    # to enforce user verification here - the frontend always wants to get the info about
    # the current user regardless of if they are currently verified
    if user is None:
        # if auth type is disabled, return a dummy user with preferences from
        # the key-value store
        if AUTH_TYPE == AuthType.DISABLED:
            store = get_kv_store()
            return fetch_no_auth_user(store)
        if anonymous_user_enabled(tenant_id=tenant_id):
            store = get_kv_store()
            return fetch_no_auth_user(store, anonymous_user_enabled=True)
        raise BasicAuthenticationError(detail="User Not Authenticated")

    if user.oidc_expiry and user.oidc_expiry < datetime.now(timezone.utc):
        raise BasicAuthenticationError(
            detail="Access denied. User's OIDC token has expired.",
        )

    token_created_at = (
        get_current_auth_token_creation_redis(user, request)
        if AUTH_BACKEND == AuthBackend.REDIS
        else get_current_token_creation(user, db_session)
    )

    team_name = fetch_ee_implementation_or_noop(
        "onyx.server.tenants.user_mapping", "get_tenant_id_for_email", None
    )(user.email)

    new_tenant: TenantSnapshot | None = None
    tenant_invitation: TenantSnapshot | None = None

    if MULTI_TENANT:
        if team_name != get_current_tenant_id():
            user_count = fetch_ee_implementation_or_noop(
                "onyx.server.tenants.user_mapping", "get_tenant_count", None
            )(team_name)
            new_tenant = TenantSnapshot(tenant_id=team_name, number_of_users=user_count)

        tenant_invitation = fetch_ee_implementation_or_noop(
            "onyx.server.tenants.user_mapping", "get_tenant_invitation", None
        )(user.email)

    super_users_list = cast(
        list[str],
        fetch_versioned_implementation_with_fallback(
            "onyx.configs.app_configs",
            "SUPER_USERS",
            [],
        ),
    )
    user_info = UserInfo.from_model(
        user,
        current_token_created_at=token_created_at,
        expiry_length=SESSION_EXPIRE_TIME_SECONDS,
        is_cloud_superuser=user.email in super_users_list,
        team_name=team_name,
        tenant_info=TenantInfo(
            new_tenant=new_tenant,
            invitation=tenant_invitation,
        ),
    )

    return user_info


"""APIs to adjust user preferences"""


@router.patch("/temperature-override-enabled")
def update_user_temperature_override_enabled_api(
    temperature_override_enabled: bool,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    if user is None:
        if AUTH_TYPE == AuthType.DISABLED:
            store = get_kv_store()
            no_auth_user = fetch_no_auth_user(store)
            no_auth_user.preferences.temperature_override_enabled = (
                temperature_override_enabled
            )
            set_no_auth_user_preferences(store, no_auth_user.preferences)
            return
        else:
            raise RuntimeError("This should never happen")

    update_user_temperature_override_enabled(
        user.id, temperature_override_enabled, db_session
    )


class ChosenDefaultModelRequest(BaseModel):
    default_model: str | None = None


@router.patch("/shortcut-enabled")
def update_user_shortcut_enabled_api(
    shortcut_enabled: bool,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    if user is None:
        if AUTH_TYPE == AuthType.DISABLED:
            store = get_kv_store()
            no_auth_user = fetch_no_auth_user(store)
            no_auth_user.preferences.shortcut_enabled = shortcut_enabled
            set_no_auth_user_preferences(store, no_auth_user.preferences)
            return
        else:
            raise RuntimeError("This should never happen")

    update_user_shortcut_enabled(user.id, shortcut_enabled, db_session)


@router.patch("/auto-scroll")
def update_user_auto_scroll_api(
    request: AutoScrollRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    if user is None:
        if AUTH_TYPE == AuthType.DISABLED:
            store = get_kv_store()
            no_auth_user = fetch_no_auth_user(store)
            no_auth_user.preferences.auto_scroll = request.auto_scroll
            set_no_auth_user_preferences(store, no_auth_user.preferences)
            return
        else:
            raise RuntimeError("This should never happen")

    update_user_auto_scroll(user.id, request.auto_scroll, db_session)


@router.patch("/user/default-model")
def update_user_default_model_api(
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

    update_user_default_model(user.id, request.default_model, db_session)


@router.patch("/user/personalization")
def update_user_personalization_api(
    request: PersonalizationUpdateRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    if user is None:
        if AUTH_TYPE == AuthType.DISABLED:
            store = get_kv_store()
            no_auth_user = fetch_no_auth_user(store)
            personalization = no_auth_user.personalization

            if request.name is not None:
                personalization.name = request.name
            if request.role is not None:
                personalization.role = request.role
            if request.use_memories is not None:
                personalization.use_memories = request.use_memories
            if request.memories is not None:
                personalization.memories = request.memories

            set_no_auth_user_personalization(store, personalization)
            return
        else:
            raise RuntimeError("This should never happen")

    new_name = request.name if request.name is not None else user.personal_name
    new_role = request.role if request.role is not None else user.personal_role
    current_use_memories = user.use_memories
    new_use_memories = (
        request.use_memories
        if request.use_memories is not None
        else current_use_memories
    )
    existing_memories = [memory.memory_text for memory in user.memories]
    new_memories = (
        request.memories if request.memories is not None else existing_memories
    )

    update_user_personalization(
        user.id,
        personal_name=new_name,
        personal_role=new_role,
        use_memories=new_use_memories,
        memories=new_memories,
        db_session=db_session,
    )


class ReorderPinnedAssistantsRequest(BaseModel):
    ordered_assistant_ids: list[int]


@router.patch("/user/pinned-assistants")
def update_user_pinned_assistants_api(
    request: ReorderPinnedAssistantsRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    ordered_assistant_ids = request.ordered_assistant_ids

    if user is None:
        if AUTH_TYPE == AuthType.DISABLED:
            store = get_kv_store()
            no_auth_user = fetch_no_auth_user(store)
            no_auth_user.preferences.pinned_assistants = ordered_assistant_ids
            set_no_auth_user_preferences(store, no_auth_user.preferences)
            return
        else:
            raise RuntimeError("This should never happen")

    update_user_pinned_assistants(user.id, ordered_assistant_ids, db_session)


class ChosenAssistantsRequest(BaseModel):
    chosen_assistants: list[int]


def update_assistant_visibility(
    preferences: UserPreferences, assistant_id: int, show: bool
) -> UserPreferences:
    visible_assistants = preferences.visible_assistants or []
    hidden_assistants = preferences.hidden_assistants or []

    if show:
        if assistant_id not in visible_assistants:
            visible_assistants.append(assistant_id)
        if assistant_id in hidden_assistants:
            hidden_assistants.remove(assistant_id)
    else:
        if assistant_id in visible_assistants:
            visible_assistants.remove(assistant_id)
        if assistant_id not in hidden_assistants:
            hidden_assistants.append(assistant_id)

    preferences.visible_assistants = visible_assistants
    preferences.hidden_assistants = hidden_assistants
    return preferences


@router.patch("/user/assistant-list/update/{assistant_id}")
def update_user_assistant_visibility_api(
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
            updated_preferences = update_assistant_visibility(
                preferences, assistant_id, show
            )
            if updated_preferences.chosen_assistants is not None:
                updated_preferences.chosen_assistants.append(assistant_id)

            set_no_auth_user_preferences(store, updated_preferences)
            return
        else:
            raise RuntimeError("This should never happen")

    user_preferences = UserInfo.from_model(user).preferences
    updated_preferences = update_assistant_visibility(
        user_preferences, assistant_id, show
    )
    if updated_preferences.chosen_assistants is not None:
        updated_preferences.chosen_assistants.append(assistant_id)
    update_user_assistant_visibility(
        user.id,
        updated_preferences.hidden_assistants,
        updated_preferences.visible_assistants,
        updated_preferences.chosen_assistants,
        db_session,
    )


@router.get("/user/assistant/preferences")
def get_user_assistant_preferences(
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UserSpecificAssistantPreferences | None:
    """Fetch all assistant preferences for the user."""
    if user is None:
        if AUTH_TYPE == AuthType.DISABLED:
            store = get_kv_store()
            no_auth_user = fetch_no_auth_user(store)
            return no_auth_user.preferences.assistant_specific_configs
        else:
            raise RuntimeError("This should never happen")

    assistant_specific_configs = get_all_user_assistant_specific_configs(
        user.id, db_session
    )
    return {
        config.assistant_id: UserSpecificAssistantPreference(
            disabled_tool_ids=config.disabled_tool_ids
        )
        for config in assistant_specific_configs
    }


@router.patch("/user/assistant/{assistant_id}/preferences")
def update_assistant_preferences_for_user_api(
    assistant_id: int,
    new_assistant_preference: UserSpecificAssistantPreference,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    if user is None:
        if AUTH_TYPE == AuthType.DISABLED:
            store = get_kv_store()
            no_auth_user = fetch_no_auth_user(store)
            if no_auth_user.preferences.assistant_specific_configs is None:
                no_auth_user.preferences.assistant_specific_configs = {}

            no_auth_user.preferences.assistant_specific_configs[assistant_id] = (
                new_assistant_preference
            )
            set_no_auth_user_preferences(store, no_auth_user.preferences)
            return
        else:
            raise RuntimeError("This should never happen")

    update_assistant_preferences(
        assistant_id, user.id, new_assistant_preference, db_session
    )
    db_session.commit()


@router.get("/user/files/recent")
def get_recent_files(
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[UserFileSnapshot]:
    user_id = user.id if user is not None else None
    user_files = (
        db_session.query(UserFile)
        .filter(UserFile.user_id == user_id)
        .filter(UserFile.status != UserFileStatus.FAILED)
        .filter(UserFile.status != UserFileStatus.DELETING)
        .order_by(UserFile.last_accessed_at.desc())
        .all()
    )

    return [UserFileSnapshot.from_model(user_file) for user_file in user_files]
