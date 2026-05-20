"""External-dependency tests for db.external_app.get_external_app_credentials.

Runs against a real Postgres. The function is exercised end-to-end via
the live SQL engine — no mocks — so behaviors that depend on Postgres
specifics (ARRAY of regex strings, JSONB equality, FK to user) are
covered for real.

Test isolation: setup writes are flushed but never committed, and the
`rollback_session` fixture rolls them back at teardown so each test
sees a clean catalog. Users created via `create_test_user` are
committed and persist (they use unique emails to avoid collisions),
which is fine — the function under test only reads `user_id`.
"""

import uuid
from collections.abc import Generator
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType
from onyx.db.external_app import create_external_app__no_commit
from onyx.db.external_app import get_external_app_credentials
from onyx.db.external_app import upsert_external_app_user_credential__no_commit
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
    """Roll back the session at teardown so per-test app/credential rows
    don't bleed into sibling tests' catalog walks. Wrapped in try/finally
    so a failing assertion still cleans up."""
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
    return create_external_app__no_commit(
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
    upsert_external_app_user_credential__no_commit(
        db_session,
        external_app_id=app_id,
        user_id=user_id,
        user_credentials=creds,
    )


# =============================================================================
# Happy paths
# =============================================================================


def test_returns_resolved_template_on_match_and_full_creds(
    rollback_session: Session,
) -> None:
    """The canonical case: matching URL + user has every required key →
    auth_template is returned with every `{placeholder}` substituted
    from the union of org and user credentials."""
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
    """When every template key is already covered by org credentials,
    the user is "authenticated" without configuring anything — useful
    for shared org-level API integrations."""
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
    """An app with multiple regex patterns matches if *any* of them
    matches the URL. A common shape: one pattern per service of the
    same provider (api host + auth host)."""
    user = create_test_user(rollback_session, "ea_multi_pattern")
    app = _create_app(
        rollback_session,
        upstream_url_patterns=[
            r"https://api\.example\.com/.*",
            r"https://auth\.example\.com/.*",
        ],
    )
    _store_user_creds(rollback_session, app.id, user.id, _DEFAULT_USER_CREDS)

    # First pattern matches.
    assert (
        get_external_app_credentials(
            rollback_session, user.id, "https://api.example.com/v1/me"
        )
        is not None
    )
    # Second pattern matches.
    assert (
        get_external_app_credentials(
            rollback_session, user.id, "https://auth.example.com/oauth/token"
        )
        is not None
    )


# =============================================================================
# None paths
# =============================================================================


def test_returns_none_when_no_app_matches_url(rollback_session: Session) -> None:
    """A URL that no app's patterns cover should resolve to None — the
    proxy will let the request through unauthenticated rather than
    inject something arbitrary."""
    user = create_test_user(rollback_session, "ea_no_match")
    app = _create_app(rollback_session)
    _store_user_creds(rollback_session, app.id, user.id, _DEFAULT_USER_CREDS)

    result = get_external_app_credentials(
        rollback_session, user.id, "https://unrelated.example.org/foo"
    )

    assert result is None


def test_disabled_app_is_skipped(rollback_session: Session) -> None:
    """A disabled app must not produce credentials even when URL + user
    creds are otherwise a perfect match. The `enabled` flag is the
    admin's kill switch — bypassing it would defeat the safety guarantee."""
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
    """The URL matches an enabled app but the user has never configured
    it — they aren't authenticated for this integration yet."""
    user = create_test_user(rollback_session, "ea_no_creds")
    _create_app(rollback_session)

    result = get_external_app_credentials(
        rollback_session, user.id, _DEFAULT_MATCHING_URL
    )

    assert result is None


def test_returns_none_when_user_credentials_are_partial(
    rollback_session: Session,
) -> None:
    """User has stored *some* of the required keys but is missing at
    least one. The proxy must not inject a half-formed auth header."""
    user = create_test_user(rollback_session, "ea_partial")
    app = _create_app(rollback_session)
    _store_user_creds(
        rollback_session,
        app.id,
        user.id,
        {"access_token": "USER_ACCESS_TOKEN"},  # missing refresh_token
    )

    result = get_external_app_credentials(
        rollback_session, user.id, _DEFAULT_MATCHING_URL
    )

    assert result is None


def test_returns_none_when_template_placeholder_has_no_source(
    rollback_session: Session,
) -> None:
    """Admin set up a malformed template that references a placeholder
    nothing supplies. The format_map step raises KeyError and the
    function fails closed rather than injecting a partially-templated
    header."""
    user = create_test_user(rollback_session, "ea_malformed")
    # `key1` is fully covered by the org; `key2`'s value references
    # `{missing_source}` which is neither in org nor expected from user.
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
    """`re.fullmatch` semantics: a pattern like `https://api\\.example\\.com/.*`
    must NOT match `https://api.example.com.evil.com/foo`. If the
    function used `re.search`/`re.match` instead, this lookalike host
    would resolve to real credentials and exfiltrate them."""
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
    """If two apps' patterns happen to cover the same URL, resolution
    must be deterministic — the lower-id (earlier created) app wins.
    This is what prevents "creating a new overlapping app silently
    redirects auth"."""
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

    assert second_app.id > first_app.id  # sanity — Postgres assigned in order

    result = get_external_app_credentials(
        rollback_session, user.id, _DEFAULT_MATCHING_URL
    )

    assert result is not None
    assert result["client_id"] == "FIRST_ORG_CLIENT_ID"
    assert result["access_token"] == "Bearer FIRST_USER_TOKEN"


def test_one_users_credentials_do_not_leak_to_another_user(
    rollback_session: Session,
) -> None:
    """Two users on the same app: only the calling user's stored
    credentials are used. A second user who hasn't configured the app
    must get None even though the first user has it fully set up."""
    user_a = create_test_user(rollback_session, "ea_user_a")
    user_b = create_test_user(rollback_session, "ea_user_b")

    app = _create_app(rollback_session)
    _store_user_creds(rollback_session, app.id, user_a.id, _DEFAULT_USER_CREDS)
    # user_b deliberately has no credentials row.

    result_a = get_external_app_credentials(
        rollback_session, user_a.id, _DEFAULT_MATCHING_URL
    )
    result_b = get_external_app_credentials(
        rollback_session, user_b.id, _DEFAULT_MATCHING_URL
    )

    assert result_a is not None
    assert result_a["access_token"] == "Bearer USER_ACCESS_TOKEN"
    assert result_b is None
