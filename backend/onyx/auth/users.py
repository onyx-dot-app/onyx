import json
import secrets
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from datetime import timezone
from typing import cast
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

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
from sqlalchemy.ext.asyncio import AsyncSession

from onyx.auth.api_key import get_hashed_api_key_from_request
from onyx.auth.email_utils import send_forgot_password_email
from onyx.auth.email_utils import send_user_verification_email
from onyx.auth.invited_users import get_invited_users
from onyx.auth.schemas import AuthBackend
from onyx.auth.schemas import UserCreate
from onyx.auth.schemas import UserRole
from onyx.auth.schemas import UserUpdateWithRole
from onyx.configs.app_configs import AUTH_BACKEND
from onyx.configs.app_configs import AUTH_COOKIE_EXPIRE_TIME_SECONDS
from onyx.configs.app_configs import AUTH_TYPE
from onyx.configs.app_configs import DISABLE_AUTH
from onyx.configs.app_configs import EMAIL_CONFIGURED
from onyx.configs.app_configs import REDIS_AUTH_KEY_PREFIX
from onyx.configs.app_configs import REQUIRE_EMAIL_VERIFICATION
from onyx.configs.app_configs import SESSION_EXPIRE_TIME_SECONDS
from onyx.configs.app_configs import TRACK_EXTERNAL_IDP_EXPIRY
from onyx.configs.app_configs import USER_AUTH_SECRET
from onyx.configs.app_configs import VALID_EMAIL_DOMAINS
from onyx.configs.app_configs import WEB_DOMAIN
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
from onyx.db.engine import get_async_session
from onyx.db.engine import get_async_session_with_tenant
from onyx.db.engine import get_current_tenant_id
from onyx.db.engine import get_session_with_tenant
from onyx.db.models import AccessToken
from onyx.db.models import OAuthAccount
from onyx.db.models import User
from onyx.db.users import get_user_by_email
from onyx.redis.redis_pool import get_async_redis_connection
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger
from onyx.utils.telemetry import create_milestone_and_report
from onyx.utils.telemetry import optional_telemetry
from onyx.utils.telemetry import RecordType
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop
from onyx.utils.variable_functionality import fetch_versioned_implementation
from shared_configs.configs import async_return_default_schema
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


class BasicAuthenticationError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def is_user_admin(user: User | None) -> bool:
    if AUTH_TYPE == AuthType.DISABLED:
        return True
    if user and user.role == UserRole.ADMIN:
        return True
    return False


