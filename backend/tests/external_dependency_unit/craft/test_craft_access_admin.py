"""Tests for the admin per-user Craft access toggle. Route functions are
invoked directly with constructed ``User`` rows and the test ``db_session``
(no ``TestClient``)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.feature_flags.interface import NoOpFeatureFlagProvider
from onyx.server.features.build import utils as build_utils
from onyx.server.features.build.api import require_onyx_craft_enabled
from onyx.server.features.build.utils import is_craft_enabled_for_user
from onyx.server.manage.models import UserCraftAccessUpdateRequest
from onyx.server.manage.users import set_user_craft_access
from tests.external_dependency_unit.craft.db_helpers import make_user


def _enable_craft_deployment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the deployment-level gate on via the ENABLE_CRAFT env path."""
    monkeypatch.setattr(build_utils, "ENABLE_CRAFT", True)
    monkeypatch.setattr(
        build_utils,
        "get_default_feature_flag_provider",
        lambda: NoOpFeatureFlagProvider(),
    )


def test_admin_toggle_disables_and_reenables_craft(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_craft_deployment(monkeypatch)
    admin = make_user(db_session, role=UserRole.ADMIN, email_prefix="craft_admin")
    target = make_user(db_session, role=UserRole.BASIC, email_prefix="craft_target")

    assert target.craft_enabled is True
    assert is_craft_enabled_for_user(target) is True

    set_user_craft_access(
        craft_access_update_request=UserCraftAccessUpdateRequest(
            user_email=target.email, craft_enabled=False
        ),
        current_user=admin,
        db_session=db_session,
    )
    db_session.refresh(target)
    assert target.craft_enabled is False
    assert is_craft_enabled_for_user(target) is False
    # The /build router dependency now rejects the user.
    with pytest.raises(OnyxError) as exc_info:
        require_onyx_craft_enabled(user=target)
    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    assert exc_info.value.status_code == 403
    # The admin's own access is unaffected.
    assert is_craft_enabled_for_user(admin) is True

    set_user_craft_access(
        craft_access_update_request=UserCraftAccessUpdateRequest(
            user_email=target.email, craft_enabled=True
        ),
        current_user=admin,
        db_session=db_session,
    )
    db_session.refresh(target)
    assert target.craft_enabled is True
    assert is_craft_enabled_for_user(target) is True
    assert require_onyx_craft_enabled(user=target) is target


def test_unknown_user_raises_not_found(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    admin = make_user(db_session, role=UserRole.ADMIN, email_prefix="craft_admin")

    with pytest.raises(OnyxError) as exc_info:
        set_user_craft_access(
            craft_access_update_request=UserCraftAccessUpdateRequest(
                user_email="craft_missing_user@example.com", craft_enabled=False
            ),
            current_user=admin,
            db_session=db_session,
        )
    assert exc_info.value.error_code == OnyxErrorCode.NOT_FOUND
