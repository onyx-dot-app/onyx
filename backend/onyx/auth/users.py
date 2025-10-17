import json
import random
import secrets
import string
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import cast
from typing import Dict
from typing import List
from typing import Optional
from typing import Protocol
from typing import Tuple
from typing import TypeVar

import jwt
from email_validator import EmailNotValidError
from email_validator import EmailUndeliverableError
from email_validator import validate_email
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi import Response
from fastapi import status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users import BaseUserManager
from fastapi_users import exceptions
from fastapi_users import FastAPIUsers
from fastapi_users import models
from fastapi_users import schemas
from fastapi_users import UUIDIDMixin
from fastapi_users.authentication import AuthenticationBackend
from fastapi_users.authentication import CookieTransport
from fastapi_users.authentication import RedisStrategy
from fastapi_users.authentication import Strategy
from fastapi_users.authentication.strategy.db import AccessTokenDatabase
from fastapi_users.authentication.strategy.db import DatabaseStrategy
from fastapi_users.exceptions import UserAlreadyExists
from fastapi_users.jwt import decode_jwt
from fastapi_users.jwt import generate_jwt
from fastapi_users.jwt import SecretType
from fastapi_users.manager import UserManagerDependency
from fastapi_users.openapi import OpenAPIResponseType
from fastapi_users.router.common import ErrorCode
from fastapi_users.router.common import ErrorModel
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from httpx_oauth.integrations.fastapi import OAuth2AuthorizeCallback
from httpx_oauth.oauth2 import BaseOAuth2
from httpx_oauth.oauth2 import OAuth2Token
from pydantic import BaseModel
from sqlalchemy import nulls_last
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from onyx.auth.api_key import get_hashed_api_key_from_request
from onyx.auth.email_utils import send_forgot_password_email
from onyx.auth.email_utils import send_user_verification_email
from onyx.auth.invited_users import get_invited_users
from onyx.auth.invited_users import remove_user_from_invited_users
from onyx.auth.jwt import verify_jwt_token
from onyx.auth.schemas import AuthBackend
from onyx.auth.schemas import UserCreate
from onyx.auth.schemas import UserRole
from onyx.auth.schemas import UserUpdateWithRole
from onyx.configs.app_configs import AUTH_BACKEND
from onyx.configs.app_configs import AUTH_COOKIE_EXPIRE_TIME_SECONDS
from onyx.configs.app_configs import AUTH_TYPE
from onyx.configs.app_configs import DISABLE_AUTH
from onyx.configs.app_configs import EMAIL_CONFIGURED
from onyx.configs.app_configs import JWT_PUBLIC_KEY_URL
from onyx.configs.app_configs import PASSWORD_MAX_LENGTH
from onyx.configs.app_configs import PASSWORD_MIN_LENGTH
from onyx.configs.app_configs import PASSWORD_REQUIRE_DIGIT
from onyx.configs.app_configs import PASSWORD_REQUIRE_LOWERCASE
from onyx.configs.app_configs import PASSWORD_REQUIRE_SPECIAL_CHAR
from onyx.configs.app_configs import PASSWORD_REQUIRE_UPPERCASE
from onyx.configs.app_configs import REDIS_AUTH_KEY_PREFIX
from onyx.configs.app_configs import REQUIRE_EMAIL_VERIFICATION
from onyx.configs.app_configs import SESSION_EXPIRE_TIME_SECONDS
from onyx.configs.app_configs import TRACK_EXTERNAL_IDP_EXPIRY
from onyx.configs.app_configs import USER_AUTH_SECRET
from onyx.configs.app_configs import VALID_EMAIL_DOMAINS
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.configs.constants import ANONYMOUS_USER_COOKIE_NAME
from onyx.configs.constants import AuthType
from onyx.configs.constants import DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN
from onyx.configs.constants import DANSWER_API_KEY_PREFIX
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.configs.constants import MilestoneRecordType
from onyx.configs.constants import OnyxRedisLocks
from onyx.configs.constants import PASSWORD_SPECIAL_CHARS
from onyx.configs.constants import UNNAMED_KEY_PLACEHOLDER
from onyx.db.api_key import fetch_user_for_api_key
from onyx.db.auth import get_access_token_db
from onyx.db.auth import get_default_admin_user_emails
from onyx.db.auth import get_user_count
from onyx.db.auth import get_user_db
from onyx.db.auth import SQLAlchemyUserAdminDB
from onyx.db.engine.async_sql_engine import get_async_session
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import AccessToken
from onyx.db.models import OAuthAccount
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.db.saml import get_saml_account
from onyx.db.users import get_user_by_email
from onyx.redis.redis_pool import get_async_redis_connection
from onyx.redis.redis_pool import get_redis_client
from onyx.server.utils import BasicAuthenticationError
from onyx.utils.logger import setup_logger
from onyx.utils.secrets import extract_hashed_cookie
from onyx.utils.telemetry import create_milestone_and_report
from onyx.utils.telemetry import optional_telemetry
from onyx.utils.telemetry import RecordType
from onyx.utils.timing import log_function_time
from onyx.utils.url import add_url_params
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop
from shared_configs.configs import async_return_default_schema
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


def is_user_admin(user: User | None) -> bool:
    if AUTH_TYPE == AuthType.DISABLED:
        return True
    if user and user.role == UserRole.ADMIN:
        return True
    return False


def verify_auth_setting() -> None:
    if AUTH_TYPE == AuthType.CLOUD:
        raise ValueError(
            f"{AUTH_TYPE.value} is not a valid auth type for self-hosted deployments."
        )
    logger.notice(f"Using Auth Type: {AUTH_TYPE.value}")


