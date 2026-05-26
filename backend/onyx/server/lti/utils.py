"""Utilities for LTI 1.3 launches and Canvas course → Onyx tutor binding.

Tutors are bound to courses entirely *inside Onyx*. We never ask the admin
to type a course ID — the binding label name is the LTI `context.id` from
the live launch, captured by the editor via the `lti_context_id` URL param
that the launch handler threads through. `find_tutor_personas_for_course`
is the runtime side of that contract.
"""

import contextlib
import json
import secrets
import string
import time
from uuid import UUID

import httpx
import jwt as pyjwt
from fastapi_users import exceptions
from jwt import PyJWKSet
from jwt.exceptions import InvalidTokenError
from redis import asyncio as aioredis
from sqlalchemy import select

from onyx.auth.schemas import UserCreate
from onyx.auth.schemas import UserRole
from onyx.auth.users import get_user_db
from onyx.auth.users import get_user_manager
from onyx.configs.constants import DocumentSource
from onyx.configs.lti_configs import LTI_CLIENT_ID
from onyx.configs.lti_configs import LTI_ISSUER
from onyx.configs.lti_configs import LTI_JWKS_URL
from onyx.configs.lti_configs import LTI_NONCE_TTL_SECONDS
from onyx.db.auth import get_user_count
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.enums import HierarchyNodeType
from onyx.db.lti import build_lti_course_project_description
from onyx.db.models import HierarchyNode
from onyx.db.models import Persona
from onyx.db.models import PersonaLabel
from onyx.db.models import User
from onyx.db.models import UserProject
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.lti.constants import VIRTUAL_TUTOR_LABEL
from onyx.utils.logger import setup_logger


logger = setup_logger()

# LTI 1.3 role URIs
_LTI_ADMIN_ROLES = {
    "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Administrator",
    "http://purl.imsglobal.org/vocab/lis/v2/membership#Administrator",
    "http://purl.imsglobal.org/vocab/lis/v2/system/person#Administrator",
}
_LTI_INSTRUCTOR_ROLES = {
    "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor",
    "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Instructor",
    "http://purl.imsglobal.org/vocab/lis/v2/membership#ContentDeveloper",
}

# Redis key prefix for LTI OIDC state
_LTI_STATE_PREFIX = "lti_state:"

# In-memory JWKS cache
_jwks_cache: dict[str, dict] = {}
_jwks_cache_time: float = 0.0
_JWKS_CACHE_TTL = 3600  # 1 hour


async def store_lti_state(
    redis: aioredis.Redis,
    state: str,
    nonce: str,
) -> None:
    """Store OIDC state+nonce in Redis with a short TTL."""
    key = f"{_LTI_STATE_PREFIX}{state}"
    data = json.dumps({"nonce": nonce, "created": int(time.time())})
    await redis.set(key, data, ex=LTI_NONCE_TTL_SECONDS)


async def validate_and_consume_state(
    redis: aioredis.Redis,
    state: str,
) -> str:
    """Retrieve and atomically delete the state from Redis. Returns the nonce."""
    key = f"{_LTI_STATE_PREFIX}{state}"
    raw = await redis.getdel(key)
    if raw is None:
        raise OnyxError(
            OnyxErrorCode.UNAUTHENTICATED,
            "LTI state expired or not found (possible replay)",
        )
    data = json.loads(raw)
    return str(data["nonce"])


async def _fetch_jwks() -> dict:
    """Fetch and cache the platform's JWKS."""
    global _jwks_cache, _jwks_cache_time

    if _jwks_cache and (time.time() - _jwks_cache_time) < _JWKS_CACHE_TTL:
        return _jwks_cache

    if not LTI_JWKS_URL:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "LTI_JWKS_URL is not configured")

    async with httpx.AsyncClient() as client:
        resp = await client.get(LTI_JWKS_URL)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        _jwks_cache_time = time.time()
        return _jwks_cache


