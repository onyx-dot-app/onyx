"""End-to-end tests for `get_external_app_credentials` against a real
Postgres. Setup writes flush but never commit; `rollback_session`
discards them at teardown so each test sees a clean catalog."""

import uuid
from collections.abc import Generator
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType
from onyx.db.external_app import create_external_app
from onyx.db.external_app import get_external_app_credentials
from onyx.db.external_app import upsert_external_app_user_credential
from onyx.db.models import ExternalApp
from tests.external_dependency_unit.conftest import create_test_user

_DEFAULT_AUTH_TEMPLATE: dict[str, Any] = {
    "client_id": "{client_id}",
    "client_secret": "{client_secret}",
    "access_token": "Bearer {access_token}",
    "refresh_token": "{refresh_token}",
}
_DEFAULT_ORG_CREDS: dict[str, Any] = {
    "client_id": "ORG_CLIENT_ID",
    "client_secret": "ORG_CLIENT_SECRET",
}
_DEFAULT_USER_CREDS: dict[str, Any] = {
    "access_token": "USER_ACCESS_TOKEN",
    "refresh_token": "USER_REFRESH_TOKEN",
}
_DEFAULT_UPSTREAM_URL_PATTERNS = [r"https://api\.example\.com/.*"]
_DEFAULT_MATCHING_URL = "https://api.example.com/users/me"


@pytest.fixture
def rollback_session(db_session: Session) -> Generator[Session, None, None]:
    try:
        yield db_session
    finally:
        db_session.rollback()


def _create_app(
    db_session: Session,
    name: str = "Test App",
    upstream_url_patterns: list[str] | None = None,
    auth_template: dict[str, Any] | None = None,
    organization_credentials: dict[str, Any] | None = None,
    enabled: bool = True,
    app_type: ExternalAppType = ExternalAppType.CUSTOM,
) -> ExternalApp:
    return create_external_app(
        db_session,
        slug=f"test-{uuid.uuid4().hex[:12]}",
        name=name,
        description="test",
        bundle_file_id="",
        bundle_sha256="",
        app_type=app_type,
        upstream_url_patterns=(
            upstream_url_patterns
            if upstream_url_patterns is not None
            else list(_DEFAULT_UPSTREAM_URL_PATTERNS)
        ),
        auth_template=(
            auth_template if auth_template is not None else dict(_DEFAULT_AUTH_TEMPLATE)
        ),
        organization_credentials=(
            organization_credentials
            if organization_credentials is not None
            else dict(_DEFAULT_ORG_CREDS)
        ),
        enabled=enabled,
    )


def _store_user_creds(
    db_session: Session,
    app_id: int,
    user_id: UUID,
    creds: dict[str, Any],
) -> None:
    upsert_external_app_user_credential(
        db_session,
        external_app_id=app_id,
        user_id=user_id,
        user_credentials=creds,
    )


# ── Happy paths ───────────────────────────────────────────────────


def test_returns_resolved_template_on_match_and_full_creds(
    rollback_session: Session,
) -> None:
    user = create_test_user(rollback_session, "ea_happy")
    app = _create_app(rollback_session)
    _store_user_creds(rollback_session, app.id, user.id, _DEFAULT_USER_CREDS)

    result = get_external_app_credentials(
        rollback_session, user.id, _DEFAULT_MATCHING_URL
    )

    assert result == {
        "client_id": "ORG_CLIENT_ID",
        "client_secret": "ORG_CLIENT_SECRET",
        "access_token": "Bearer USER_ACCESS_TOKEN",
        "refresh_token": "USER_REFRESH_TOKEN",
    }