def get_display_email(email: str | None, space_less: bool = False) -> str:
    if email and email.endswith(DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN):
        name = email.split("@")[0]
        if name == DANSWER_API_KEY_PREFIX + UNNAMED_KEY_PLACEHOLDER:
            return "Unnamed API Key"

        if space_less:
            return name

        return name.replace("API_KEY__", "API Key: ")

    return email or ""


def generate_password() -> str:
    lowercase_letters = string.ascii_lowercase
    uppercase_letters = string.ascii_uppercase
    digits = string.digits
    special_characters = string.punctuation

    # Ensure at least one of each required character type
    password = [
        secrets.choice(uppercase_letters),
        secrets.choice(digits),
        secrets.choice(special_characters),
    ]

    # Fill the rest with a mix of characters
    remaining_length = 12 - len(password)
    all_characters = lowercase_letters + uppercase_letters + digits + special_characters
    password.extend(secrets.choice(all_characters) for _ in range(remaining_length))

    # Shuffle the password to randomize the position of the required characters
    random.shuffle(password)

    return "".join(password)


def user_needs_to_be_verified() -> bool:
    if AUTH_TYPE == AuthType.BASIC or AUTH_TYPE == AuthType.CLOUD:
        return REQUIRE_EMAIL_VERIFICATION

    # For other auth types, if the user is authenticated it's assumed that
    # the user is already verified via the external IDP
    return False


def anonymous_user_enabled(*, tenant_id: str | None = None) -> bool:
    redis_client = get_redis_client(tenant_id=tenant_id)
    value = redis_client.get(OnyxRedisLocks.ANONYMOUS_USER_ENABLED)

    if value is None:
        return False

    assert isinstance(value, bytes)
    return int(value.decode("utf-8")) == 1


def verify_email_is_invited(email: str) -> None:
    whitelist = get_invited_users()
    if not whitelist:
        return

    if not email:
        raise PermissionError("Email must be specified")

    try:
        email_info = validate_email(email)
    except EmailUndeliverableError:
        raise PermissionError("Email is not valid")

    for email_whitelist in whitelist:
        try:
            # normalized emails are now being inserted into the db
            # we can remove this normalization on read after some time has passed
            email_info_whitelist = validate_email(email_whitelist)
        except EmailNotValidError:
            continue

        # oddly, normalization does not include lowercasing the user part of the
        # email address ... which we want to allow
        if email_info.normalized.lower() == email_info_whitelist.normalized.lower():
            return

    raise PermissionError("User not on allowed user whitelist")


def verify_email_in_whitelist(email: str, tenant_id: str) -> None:
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        if not get_user_by_email(email, db_session):
            verify_email_is_invited(email)