def verify_auth_setting() -> None:
    if AUTH_TYPE not in [AuthType.DISABLED, AuthType.BASIC, AuthType.GOOGLE_OAUTH]:
        raise ValueError(
            "User must choose a valid user authentication method: "
            "disabled, basic, or google_oauth"
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


def verify_email_in_whitelist(email: str, tenant_id: str | None = None) -> None:
    with get_session_with_tenant(tenant_id) as db_session:
        if not get_user_by_email(email, db_session):
            verify_email_is_invited(email)


def verify_email_domain(email: str) -> None:
    if VALID_EMAIL_DOMAINS:
        if email.count("@") != 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is not valid",
            )
        domain = email.split("@")[-1]
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
        async with get_async_session_with_tenant(tenant_id) as db_session:
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

        async with get_async_session_with_tenant(tenant_id) as db_session:
            token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
            verify_email_is_invited(user_create.email)
            verify_email_domain(user_create.email)
            if MULTI_TENANT:
                tenant_user_db = SQLAlchemyUserAdminDB[User, uuid.UUID](
                    db_session, User, OAuthAccount
                )
                self.user_db = tenant_user_db
                self.database = tenant_user_db

            if hasattr(user_create, "role"):
                user_count = await get_user_count()
                if (
                    user_count == 0
                    or user_create.email in get_default_admin_user_emails()
                ):
                    user_create.role = UserRole.ADMIN
                else:
                    user_create.role = UserRole.BASIC
            try:
                user = await super().create(user_create, safe=safe, request=request)  # type: ignore
            except exceptions.UserAlreadyExists:
                user = await self.get_by_email(user_create.email)
                # Handle case where user has used product outside of web and is now creating an account through web
                if not user.role.is_web_login() and user_create.role.is_web_login():
                    user_update = UserUpdateWithRole(
                        password=user_create.password,
                        is_verified=user_create.is_verified,
                        role=user_create.role,
                    )
                    user = await self.update(user_update, user)
                else:
                    raise exceptions.UserAlreadyExists()

            finally:
                CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        return user

    async def validate_password(self, password: str, _: schemas.UC | models.UP) -> None:
        # Validate password according to basic security guidelines
        if len(password) < 12:
            raise exceptions.InvalidPasswordException(
                reason="Password must be at least 12 characters long."
            )
        if len(password) > 64:
            raise exceptions.InvalidPasswordException(
                reason="Password must not exceed 64 characters."
            )
        if not any(char.isupper() for char in password):
            raise exceptions.InvalidPasswordException(
                reason="Password must contain at least one uppercase letter."
            )
        if not any(char.islower() for char in password):
            raise exceptions.InvalidPasswordException(
                reason="Password must contain at least one lowercase letter."
            )
        if not any(char.isdigit() for char in password):
            raise exceptions.InvalidPasswordException(
                reason="Password must contain at least one number."
            )
        if not any(char in PASSWORD_SPECIAL_CHARS for char in password):
            raise exceptions.InvalidPasswordException(
                reason="Password must contain at least one special character from the following set: "
                f"{PASSWORD_SPECIAL_CHARS}."
            )

        return

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
        async with get_async_session_with_tenant(tenant_id) as db_session:
            token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

            verify_email_in_whitelist(account_email, tenant_id)
            verify_email_domain(account_email)

            if MULTI_TENANT:
                tenant_user_db = SQLAlchemyUserAdminDB[User, uuid.UUID](
                    db_session, User, OAuthAccount
                )
                self.user_db = tenant_user_db
                self.database = tenant_user_db

            oauth_account_dict = {
                "oauth_name": oauth_name,
                "access_token": access_token,
                "account_id": account_id,
                "account_email": account_email,
                "expires_at": expires_at,
                "refresh_token": refresh_token,
            }

            user: User

            try:
                # Attempt to get user by OAuth account
                user = await self.get_by_oauth_account(oauth_name, account_id)

            except exceptions.UserNotExists:
                try:
                    # Attempt to get user by email
                    user = await self.get_by_email(account_email)
                    if not associate_by_email:
                        raise exceptions.UserAlreadyExists()

                    user = await self.user_db.add_oauth_account(
                        user, oauth_account_dict
                    )

                    # If user not found by OAuth account or email, create a new user
                except exceptions.UserNotExists:
                    password = self.password_helper.generate()
                    user_dict = {
                        "email": account_email,
                        "hashed_password": self.password_helper.hash(password),
                        "is_verified": is_verified_by_default,
                    }

                    user = await self.user_db.create(user_dict)

                    # Explicitly set the Postgres schema for this session to ensure
                    # OAuth account creation happens in the correct tenant schema

                    # Add OAuth account
                    await self.user_db.add_oauth_account(user, oauth_account_dict)
                    await self.on_after_register(user, request)

            else:
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
                await self.user_db.update(
                    user,
                    {
                        "is_verified": is_verified_by_default,
                        "role": UserRole.BASIC,
                    },
                )
                user.is_verified = is_verified_by_default

            # this is needed if an organization goes from `TRACK_EXTERNAL_IDP_EXPIRY=true` to `false`
            # otherwise, the oidc expiry will always be old, and the user will never be able to login
            if (
                user.oidc_expiry is not None  # type: ignore
                and not TRACK_EXTERNAL_IDP_EXPIRY
            ):
                await self.user_db.update(user, {"oidc_expiry": None})
                user.oidc_expiry = None  # type: ignore

            if token:
                CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

            return user

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

            with get_session_with_tenant(tenant_id=tenant_id) as db_session:
                if user_count == 1:
                    create_milestone_and_report(
                        user=user,
                        distinct_id=user.email,
                        event_type=MilestoneRecordType.USER_SIGNED_UP,
                        properties=None,
                        db_session=db_session,
                    )
                else:
                    create_milestone_and_report(
                        user=user,
                        distinct_id=user.email,
                        event_type=MilestoneRecordType.MULTIPLE_USERS,
                        properties=None,
                        db_session=db_session,
                    )
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

        logger.notice(f"User {user.id} has registered.")
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

        send_forgot_password_email(user.email, token, tenant_id=tenant_id)

    async def on_after_request_verify(
        self, user: User, token: str, request: Optional[Request] = None
    ) -> None:
        verify_email_domain(user.email)

        logger.notice(
            f"Verification requested for user {user.id}. Verification token: {token}"
        )

        send_user_verification_email(user.email, token)

    async def authenticate(
        self, credentials: OAuth2PasswordRequestForm
    ) -> Optional[User]:
        email = credentials.username

        # Get tenant_id from mapping table
        tenant_id = await fetch_ee_implementation_or_noop(
            "onyx.server.tenants.provisioning",
            "get_or_provision_tenant",
            async_return_default_schema,
        )(
            email=email,
        )
        if not tenant_id:
            # User not found in mapping
            self.password_helper.hash(credentials.password)
            return None

        # Create a tenant-specific session
        async with get_async_session_with_tenant(tenant_id) as tenant_session:
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


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
) -> AsyncGenerator[UserManager, None]:
    yield UserManager(user_db)