def _extract_email_from_claims(claims: dict) -> str:
    """Extract email from LTI JWT claims.

    Canvas may place the email in several locations depending on
    configuration and privacy settings.
    """
    logger.debug("LTI JWT claims: %s", list(claims.keys()))

    # Standard OIDC email claim
    email = claims.get("email")
    if email:
        return str(email).strip().lower()

    # Canvas sometimes nests email in the LTI 1.3 custom claims
    custom = claims.get("https://purl.imsglobal.org/spec/lti/claim/custom", {})
    email = custom.get("email") or custom.get("user_email")
    if email:
        return str(email).strip().lower()

    # Canvas extension: lis (Learning Information Services) person contact
    lis = claims.get("https://purl.imsglobal.org/spec/lti/claim/lis", {})
    email = lis.get("person_contact_email_primary")
    if email:
        return str(email).strip().lower()

    # Canvas-specific extension claims
    for key in [
        "https://purl.imsglobal.org/spec/lti/claim/ext",
        "https://www.instructure.com/claims",
    ]:
        ext = claims.get(key, {})
        if isinstance(ext, dict):
            email = ext.get("email") or ext.get("user_email")
            if email:
                return str(email).strip().lower()

    # Last resort: construct from sub + platform domain if name is available
    # Log all claims to help debug
    logger.error(
        "LTI JWT missing email. Available claims: %s",
        {k: v for k, v in claims.items() if not k.startswith("https://")},
    )
    logger.error(
        "LTI JWT LTI-namespaced claims: %s",
        {k: v for k, v in claims.items() if k.startswith("https://")},
    )

    raise OnyxError(
        OnyxErrorCode.INVALID_INPUT,
        "LTI launch JWT does not contain an email claim. "
        "Ensure Canvas is configured to share email addresses "
        "(Privacy setting should be 'Public' or 'Email Only' on the Developer Key).",
    )


def _map_lti_roles_to_onyx_role(lti_roles: list[str]) -> UserRole:
    """Map LTI role URIs to an Onyx UserRole.

    LTI Administrators → ADMIN (full platform access).
    LTI Instructors/ContentDevelopers → CURATOR (can create/edit their own
    tutors and manage document sets within their user groups, but cannot
    modify platform-wide settings or other professors' resources).
    Everyone else → BASIC (student-level access).
    """
    role_set = set(lti_roles)
    if role_set & _LTI_ADMIN_ROLES:
        return UserRole.ADMIN
    if role_set & _LTI_INSTRUCTOR_ROLES:
        return UserRole.CURATOR
    return UserRole.BASIC


async def validate_lti_jwt(id_token: str, expected_nonce: str) -> dict:
    """Validate an LTI 1.3 id_token JWT and return its claims.

    Checks:
    - Signature against the platform JWKS
    - Issuer matches LTI_ISSUER
    - Audience contains LTI_CLIENT_ID
    - Nonce matches expected value
    - Token is not expired
    """
    jwks_data = await _fetch_jwks()

    try:
        jwk_set = PyJWKSet.from_dict(jwks_data)
    except Exception as e:
        raise OnyxError(OnyxErrorCode.INVALID_TOKEN, f"Invalid JWKS data: {e}")

    try:
        # Get the unverified header to find the key id
        unverified_header = pyjwt.get_unverified_header(id_token)
    except InvalidTokenError as e:
        raise OnyxError(OnyxErrorCode.INVALID_TOKEN, f"Invalid LTI JWT header: {e}")

    kid = unverified_header.get("kid")
    signing_key = None
    for jwk in jwk_set.keys:
        if jwk.key_id == kid:
            signing_key = jwk.key
            break

    if signing_key is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_TOKEN,
            "No matching key found in platform JWKS for JWT kid",
        )

    try:
        claims: dict = pyjwt.decode(
            id_token,
            signing_key,
            algorithms=["RS256"],
            audience=LTI_CLIENT_ID,
            issuer=LTI_ISSUER,
        )
    except InvalidTokenError as e:
        raise OnyxError(OnyxErrorCode.INVALID_TOKEN, f"LTI JWT validation failed: {e}")

    # Verify nonce
    token_nonce = claims.get("nonce")
    if token_nonce != expected_nonce:
        raise OnyxError(
            OnyxErrorCode.UNAUTHENTICATED,
            "LTI JWT nonce mismatch",
        )

    return claims


async def upsert_lti_user(email: str, lti_roles: list[str]) -> User:
    """Create or retrieve a user from an LTI launch, following the SAML pattern."""
    get_user_db_context = contextlib.asynccontextmanager(get_user_db)
    get_user_manager_context = contextlib.asynccontextmanager(get_user_manager)

    async with get_async_session_context_manager() as session:
        async with get_user_db_context(session) as user_db:
            async with get_user_manager_context(user_db) as um:
                try:
                    user = await um.get_by_email(email)
                    if not user.role.is_web_login():
                        raise exceptions.UserNotExists()
                    return user
                except exceptions.UserNotExists:
                    logger.info("Creating user from LTI launch: %s", email)

                user_count = await get_user_count()
                role = (
                    UserRole.ADMIN
                    if user_count == 0
                    else _map_lti_roles_to_onyx_role(lti_roles)
                )

                # Generate a secure random password (LTI users authenticate
                # via their LMS, so this is never used directly)
                secure_random_password = "".join(
                    [
                        secrets.choice(string.ascii_uppercase),
                        secrets.choice(string.ascii_lowercase),
                        secrets.choice(string.digits),
                        secrets.choice("!@#$%^&*()-_=+[]{}|;:,.<>?"),
                        "".join(
                            secrets.choice(
                                string.ascii_letters
                                + string.digits
                                + "!@#$%^&*()-_=+[]{}|;:,.<>?"
                            )
                            for _ in range(12)
                        ),
                    ]
                )

                user = await um.create(
                    UserCreate(
                        email=email,
                        password=secure_random_password,
                        role=role,
                        is_verified=True,
                    )
                )
                return user