def verify_email_domain(email: str) -> None:
    if VALID_EMAIL_DOMAINS:
        if email.count("@") != 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is not valid",
            )
        domain = email.split("@")[-1].lower()
        if domain not in VALID_EMAIL_DOMAINS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email domain is not valid",
            )


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = USER_AUTH_SECRET
    verification_token_secret = USER_AUTH_SECRET
    verification_token_lifetime_seconds = AUTH_COOKIE_EXPIRE_TIME_SECONDS
    user_db: SQLAlchemyUserDatabase[User, uuid.UUID]

    async def get_by_email(self, user_email: str) -> User:
        tenant_id = fetch_ee_implementation_or_noop(
            "onyx.server.tenants.user_mapping", "get_tenant_id_for_email", None
        )(user_email)
        async with get_async_session_context_manager(tenant_id) as db_session:
            if MULTI_TENANT:
                tenant_user_db = SQLAlchemyUserAdminDB[User, uuid.UUID](
                    db_session, User, OAuthAccount
                )
                user = await tenant_user_db.get_by_email(user_email)
            else:
                user = await self.user_db.get_by_email(user_email)

        if not user:
            raise exceptions.UserNotExists()

        return user

    async def create(
        self,
        user_create: schemas.UC | UserCreate,
        safe: bool = False,
        request: Optional[Request] = None,
    ) -> User:
        # We verify the password here to make sure it's valid before we proceed
        await self.validate_password(
            user_create.password, cast(schemas.UC, user_create)
        )

        user_count: int | None = None
        referral_source = (
            request.cookies.get("referral_source", None)
            if request is not None
            else None
        )

        tenant_id = await fetch_ee_implementation_or_noop(
            "onyx.server.tenants.provisioning",
            "get_or_provision_tenant",
            async_return_default_schema,
        )(
            email=user_create.email,
            referral_source=referral_source,
            request=request,
        )
        user: User

        token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
        try:
            async with get_async_session_context_manager(tenant_id) as db_session:
                verify_email_is_invited(user_create.email)
                verify_email_domain(user_create.email)
                if MULTI_TENANT:
                    tenant_user_db = SQLAlchemyUserAdminDB[User, uuid.UUID](
                        db_session, User, OAuthAccount
                    )
                    self.user_db = tenant_user_db

                if hasattr(user_create, "role"):
                    user_create.role = UserRole.BASIC

                    user_count = await get_user_count()
                    if (
                        user_count == 0
                        or user_create.email in get_default_admin_user_emails()
                    ):
                        user_create.role = UserRole.ADMIN

                user_created = False
                try:
                    user = await super().create(
                        user_create, safe=safe, request=request
                    )  # type: ignore
                    user_created = True
                except exceptions.UserAlreadyExists:
                    user = await self.get_by_email(user_create.email)

                    # we must use the existing user in the session if it matches
                    # the user we just got by email. Note that this only applies
                    # to multi-tenant, due to the overwriting of the user_db
                    if MULTI_TENANT:
                        user_by_session = await db_session.get(User, user.id)
                        if user_by_session:
                            user = user_by_session

                    # Handle case where user has used product outside of web and is now creating an account through web
                    if (
                        user.role.is_web_login()
                        or not isinstance(user_create, UserCreate)
                        or not user_create.role.is_web_login()
                    ):
                        raise exceptions.UserAlreadyExists()

                    user_update = UserUpdateWithRole(
                        password=user_create.password,
                        is_verified=user_create.is_verified,
                        role=user_create.role,
                    )
                    user = await self.update(user_update, user)
                if user_created:
                    await self._assign_default_pinned_assistants(user, db_session)
                remove_user_from_invited_users(user_create.email)
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        return user

    async def _assign_default_pinned_assistants(
        self, user: User, db_session: AsyncSession
    ) -> None:
        if user.pinned_assistants is not None:
            return

        result = await db_session.execute(
            select(Persona.id)
            .where(
                Persona.is_default_persona.is_(True),
                Persona.is_public.is_(True),
                Persona.is_visible.is_(True),
                Persona.deleted.is_(False),
            )
            .order_by(
                nulls_last(Persona.display_priority.asc()),
                Persona.id.asc(),
            )
        )
        default_persona_ids = list(result.scalars().all())
        if not default_persona_ids:
            return

        await self.user_db.update(
            user,
            {"pinned_assistants": default_persona_ids},
        )
        user.pinned_assistants = default_persona_ids

    async def validate_password(self, password: str, _: schemas.UC | models.UP) -> None:
        # Validate password according to configurable security policy (defined via environment variables)
        if len(password) < PASSWORD_MIN_LENGTH:
            raise exceptions.InvalidPasswordException(
                reason=f"Password must be at least {PASSWORD_MIN_LENGTH} characters long."
            )
        if len(password) > PASSWORD_MAX_LENGTH:
            raise exceptions.InvalidPasswordException(
                reason=f"Password must not exceed {PASSWORD_MAX_LENGTH} characters."
            )
        if PASSWORD_REQUIRE_UPPERCASE and not any(char.isupper() for char in password):
            raise exceptions.InvalidPasswordException(
                reason="Password must contain at least one uppercase letter."
            )
        if PASSWORD_REQUIRE_LOWERCASE and not any(char.islower() for char in password):
            raise exceptions.InvalidPasswordException(
                reason="Password must contain at least one lowercase letter."
            )
        if PASSWORD_REQUIRE_DIGIT and not any(char.isdigit() for char in password):
            raise exceptions.InvalidPasswordException(
                reason="Password must contain at least one number."
            )
        if PASSWORD_REQUIRE_SPECIAL_CHAR and not any(
            char in PASSWORD_SPECIAL_CHARS for char in password
        ):
            raise exceptions.InvalidPasswordException(
                reason="Password must contain at least one special character from the following set: "
                f"{PASSWORD_SPECIAL_CHARS}."
            )
        return

    @log_function_time(print_only=True)
    async def oauth_callback(
        self,
        oauth_name: str,
        access_token: str,
        account_id: str,
        account_email: str,
        expires_at: Optional[int] = None,
        refresh_token: Optional[str] = None,
        request: Optional[Request] = None,
        *,
        associate_by_email: bool = False,
        is_verified_by_default: bool = False,
    ) -> User:
        referral_source = (
            getattr(request.state, "referral_source", None) if request else None
        )

        tenant_id = await fetch_ee_implementation_or_noop(
            "onyx.server.tenants.provisioning",
            "get_or_provision_tenant",
            async_return_default_schema,
        )(
            email=account_email,
            referral_source=referral_source,
            request=request,
        )

        if not tenant_id:
            raise HTTPException(status_code=401, detail="User not found")

        # Proceed with the tenant context
        token = None
        async with get_async_session_context_manager(tenant_id) as db_session:
            token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

            verify_email_in_whitelist(account_email, tenant_id)
            verify_email_domain(account_email)

            # NOTE(rkuo): If this UserManager is instantiated per connection
            # should we even be doing this here?
            if MULTI_TENANT:
                tenant_user_db = SQLAlchemyUserAdminDB[User, uuid.UUID](
                    db_session, User, OAuthAccount
                )
                self.user_db = tenant_user_db

            oauth_account_dict = {
                "oauth_name": oauth_name,
                "access_token": access_token,
                "account_id": account_id,
                "account_email": account_email,
                "expires_at": expires_at,
                "refresh_token": refresh_token,
            }

            user: User | None = None

            try:
                # Attempt to get user by OAuth account
                user = await self.get_by_oauth_account(oauth_name, account_id)

            except exceptions.UserNotExists:
                try:
                    # Attempt to get user by email
                    user = await self.user_db.get_by_email(account_email)
                    if not associate_by_email:
                        raise exceptions.UserAlreadyExists()

                    # Make sure user is not None before adding OAuth account
                    if user is not None:
                        user = await self.user_db.add_oauth_account(
                            user, oauth_account_dict
                        )
                    else:
                        # This shouldn't happen since get_by_email would raise UserNotExists
                        # but adding as a safeguard
                        raise exceptions.UserNotExists()

                except exceptions.UserNotExists:
                    password = self.password_helper.generate()
                    user_dict = {
                        "email": account_email,
                        "hashed_password": self.password_helper.hash(password),
                        "is_verified": is_verified_by_default,
                    }

                    user = await self.user_db.create(user_dict)
                    await self.user_db.add_oauth_account(user, oauth_account_dict)
                    await self._assign_default_pinned_assistants(user, db_session)
                    await self.on_after_register(user, request)

            else:
                # User exists, update OAuth account if needed
                if user is not None:  # Add explicit check
                    for existing_oauth_account in user.oauth_accounts:
                        if (
                            existing_oauth_account.account_id == account_id
                            and existing_oauth_account.oauth_name == oauth_name
                        ):
                            user = await self.user_db.update_oauth_account(
                                user,
                                # NOTE: OAuthAccount DOES implement the OAuthAccountProtocol
                                # but the type checker doesn't know that :(
                                existing_oauth_account,  # type: ignore
                                oauth_account_dict,
                            )

            # NOTE: Most IdPs have very short expiry times, and we don't want to force the user to
            # re-authenticate that frequently, so by default this is disabled
            if expires_at and TRACK_EXTERNAL_IDP_EXPIRY:
                oidc_expiry = datetime.fromtimestamp(expires_at, tz=timezone.utc)
                await self.user_db.update(
                    user, update_dict={"oidc_expiry": oidc_expiry}
                )

            # Handle case where user has used product outside of web and is now creating an account through web
            if not user.role.is_web_login():
                # We must use the existing user in the session if it matches
                # the user we just got by email/oauth. Note that this only applies
                # to multi-tenant, due to the overwriting of the user_db
                if MULTI_TENANT:
                    if user.id:
                        user_by_session = await db_session.get(User, user.id)
                        if user_by_session:
                            user = user_by_session

                await self.user_db.update(
                    user,
                    {
                        "is_verified": is_verified_by_default,
                        "role": UserRole.BASIC,
                    },
                )

            # this is needed if an organization goes from `TRACK_EXTERNAL_IDP_EXPIRY=true` to `false`
            # otherwise, the oidc expiry will always be old, and the user will never be able to login
            if (
                user.oidc_expiry is not None  # type: ignore
                and not TRACK_EXTERNAL_IDP_EXPIRY
            ):
                await self.user_db.update(user, {"oidc_expiry": None})
                user.oidc_expiry = None  # type: ignore
            remove_user_from_invited_users(user.email)
            if token:
                CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

            return user

    async def on_after_login(
        self,
        user: User,
        request: Optional[Request] = None,
        response: Optional[Response] = None,
    ) -> None:
        try:
            if response and request and ANONYMOUS_USER_COOKIE_NAME in request.cookies:
                response.delete_cookie(
                    ANONYMOUS_USER_COOKIE_NAME,
                    # Ensure cookie deletion doesn't override other cookies by setting the same path/domain
                    path="/",
                    domain=None,
                    secure=WEB_DOMAIN.startswith("https"),
                )
                logger.debug(f"Deleted anonymous user cookie for user {user.email}")
        except Exception:
            logger.exception("Error deleting anonymous user cookie")

    async def on_after_register(
        self, user: User, request: Optional[Request] = None
    ) -> None:
        tenant_id = await fetch_ee_implementation_or_noop(
            "onyx.server.tenants.provisioning",
            "get_or_provision_tenant",
            async_return_default_schema,
        )(
            email=user.email,
            request=request,
        )

        token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
        try:
            user_count = await get_user_count()
            logger.debug(f"Current tenant user count: {user_count}")

            with get_session_with_tenant(tenant_id=tenant_id) as db_session:
                event_type = (
                    MilestoneRecordType.USER_SIGNED_UP
                    if user_count == 1
                    else MilestoneRecordType.MULTIPLE_USERS
                )
                create_milestone_and_report(
                    user=user,
                    distinct_id=user.email,
                    event_type=event_type,
                    properties=None,
                    db_session=db_session,
                )

        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

        logger.debug(f"User {user.id} has registered.")
        optional_telemetry(
            record_type=RecordType.SIGN_UP,
            data={"action": "create"},
            user_id=str(user.id),
        )

    async def on_after_forgot_password(
        self, user: User, token: str, request: Optional[Request] = None
    ) -> None:
        if not EMAIL_CONFIGURED:
            logger.error(
                "Email is not configured. Please configure email in the admin panel"
            )
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Your admin has not enabled this feature.",
            )
        tenant_id = await fetch_ee_implementation_or_noop(
            "onyx.server.tenants.provisioning",
            "get_or_provision_tenant",
            async_return_default_schema,
        )(email=user.email)

        send_forgot_password_email(user.email, tenant_id=tenant_id, token=token)

    async def on_after_request_verify(
        self, user: User, token: str, request: Optional[Request] = None
    ) -> None:
        verify_email_domain(user.email)

        logger.notice(
            f"Verification requested for user {user.id}. Verification token: {token}"
        )
        user_count = await get_user_count()
        send_user_verification_email(
            user.email, token, new_organization=user_count == 1
        )

    @log_function_time(print_only=True)
    async def authenticate(
        self, credentials: OAuth2PasswordRequestForm
    ) -> Optional[User]:
        email = credentials.username

        tenant_id: str | None = None
        try:
            tenant_id = fetch_ee_implementation_or_noop(
                "onyx.server.tenants.provisioning",
                "get_tenant_id_for_email",
                POSTGRES_DEFAULT_SCHEMA,
            )(
                email=email,
            )
        except Exception as e:
            logger.warning(
                f"User attempted to login with invalid credentials: {str(e)}"
            )

        if not tenant_id:
            # User not found in mapping
            self.password_helper.hash(credentials.password)
            return None

        # Create a tenant-specific session
        async with get_async_session_context_manager(tenant_id) as tenant_session:
            tenant_user_db: SQLAlchemyUserDatabase = SQLAlchemyUserDatabase(
                tenant_session, User
            )
            self.user_db = tenant_user_db

            # Proceed with authentication
            try:
                user = await self.get_by_email(email)

            except exceptions.UserNotExists:
                self.password_helper.hash(credentials.password)
                return None

            if not user.role.is_web_login():
                raise BasicAuthenticationError(
                    detail="NO_WEB_LOGIN_AND_HAS_NO_PASSWORD",
                )

            verified, updated_password_hash = self.password_helper.verify_and_update(
                credentials.password, user.hashed_password
            )
            if not verified:
                return None

            if updated_password_hash is not None:
                await self.user_db.update(
                    user, {"hashed_password": updated_password_hash}
                )

            return user

    async def reset_password_as_admin(self, user_id: uuid.UUID) -> str:
        """Admin-only. Generate a random password for a user and return it."""
        user = await self.get(user_id)
        new_password = generate_password()
        await self._update(user, {"password": new_password})
        return new_password

    async def change_password_if_old_matches(
        self, user: User, old_password: str, new_password: str
    ) -> None:
        """
        For normal users to change password if they know the old one.
        Raises 400 if old password doesn't match.
        """
        verified, updated_password_hash = self.password_helper.verify_and_update(
            old_password, user.hashed_password
        )
        if not verified:
            # Raise some HTTPException (or your custom exception) if old password is invalid:
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid current password",
            )

        # If the hash was upgraded behind the scenes, we can keep it before setting the new password:
        if updated_password_hash:
            user.hashed_password = updated_password_hash

        # Now apply and validate the new password
        await self._update(user, {"password": new_password})


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
) -> AsyncGenerator[UserManager, None]:
    yield UserManager(user_db)


