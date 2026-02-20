"""Integration tests for seat limit enforcement on user creation paths.

Verifies that when a license with a seat limit is active, new user
creation (registration, invite, reactivation) is blocked with HTTP 402.
"""

from datetime import datetime
from datetime import timedelta

import redis
import requests

from ee.onyx.server.license.models import LicenseMetadata
from ee.onyx.server.license.models import LicenseSource
from ee.onyx.server.license.models import PlanType
from onyx.configs.app_configs import REDIS_DB_NUMBER
from onyx.configs.app_configs import REDIS_HOST
from onyx.configs.app_configs import REDIS_PORT
from onyx.server.settings.models import ApplicationStatus
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.managers.user import UserManager

# TenantRedis prefixes every key with "{tenant_id}:".
# Single-tenant deployments use "public" as the tenant id.
_LICENSE_REDIS_KEY = "public:license:metadata"


def _seed_license(r: redis.Redis, seats: int) -> None:
    """Write a LicenseMetadata entry into Redis with the given seat cap."""
    now = datetime.utcnow()
    metadata = LicenseMetadata(
        tenant_id="public",
        organization_name="Test Org",
        seats=seats,
        used_seats=0,  # check_seat_availability recalculates from DB
        plan_type=PlanType.ANNUAL,
        issued_at=now,
        expires_at=now + timedelta(days=365),
        status=ApplicationStatus.ACTIVE,
        source=LicenseSource.MANUAL_UPLOAD,
    )
    r.set(_LICENSE_REDIS_KEY, metadata.model_dump_json(), ex=300)


def _clear_license(r: redis.Redis) -> None:
    r.delete(_LICENSE_REDIS_KEY)


def _redis() -> redis.Redis:
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_NUMBER)


# ------------------------------------------------------------------
# Registration
# ------------------------------------------------------------------


def test_registration_blocked_when_seats_full(reset: None) -> None:  # noqa: ARG001
    """POST /auth/register returns 402 when the seat limit is reached."""
    r = _redis()

    # First user is admin — occupies 1 seat
    UserManager.create(name="admin_user")

    # License allows exactly 1 seat → already full
    _seed_license(r, seats=1)

    try:
        response = requests.post(
            url=f"{API_SERVER_URL}/auth/register",
            json={
                "email": "blocked@example.com",
                "username": "blocked@example.com",
                "password": "TestPassword123!",
            },
            headers=GENERAL_HEADERS,
        )
        assert response.status_code == 402
    finally:
        _clear_license(r)


# ------------------------------------------------------------------
# Invitation
# ------------------------------------------------------------------


def test_invite_blocked_when_seats_full(reset: None) -> None:  # noqa: ARG001
    """PUT /manage/admin/users returns 402 when the seat limit is reached."""
    r = _redis()

    admin_user = UserManager.create(name="admin_user")

    _seed_license(r, seats=1)

    try:
        response = requests.put(
            url=f"{API_SERVER_URL}/manage/admin/users",
            json={"emails": ["newuser@example.com"]},
            headers=admin_user.headers,
        )
        assert response.status_code == 402
    finally:
        _clear_license(r)


# ------------------------------------------------------------------
# Reactivation
# ------------------------------------------------------------------


def test_reactivation_blocked_when_seats_full(reset: None) -> None:  # noqa: ARG001
    """PATCH /manage/admin/activate-user returns 402 when seats are full."""
    r = _redis()

    admin_user = UserManager.create(name="admin_user")
    basic_user = UserManager.create(name="basic_user")

    # Deactivate the basic user (frees a seat in the DB count)
    UserManager.set_status(
        basic_user, target_status=False, user_performing_action=admin_user
    )

    # Set license to 1 seat — only admin counts now
    _seed_license(r, seats=1)

    try:
        response = requests.patch(
            url=f"{API_SERVER_URL}/manage/admin/activate-user",
            json={"user_email": basic_user.email},
            headers=admin_user.headers,
        )
        assert response.status_code == 402
    finally:
        _clear_license(r)


# ------------------------------------------------------------------
# No license → no enforcement
# ------------------------------------------------------------------


def test_registration_allowed_without_license(reset: None) -> None:  # noqa: ARG001
    """Without a license in Redis, registration is unrestricted."""
    r = _redis()

    # Make sure there is no cached license
    _clear_license(r)

    UserManager.create(name="admin_user")

    # Second user should register without issue
    second_user = UserManager.create(name="second_user")
    assert second_user is not None
