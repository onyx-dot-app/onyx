"""Integration tests for Slack user deactivation and reactivation via admin endpoints.

Verifies that:
- Slack users can be deactivated by admins
- Deactivated Slack users can be reactivated by admins
- Reactivation is blocked when the seat limit is reached
"""

from datetime import datetime
from datetime import timedelta

import redis
import requests

from ee.onyx.server.license.models import LicenseMetadata
from ee.onyx.server.license.models import LicenseSource
from ee.onyx.server.license.models import PlanType
from onyx.auth.schemas import UserRole
from onyx.configs.app_configs import REDIS_DB_NUMBER
from onyx.configs.app_configs import REDIS_HOST
from onyx.configs.app_configs import REDIS_PORT
from onyx.server.settings.models import ApplicationStatus
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser

_LICENSE_REDIS_KEY = "public:license:metadata"


def _seed_license(r: redis.Redis, seats: int) -> None:
    now = datetime.utcnow()
    metadata = LicenseMetadata(
        tenant_id="public",
        organization_name="Test Org",
        seats=seats,
        used_seats=0,
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


def _get_user_is_active(email: str, admin_user: DATestUser) -> bool:
    """Look up a user's is_active flag via the admin users list endpoint."""
    result = UserManager.get_user_page(
        user_performing_action=admin_user,
        search_query=email,
    )
    matching = [u for u in result.items if u.email == email]
    assert len(matching) == 1, f"Expected exactly 1 user with email {email}"
    return matching[0].is_active


def test_slack_user_deactivate_and_reactivate(reset: None) -> None:  # noqa: ARG001
    """Admin can deactivate and then reactivate a Slack user."""
    admin_user = UserManager.create(name="admin_user")

    slack_user = UserManager.create(name="slack_test_user")
    slack_user = UserManager.set_role(
        user_to_set=slack_user,
        target_role=UserRole.SLACK_USER,
        user_performing_action=admin_user,
        explicit_override=True,
    )

    # Deactivate the Slack user
    UserManager.set_status(
        slack_user, target_status=False, user_performing_action=admin_user
    )
    assert _get_user_is_active(slack_user.email, admin_user) is False

    # Reactivate the Slack user
    UserManager.set_status(
        slack_user, target_status=True, user_performing_action=admin_user
    )
    assert _get_user_is_active(slack_user.email, admin_user) is True


def test_slack_user_reactivation_blocked_by_seat_limit(
    reset: None,  # noqa: ARG001
) -> None:
    """Reactivating a deactivated Slack user returns 402 when seats are full."""
    r = _redis()

    admin_user = UserManager.create(name="admin_user")

    slack_user = UserManager.create(name="slack_test_user")
    slack_user = UserManager.set_role(
        user_to_set=slack_user,
        target_role=UserRole.SLACK_USER,
        user_performing_action=admin_user,
        explicit_override=True,
    )

    UserManager.set_status(
        slack_user, target_status=False, user_performing_action=admin_user
    )

    # License allows 1 seat — only admin counts
    _seed_license(r, seats=1)

    try:
        response = requests.patch(
            url=f"{API_SERVER_URL}/manage/admin/activate-user",
            json={"user_email": slack_user.email},
            headers=admin_user.headers,
        )
        assert response.status_code == 402
    finally:
        _clear_license(r)