cookie_transport = CookieTransport(
    cookie_max_age=SESSION_EXPIRE_TIME_SECONDS,
    cookie_secure=WEB_DOMAIN.startswith("https"),
    cookie_name=FASTAPI_USERS_AUTH_COOKIE_NAME,
)


T = TypeVar("T", covariant=True)
ID = TypeVar("ID", contravariant=True)


# Protocol for strategies that support token refreshing without inheritance.
class RefreshableStrategy(Protocol):
    """Protocol for authentication strategies that support token refreshing."""

    async def refresh_token(self, token: Optional[str], user: Any) -> str:
        """
        Refresh an existing token by extending its lifetime.
        Returns either the same token with extended expiration or a new token.
        """
        ...


class TenantAwareRedisStrategy(RedisStrategy[User, uuid.UUID]):
    """
    A custom strategy that fetches the actual async Redis connection inside each method.
    We do NOT pass a synchronous or "coroutine" redis object to the constructor.
    """

    def __init__(
        self,
        lifetime_seconds: Optional[int] = SESSION_EXPIRE_TIME_SECONDS,
        key_prefix: str = REDIS_AUTH_KEY_PREFIX,
    ):
        self.lifetime_seconds = lifetime_seconds
        self.key_prefix = key_prefix

    async def write_token(self, user: User) -> str:
        redis = await get_async_redis_connection()

        tenant_id = await fetch_ee_implementation_or_noop(
            "onyx.server.tenants.provisioning",
            "get_or_provision_tenant",
            async_return_default_schema,
        )(email=user.email)

        token_data = {
            "sub": str(user.id),
            "tenant_id": tenant_id,
        }
        token = secrets.token_urlsafe()
        await redis.set(
            f"{self.key_prefix}{token}",
            json.dumps(token_data),
            ex=self.lifetime_seconds,
        )
        return token

    async def read_token(
        self, token: Optional[str], user_manager: BaseUserManager[User, uuid.UUID]
    ) -> Optional[User]:
        redis = await get_async_redis_connection()
        token_data_str = await redis.get(f"{self.key_prefix}{token}")
        if not token_data_str:
            return None

        try:
            token_data = json.loads(token_data_str)
            user_id = token_data["sub"]
            parsed_id = user_manager.parse_id(user_id)
            return await user_manager.get(parsed_id)
        except (exceptions.UserNotExists, exceptions.InvalidID, KeyError):
            return None

    async def destroy_token(self, token: str, user: User) -> None:
        """Properly delete the token from async redis."""
        redis = await get_async_redis_connection()
        await redis.delete(f"{self.key_prefix}{token}")

    async def refresh_token(self, token: Optional[str], user: User) -> str:
        """Refresh a token by extending its expiration time in Redis."""
        if token is None:
            # If no token provided, create a new one
            return await self.write_token(user)

        redis = await get_async_redis_connection()
        token_key = f"{self.key_prefix}{token}"

        # Check if token exists
        token_data_str = await redis.get(token_key)
        if not token_data_str:
            # Token not found, create new one
            return await self.write_token(user)

        # Token exists, extend its lifetime
        token_data = json.loads(token_data_str)
        await redis.set(
            token_key,
            json.dumps(token_data),
            ex=self.lifetime_seconds,
        )

        return token