def test_returns_resolved_template_when_no_user_keys_required(
    rollback_session: Session,
) -> None:
    user = create_test_user(rollback_session, "ea_org_only")
    org_only_creds = {
        "client_id": "ORG_CLIENT_ID",
        "client_secret": "ORG_CLIENT_SECRET",
        "access_token": "ORG_ACCESS_TOKEN",
        "refresh_token": "ORG_REFRESH_TOKEN",
    }
    _create_app(rollback_session, organization_credentials=org_only_creds)

    result = get_external_app_credentials(
        rollback_session, user.id, _DEFAULT_MATCHING_URL
    )

    assert result == {
        "client_id": "ORG_CLIENT_ID",
        "client_secret": "ORG_CLIENT_SECRET",
        "access_token": "Bearer ORG_ACCESS_TOKEN",
        "refresh_token": "ORG_REFRESH_TOKEN",
    }


def test_matches_any_pattern_in_upstream_url_patterns_list(
    rollback_session: Session,
) -> None:
    user = create_test_user(rollback_session, "ea_multi_pattern")
    app = _create_app(
        rollback_session,
        upstream_url_patterns=[
            r"https://api\.example\.com/.*",
            r"https://auth\.example\.com/.*",
        ],
    )
    _store_user_creds(rollback_session, app.id, user.id, _DEFAULT_USER_CREDS)

    assert (
        get_external_app_credentials(
            rollback_session, user.id, "https://api.example.com/v1/me"
        )
        is not None
    )
    assert (
        get_external_app_credentials(
            rollback_session, user.id, "https://auth.example.com/oauth/token"
        )
        is not None
    )


# ── None paths ────────────────────────────────────────────────────


def test_returns_none_when_no_app_matches_url(rollback_session: Session) -> None:
    user = create_test_user(rollback_session, "ea_no_match")
    app = _create_app(rollback_session)
    _store_user_creds(rollback_session, app.id, user.id, _DEFAULT_USER_CREDS)

    result = get_external_app_credentials(
        rollback_session, user.id, "https://unrelated.example.org/foo"
    )

    assert result is None


def test_disabled_app_is_skipped(rollback_session: Session) -> None:
    user = create_test_user(rollback_session, "ea_disabled")
    app = _create_app(rollback_session, enabled=False)
    _store_user_creds(rollback_session, app.id, user.id, _DEFAULT_USER_CREDS)

    result = get_external_app_credentials(
        rollback_session, user.id, _DEFAULT_MATCHING_URL
    )

    assert result is None


def test_returns_none_when_user_has_no_credentials(
    rollback_session: Session,
) -> None:
    user = create_test_user(rollback_session, "ea_no_creds")
    _create_app(rollback_session)

    result = get_external_app_credentials(
        rollback_session, user.id, _DEFAULT_MATCHING_URL
    )

    assert result is None


def test_returns_none_when_user_credentials_are_partial(
    rollback_session: Session,
) -> None:
    user = create_test_user(rollback_session, "ea_partial")
    app = _create_app(rollback_session)
    _store_user_creds(
        rollback_session,
        app.id,
        user.id,
        {"access_token": "USER_ACCESS_TOKEN"},
    )

    result = get_external_app_credentials(
        rollback_session, user.id, _DEFAULT_MATCHING_URL
    )

    assert result is None


def test_returns_none_when_template_placeholder_has_no_source(
    rollback_session: Session,
) -> None:
    """Fail closed when the template references a placeholder no
    credential supplies. Constructed to pass the required-user-keys
    check first (key1 covered by org, key2 covered as a literal),
    then trip format_map on `{missing_source}` inside key2's value."""
    user = create_test_user(rollback_session, "ea_malformed")
    _create_app(
        rollback_session,
        auth_template={
            "key1": "{key1}",
            "key2": "Bearer {missing_source}",
        },
        organization_credentials={
            "key1": "VALUE_1",
            "key2": "this_value_is_unused_at_resolution",
        },
    )

    result = get_external_app_credentials(
        rollback_session, user.id, _DEFAULT_MATCHING_URL
    )

    assert result is None