cookie_transport = CookieTransport(
    cookie_max_age=SESSION_EXPIRE_TIME_SECONDS,
    cookie_secure=WEB_DOMAIN.startswith("https"),
    cookie_name=FASTAPI_USERS_AUTH_COOKIE_NAME,
)


def get_redis_strategy() -> RedisStrategy:
    return TenantAwareRedisStrategy()


def get_database_strategy(
    access_token_db: AccessTokenDatabase[AccessToken] = Depends(get_access_token_db),
) -> DatabaseStrategy:
    return DatabaseStrategy(
        access_token_db, lifetime_seconds=SESSION_EXPIRE_TIME_SECONDS
    )


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


fastapi_users = FastAPIUserWithLogoutRouter[User, uuid.UUID](
    get_user_manager, [auth_backend]
)


# NOTE: verified=REQUIRE_EMAIL_VERIFICATION is not used here since we
# take care of that in `double_check_user` ourself. This is needed, since
# we want the /me endpoint to still return a user even if they are not
# yet verified, so that the frontend knows they exist
optional_fastapi_current_user = fastapi_users.current_user(active=True, optional=True)


async def optional_user_(
    request: Request,
    user: User | None,
    async_db_session: AsyncSession,
) -> User | None:
    """NOTE: `request` and `db_session` are not used here, but are included
    for the EE version of this function."""
    return user


async def optional_user(
    request: Request,
    async_db_session: AsyncSession = Depends(get_async_session),
    user: User | None = Depends(optional_fastapi_current_user),
) -> User | None:
    versioned_fetch_user = fetch_versioned_implementation(
        "onyx.auth.users", "optional_user_"
    )
    user = await versioned_fetch_user(request, user, async_db_session)

    # check if an API key is present
    if user is None:
        hashed_api_key = get_hashed_api_key_from_request(request)
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


async def current_chat_accesssible_user(
    user: User | None = Depends(optional_user),
    tenant_id: str | None = Depends(get_current_tenant_id),
) -> User | None:
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
        authorization_url = await oauth_client.get_authorization_url(
            authorize_redirect_url,
            state,
            scopes,
        )

        return OAuth2AuthorizeResponse(authorization_url=authorization_url)

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
        redirect_response = RedirectResponse(next_url, status_code=302)

        # Copy headers and other attributes from 'response' to 'redirect_response'
        for header_name, header_value in response.headers.items():
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