class RefreshableDatabaseStrategy(DatabaseStrategy[User, uuid.UUID, AccessToken]):
    """Database strategy with token refreshing capabilities."""

    def __init__(
        self,
        access_token_db: AccessTokenDatabase[AccessToken],
        lifetime_seconds: Optional[int] = None,
    ):
        super().__init__(access_token_db, lifetime_seconds)
        self._access_token_db = access_token_db

    async def refresh_token(self, token: Optional[str], user: User) -> str:
        """Refresh a token by updating its expiration time in the database."""
        if token is None:
            return await self.write_token(user)

        # Find the token in database
        access_token = await self._access_token_db.get_by_token(token)

        if access_token is None:
            # Token not found, create new one
            return await self.write_token(user)

        # Update expiration time
        new_expires = datetime.now(timezone.utc) + timedelta(
            seconds=float(self.lifetime_seconds or SESSION_EXPIRE_TIME_SECONDS)
        )
        await self._access_token_db.update(access_token, {"expires": new_expires})

        return token


def get_redis_strategy() -> TenantAwareRedisStrategy:
    return TenantAwareRedisStrategy()


def get_database_strategy(
    access_token_db: AccessTokenDatabase[AccessToken] = Depends(get_access_token_db),
) -> RefreshableDatabaseStrategy:
    return RefreshableDatabaseStrategy(
        access_token_db, lifetime_seconds=SESSION_EXPIRE_TIME_SECONDS
    )