def extract_lti_context(claims: dict) -> dict[str, str | None]:
    """Extract Canvas course context from LTI JWT claims.

    Returns a dict with keys: course_id, course_label, course_title.
    All values may be None if the context claim is missing.
    """
    context = claims.get("https://purl.imsglobal.org/spec/lti/claim/context", {})
    return {
        "course_id": context.get("id"),
        "course_label": context.get("label"),
        "course_title": context.get("title"),
    }


async def get_or_create_lti_course_project(
    user_id: UUID,
    course_id: str,
    course_label: str | None,
    course_title: str | None,
) -> int:
    """Find or create a UserProject for a Canvas course.

    The project name is prefixed with "[Canvas]" so it's identifiable.
    We match on the description field which stores the stable Canvas
    course ID, since course names can change.

    Returns the project ID.
    """
    # Use the Canvas course ID as a stable identifier in the description
    stable_description = build_lti_course_project_description(course_id)
    display_name = course_title or course_label or f"Course {course_id}"
    project_name = f"[Canvas] {display_name}"

    async with get_async_session_context_manager() as session:
        # Look for an existing project with this stable description for this user
        result = await session.execute(
            select(UserProject).where(
                UserProject.user_id == user_id,
                UserProject.description == stable_description,
            )
        )
        existing = result.scalars().first()
        if existing:
            # Update the name in case the course was renamed
            if existing.name != project_name:
                existing.name = project_name
                await session.commit()
            return existing.id

        # Create a new project for this course
        project = UserProject(
            user_id=user_id,
            name=project_name,
            description=stable_description,
            instructions="",
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
        logger.info(
            "Created LTI course project: id=%d, name=%s, course_id=%s",
            project.id,
            project_name,
            course_id,
        )
        return project.id


async def find_canvas_course_node_id(course_title: str) -> int | None:
    """Resolve the indexed Canvas course HierarchyNode that matches an LTI launch.

    The Canvas connector indexes each course as a top-level COURSE
    `HierarchyNode` whose `display_name` is the course name. The LTI 1.3
    launch sends the same name as `context.title`, so we match by display
    name to scope the tutor editor to the Canvas course the launch came
    from. Returns None if there is no unique match (zero or multiple
    candidates) — callers fall back to showing the whole hierarchy.
    """
    title = course_title.strip()
    if not title:
        return None

    async with get_async_session_context_manager() as session:
        result = await session.execute(
            select(HierarchyNode.id)
            .where(
                HierarchyNode.source == DocumentSource.CANVAS,
                HierarchyNode.node_type == HierarchyNodeType.COURSE,
                HierarchyNode.display_name == title,
            )
            .limit(2)
        )
        ids = [row[0] for row in result.all()]
        if len(ids) == 1:
            return ids[0]
        if len(ids) > 1:
            logger.info(
                "LTI Canvas course node lookup matched %d nodes for title %r; "
                "skipping scoped filter",
                len(ids),
                title,
            )
        return None


async def find_tutor_personas_for_course(lti_context_id: str) -> list[int]:
    """Find every Virtual Tutor persona bound to an LTI course context.

    A persona qualifies when it carries both:
    1. The "Virtual Tutor" label
    2. A label whose name equals the LTI `context.id` for the course

    Returns persona IDs ordered by display_priority (nulls last) then id.
    May be empty if no tutors are bound to this course.
    """
    async with get_async_session_context_manager() as session:
        result = await session.execute(
            select(Persona.id)
            .where(
                Persona.deleted.is_(False),
                Persona.labels.any(PersonaLabel.name == VIRTUAL_TUTOR_LABEL),
                Persona.labels.any(PersonaLabel.name == lti_context_id),
            )
            .order_by(
                Persona.display_priority.asc().nullslast(),
                Persona.id.asc(),
            )
        )
        persona_ids = [row[0] for row in result.all()]

        if persona_ids:
            logger.info(
                "Found %d tutor persona(s) for LTI context %s: %s",
                len(persona_ids),
                lti_context_id,
                persona_ids,
            )

        return persona_ids