@pytest.mark.parametrize(
    "bad_value",
    [
        "Bearer {",  # ValueError: unmatched brace
        "Bearer {token!q}",  # ValueError: unknown conversion
        "Bearer {0}",  # IndexError: positional ref against a mapping
        "Bearer {token.missing_attr}",  # AttributeError: attr access
    ],
    ids=["unmatched_brace", "unknown_conversion", "positional_ref", "attr_access"],
)
def test_returns_none_when_template_string_is_malformed(
    rollback_session: Session,
    bad_value: str,
) -> None:
    """`str.format_map` raises more than just KeyError — malformed
    templates can produce ValueError / IndexError / AttributeError /
    TypeError. All of these must fail closed; otherwise a typo in an
    admin-saved template crashes the egress proxy resolution path."""
    user = create_test_user(rollback_session, f"ea_bad_{abs(hash(bad_value))}")
    _create_app(
        rollback_session,
        auth_template={"Authorization": bad_value},
        organization_credentials={"token": "ORG_TOKEN"},
    )

    result = get_external_app_credentials(
        rollback_session, user.id, _DEFAULT_MATCHING_URL
    )

    assert result is None


# =============================================================================
# Edge / security
# =============================================================================


def test_fullmatch_rejects_partial_url_overlap(rollback_session: Session) -> None:
    """`re.fullmatch` (not `search`/`match`) prevents
    `https://api.example.com.evil.com/foo` from matching the pattern
    `https://api\\.example\\.com/.*` and exfiltrating credentials."""
    user = create_test_user(rollback_session, "ea_lookalike")
    app = _create_app(rollback_session)
    _store_user_creds(rollback_session, app.id, user.id, _DEFAULT_USER_CREDS)

    result = get_external_app_credentials(
        rollback_session,
        user.id,
        "https://api.example.com.evil.com/users/me",
    )

    assert result is None


def test_first_app_by_id_wins_when_multiple_apps_match(
    rollback_session: Session,
) -> None:
    """Deterministic resolution under multi-row overlap: lowest id wins."""
    user = create_test_user(rollback_session, "ea_overlap")

    first_app = _create_app(
        rollback_session,
        name="First App",
        organization_credentials={
            "client_id": "FIRST_ORG_CLIENT_ID",
            "client_secret": "FIRST_ORG_CLIENT_SECRET",
        },
    )
    _store_user_creds(
        rollback_session,
        first_app.id,
        user.id,
        {"access_token": "FIRST_USER_TOKEN", "refresh_token": "FIRST_USER_REFRESH"},
    )

    second_app = _create_app(
        rollback_session,
        name="Second App",
        organization_credentials={
            "client_id": "SECOND_ORG_CLIENT_ID",
            "client_secret": "SECOND_ORG_CLIENT_SECRET",
        },
    )
    _store_user_creds(
        rollback_session,
        second_app.id,
        user.id,
        {"access_token": "SECOND_USER_TOKEN", "refresh_token": "SECOND_USER_REFRESH"},
    )

    assert second_app.id > first_app.id

    result = get_external_app_credentials(
        rollback_session, user.id, _DEFAULT_MATCHING_URL
    )

    assert result is not None
    assert result["client_id"] == "FIRST_ORG_CLIENT_ID"
    assert result["access_token"] == "Bearer FIRST_USER_TOKEN"


def test_one_users_credentials_do_not_leak_to_another_user(
    rollback_session: Session,
) -> None:
    user_a = create_test_user(rollback_session, "ea_user_a")
    user_b = create_test_user(rollback_session, "ea_user_b")

    app = _create_app(rollback_session)
    _store_user_creds(rollback_session, app.id, user_a.id, _DEFAULT_USER_CREDS)

    result_a = get_external_app_credentials(
        rollback_session, user_a.id, _DEFAULT_MATCHING_URL
    )
    result_b = get_external_app_credentials(
        rollback_session, user_b.id, _DEFAULT_MATCHING_URL
    )

    assert result_a is not None
    assert result_a["access_token"] == "Bearer USER_ACCESS_TOKEN"
    assert result_b is None