if AUTH_BACKEND == AuthBackend.REDIS:
    auth_backend = AuthenticationBackend(
        name="redis", transport=cookie_transport, get_strategy=get_redis_strategy
    )
elif AUTH_BACKEND == AuthBackend.POSTGRES:
    auth_backend = AuthenticationBackend(
        name="postgres", transport=cookie_transport, get_strategy=get_database_strategy
    )
else:
    raise ValueError(f"Invalid auth backend: {AUTH_BACKEND}")


class FastAPIUserWithLogoutRouter(FastAPIUsers[models.UP, models.ID]):
    def get_logout_router(
        self,
        backend: AuthenticationBackend,
        requires_verification: bool = REQUIRE_EMAIL_VERIFICATION,
    ) -> APIRouter:
        """
        Provide a router for logout only for OAuth/OIDC Flows.
        This way the login router does not need to be included
        """
        router = APIRouter()

        get_current_user_token = self.authenticator.current_user_token(
            active=True, verified=requires_verification
        )

        logout_responses: OpenAPIResponseType = {
            **{
                status.HTTP_401_UNAUTHORIZED: {
                    "description": "Missing token or inactive user."
                }
            },
            **backend.transport.get_openapi_logout_responses_success(),
        }

        @router.post(
            "/logout", name=f"auth:{backend.name}.logout", responses=logout_responses
        )
        async def logout(
            user_token: Tuple[models.UP, str] = Depends(get_current_user_token),
            strategy: Strategy[models.UP, models.ID] = Depends(backend.get_strategy),
        ) -> Response:
            user, token = user_token
            return await backend.logout(strategy, user, token)

        return router

    def get_refresh_router(
        self,
        backend: AuthenticationBackend,
        requires_verification: bool = REQUIRE_EMAIL_VERIFICATION,
    ) -> APIRouter:
        """
        Provide a router for session token refreshing.
        """
        # Import the oauth_refresher here to avoid circular imports
        from onyx.auth.oauth_refresher import check_and_refresh_oauth_tokens

        router = APIRouter()

        get_current_user_token = self.authenticator.current_user_token(
            active=True, verified=requires_verification
        )

        refresh_responses: OpenAPIResponseType = {
            **{
                status.HTTP_401_UNAUTHORIZED: {
                    "description": "Missing token or inactive user."
                }
            },
            **backend.transport.get_openapi_login_responses_success(),
        }

        @router.post(
            "/refresh", name=f"auth:{backend.name}.refresh", responses=refresh_responses
        )
        async def refresh(
            user_token: Tuple[models.UP, str] = Depends(get_current_user_token),
            strategy: Strategy[models.UP, models.ID] = Depends(backend.get_strategy),
            user_manager: BaseUserManager[models.UP, models.ID] = Depends(
                get_user_manager
            ),
            db_session: AsyncSession = Depends(get_async_session),
        ) -> Response:
            try:
                user, token = user_token
                logger.info(f"Processing token refresh request for user {user.email}")

                # Check if user has OAuth accounts that need refreshing
                await check_and_refresh_oauth_tokens(
                    user=cast(User, user),
                    db_session=db_session,
                    user_manager=cast(Any, user_manager),
                )

                # Check if strategy supports refreshing
                supports_refresh = hasattr(strategy, "refresh_token") and callable(
                    getattr(strategy, "refresh_token")
                )

                if supports_refresh:
                    try:
                        refresh_method = getattr(strategy, "refresh_token")
                        new_token = await refresh_method(token, user)
                        logger.info(
                            f"Successfully refreshed session token for user {user.email}"
                        )
                        return await backend.transport.get_login_response(new_token)
                    except Exception as e:
                        logger.error(f"Error refreshing session token: {str(e)}")
                        # Fallback to logout and login if refresh fails
                        await backend.logout(strategy, user, token)
                        return await backend.login(strategy, user)

                # Fallback: logout and login again
                logger.info(
                    "Strategy doesn't support refresh - using logout/login flow"
                )
                await backend.logout(strategy, user, token)
                return await backend.login(strategy, user)
            except Exception as e:
                logger.error(f"Unexpected error in refresh endpoint: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Token refresh failed: {str(e)}",
                )

        return router


fastapi_users = FastAPIUserWithLogoutRouter[User, uuid.UUID](
    get_user_manager, [auth_backend]
)


# NOTE: verified=REQUIRE_EMAIL_VERIFICATION is not used here since we
# take care of that in `double_check_user` ourself. This is needed, since
# we want the /me endpoint to still return a user even if they are not
# yet verified, so that the frontend knows they exist
optional_fastapi_current_user = fastapi_users.current_user(active=True, optional=True)


async def _check_for_saml_and_jwt(
    request: Request,
    user: User | None,
    async_db_session: AsyncSession,
) -> User | None:
    # Check if the user has a session cookie from SAML
    if AUTH_TYPE == AuthType.SAML:
        saved_cookie = extract_hashed_cookie(request)

        if saved_cookie:
            saml_account = await get_saml_account(
                cookie=saved_cookie, async_db_session=async_db_session
            )
            user = saml_account.user if saml_account else None

    # If user is still None, check for JWT in Authorization header
    if user is None and JWT_PUBLIC_KEY_URL is not None:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer ") :].strip()
            user = await verify_jwt_token(token, async_db_session)

    return user


async def optional_user(
    request: Request,
    async_db_session: AsyncSession = Depends(get_async_session),
    user: User | None = Depends(optional_fastapi_current_user),
) -> User | None:
    user = await _check_for_saml_and_jwt(request, user, async_db_session)

    # check if an API key is present
    if user is None:
        try:
            hashed_api_key = get_hashed_api_key_from_request(request)
        except ValueError:
            hashed_api_key = None
        if hashed_api_key:
            user = await fetch_user_for_api_key(hashed_api_key, async_db_session)

    return user


async def double_check_user(
    user: User | None,
    optional: bool = DISABLE_AUTH,
    include_expired: bool = False,
    allow_anonymous_access: bool = False,
) -> User | None:
    if optional:
        return user

    if user is not None:
        # If user attempted to authenticate, verify them, do not default
        # to anonymous access if it fails.
        if user_needs_to_be_verified() and not user.is_verified:
            raise BasicAuthenticationError(
                detail="Access denied. User is not verified.",
            )

        if (
            user.oidc_expiry
            and user.oidc_expiry < datetime.now(timezone.utc)
            and not include_expired
        ):
            raise BasicAuthenticationError(
                detail="Access denied. User's OIDC token has expired.",
            )

        return user

    if allow_anonymous_access:
        return None

    raise BasicAuthenticationError(
        detail="Access denied. User is not authenticated.",
    )


async def current_user_with_expired_token(
    user: User | None = Depends(optional_user),
) -> User | None:
    return await double_check_user(user, include_expired=True)


async def current_limited_user(
    user: User | None = Depends(optional_user),
) -> User | None:
    return await double_check_user(user)


async def current_chat_accessible_user(
    user: User | None = Depends(optional_user),
) -> User | None:
    tenant_id = get_current_tenant_id()

    return await double_check_user(
        user, allow_anonymous_access=anonymous_user_enabled(tenant_id=tenant_id)
    )


async def current_user(
    user: User | None = Depends(optional_user),
) -> User | None:
    user = await double_check_user(user)
    if not user:
        return None

    if user.role == UserRole.LIMITED:
        raise BasicAuthenticationError(
            detail="Access denied. User role is LIMITED. BASIC or higher permissions are required.",
        )
    return user


async def current_curator_or_admin_user(
    user: User | None = Depends(current_user),
) -> User | None:
    if DISABLE_AUTH:
        return None

    if not user or not hasattr(user, "role"):
        raise BasicAuthenticationError(
            detail="Access denied. User is not authenticated or lacks role information.",
        )

    allowed_roles = {UserRole.GLOBAL_CURATOR, UserRole.CURATOR, UserRole.ADMIN}
    if user.role not in allowed_roles:
        raise BasicAuthenticationError(
            detail="Access denied. User is not a curator or admin.",
        )

    return user


async def current_admin_user(user: User | None = Depends(current_user)) -> User | None:
    if DISABLE_AUTH:
        return None

    if not user or not hasattr(user, "role") or user.role != UserRole.ADMIN:
        raise BasicAuthenticationError(
            detail="Access denied. User must be an admin to perform this action.",
        )

    return user


def get_default_admin_user_emails_() -> list[str]:
    # No default seeding available for Onyx MIT
    return []


STATE_TOKEN_AUDIENCE = "fastapi-users:oauth-state"


class OAuth2AuthorizeResponse(BaseModel):
    authorization_url: str


def generate_state_token(
    data: Dict[str, str], secret: SecretType, lifetime_seconds: int = 3600
) -> str:
    data["aud"] = STATE_TOKEN_AUDIENCE

    return generate_jwt(data, secret, lifetime_seconds)


# refer to https://github.com/fastapi-users/fastapi-users/blob/42ddc241b965475390e2bce887b084152ae1a2cd/fastapi_users/fastapi_users.py#L91
def create_onyx_oauth_router(
    oauth_client: BaseOAuth2,
    backend: AuthenticationBackend,
    state_secret: SecretType,
    redirect_url: Optional[str] = None,
    associate_by_email: bool = False,
    is_verified_by_default: bool = False,
) -> APIRouter:
    return get_oauth_router(
        oauth_client,
        backend,
        get_user_manager,
        state_secret,
        redirect_url,
        associate_by_email,
        is_verified_by_default,
    )


def get_oauth_router(
    oauth_client: BaseOAuth2,
    backend: AuthenticationBackend,
    get_user_manager: UserManagerDependency[models.UP, models.ID],
    state_secret: SecretType,
    redirect_url: Optional[str] = None,
    associate_by_email: bool = False,
    is_verified_by_default: bool = False,
) -> APIRouter:
    """Generate a router with the OAuth routes."""
    router = APIRouter()
    callback_route_name = f"oauth:{oauth_client.name}.{backend.name}.callback"

    if redirect_url is not None:
        oauth2_authorize_callback = OAuth2AuthorizeCallback(
            oauth_client,
            redirect_url=redirect_url,
        )
    else:
        oauth2_authorize_callback = OAuth2AuthorizeCallback(
            oauth_client,
            route_name=callback_route_name,
        )

    @router.get(
        "/authorize",
        name=f"oauth:{oauth_client.name}.{backend.name}.authorize",
        response_model=OAuth2AuthorizeResponse,
    )
    async def authorize(
        request: Request,
        scopes: List[str] = Query(None),
    ) -> OAuth2AuthorizeResponse:
        referral_source = request.cookies.get("referral_source", None)

        if redirect_url is not None:
            authorize_redirect_url = redirect_url
        else:
            authorize_redirect_url = str(request.url_for(callback_route_name))

        next_url = request.query_params.get("next", "/")

        state_data: Dict[str, str] = {
            "next_url": next_url,
            "referral_source": referral_source or "default_referral",
        }
        state = generate_state_token(state_data, state_secret)

        # Get the basic authorization URL
        authorization_url = await oauth_client.get_authorization_url(
            authorize_redirect_url,
            state,
            scopes,
        )

        # For Google OAuth, add parameters to request refresh tokens
        if oauth_client.name == "google":
            authorization_url = add_url_params(
                authorization_url, {"access_type": "offline", "prompt": "consent"}
            )

        return OAuth2AuthorizeResponse(authorization_url=authorization_url)

    @log_function_time(print_only=True)
    @router.get(
        "/callback",
        name=callback_route_name,
        description="The response varies based on the authentication backend used.",
        responses={
            status.HTTP_400_BAD_REQUEST: {
                "model": ErrorModel,
                "content": {
                    "application/json": {
                        "examples": {
                            "INVALID_STATE_TOKEN": {
                                "summary": "Invalid state token.",
                                "value": None,
                            },
                            ErrorCode.LOGIN_BAD_CREDENTIALS: {
                                "summary": "User is inactive.",
                                "value": {"detail": ErrorCode.LOGIN_BAD_CREDENTIALS},
                            },
                        }
                    }
                },
            },
        },
    )
    async def callback(
        request: Request,
        access_token_state: Tuple[OAuth2Token, str] = Depends(
            oauth2_authorize_callback
        ),
        user_manager: BaseUserManager[models.UP, models.ID] = Depends(get_user_manager),
        strategy: Strategy[models.UP, models.ID] = Depends(backend.get_strategy),
    ) -> RedirectResponse:
        token, state = access_token_state
        account_id, account_email = await oauth_client.get_id_email(
            token["access_token"]
        )

        if account_email is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ErrorCode.OAUTH_NOT_AVAILABLE_EMAIL,
            )

        try:
            state_data = decode_jwt(state, state_secret, [STATE_TOKEN_AUDIENCE])
        except jwt.DecodeError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)

        next_url = state_data.get("next_url", "/")
        referral_source = state_data.get("referral_source", None)
        try:
            tenant_id = fetch_ee_implementation_or_noop(
                "onyx.server.tenants.user_mapping", "get_tenant_id_for_email", None
            )(account_email)
        except exceptions.UserNotExists:
            tenant_id = None

        request.state.referral_source = referral_source

        # Proceed to authenticate or create the user
        try:
            user = await user_manager.oauth_callback(
                oauth_client.name,
                token["access_token"],
                account_id,
                account_email,
                token.get("expires_at"),
                token.get("refresh_token"),
                request,
                associate_by_email=associate_by_email,
                is_verified_by_default=is_verified_by_default,
            )
        except UserAlreadyExists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ErrorCode.OAUTH_USER_ALREADY_EXISTS,
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ErrorCode.LOGIN_BAD_CREDENTIALS,
            )

        # Login user
        response = await backend.login(strategy, user)
        await user_manager.on_after_login(user, request, response)

        # Prepare redirect response
        if tenant_id is None:
            # Use URL utility to add parameters
            redirect_url = add_url_params(next_url, {"new_team": "true"})
            redirect_response = RedirectResponse(redirect_url, status_code=302)
        else:
            # No parameters to add
            redirect_response = RedirectResponse(next_url, status_code=302)

        # Copy headers from auth response to redirect response, with special handling for Set-Cookie
        for header_name, header_value in response.headers.items():
            # FastAPI can have multiple Set-Cookie headers as a list
            if header_name.lower() == "set-cookie" and isinstance(header_value, list):
                for cookie_value in header_value:
                    redirect_response.headers.append(header_name, cookie_value)
            else:
                redirect_response.headers[header_name] = header_value

        if hasattr(response, "body"):
            redirect_response.body = response.body
        if hasattr(response, "status_code"):
            redirect_response.status_code = response.status_code
        if hasattr(response, "media_type"):
            redirect_response.media_type = response.media_type

        return redirect_response

    return router


async def api_key_dep(
    request: Request, async_db_session: AsyncSession = Depends(get_async_session)
) -> User | None:
    if AUTH_TYPE == AuthType.DISABLED:
        return None

    user: User | None = None

    hashed_api_key = get_hashed_api_key_from_request(request)
    if not hashed_api_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    if hashed_api_key:
        user = await fetch_user_for_api_key(hashed_api_key, async_db_session)

    if user is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return user
