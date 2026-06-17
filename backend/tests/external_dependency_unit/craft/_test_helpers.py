"""Shared row factories for craft external-dependency tests.

Underscore-prefixed module so pytest does not collect it. Helpers live here
(not in ``conftest.py``) because they're plain functions — callers want to
import them, not receive them as fixtures.

Conventions:

- Every helper takes ``db_session`` as the first argument and flushes (does not
  commit) so the surrounding test owns transaction boundaries.
- Every helper returns the created row.
- IDs and emails are randomised per call so tests can run in parallel against
  the same Postgres without colliding.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID
from uuid import uuid4

from fastapi_users.password import PasswordHelper
from sqlalchemy import delete
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.enums import AccessType
from onyx.db.enums import AccountType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.db.enums import SandboxStatus
from onyx.db.models import ActionApproval
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppPolicy
from onyx.db.models import ExternalAppUserCredential
from onyx.db.models import Sandbox
from onyx.db.models import Skill
from onyx.db.models import Skill__UserGroup
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
from onyx.db.models import UserGroup__ConnectorCredentialPair
from onyx.db.models import UserRole
from onyx.external_apps.matching.engine import MatchedAction
from onyx.server.features.build.sandbox.models import LLMProviderConfig


def _set_created_at(
    db_session: Session,
    model: type[ActionApproval],
    pk: UUID,
    when: datetime,
) -> None:
    """Force a row's ``created_at`` to ``when``, bypassing ``server_default``."""
    db_session.execute(
        update(model).where(model.approval_id == pk).values(created_at=when)
    )
    db_session.commit()


def make_user(
    db_session: Session,
    *,
    role: UserRole = UserRole.EXT_PERM_USER,
    email_prefix: str = "craft_helper",
) -> User:
    """Create a single ``User`` row with random email + UUID."""
    helper = PasswordHelper()
    account_type = (
        AccountType.EXT_PERM_USER
        if role == UserRole.EXT_PERM_USER
        else AccountType.STANDARD
    )
    user = User(
        id=uuid4(),
        email=f"{email_prefix}_{uuid4().hex[:8]}@example.com",
        hashed_password=helper.hash(helper.generate()),
        is_active=True,
        is_superuser=False,
        is_verified=True,
        role=role,
        account_type=account_type,
    )
    db_session.add(user)
    db_session.flush()
    return user


def make_group(db_session: Session, name: str | None = None) -> UserGroup:
    """Create a single ``UserGroup`` row with a random name if none supplied."""
    group = UserGroup(name=name or f"craft-group-{uuid4().hex[:8]}")
    db_session.add(group)
    db_session.flush()
    return group


def add_user_to_group(
    db_session: Session, user: User, group: UserGroup
) -> User__UserGroup:
    """Insert a ``User__UserGroup`` membership row."""
    membership = User__UserGroup(user_id=user.id, user_group_id=group.id)
    db_session.add(membership)
    db_session.flush()
    return membership


def make_sandbox(
    db_session: Session,
    user: User,
    status: SandboxStatus = SandboxStatus.RUNNING,
) -> Sandbox:
    """Create a single ``Sandbox`` row owned by ``user``."""
    sandbox = Sandbox(id=uuid4(), user_id=user.id, status=status)
    db_session.add(sandbox)
    db_session.flush()
    return sandbox


def make_skill(
    db_session: Session,
    *,
    slug: str | None = None,
    is_public: bool = False,
    enabled: bool = True,
) -> Skill:
    """Create a single custom ``Skill`` row.

    Bundle metadata (``bundle_file_id``, ``bundle_sha256``) is filled with
    placeholder values; tests that need a real bundle should use the
    ``seeded_skill`` fixture from ``conftest.py`` instead.
    """
    skill = Skill(
        id=uuid4(),
        slug=slug or f"helper-skill-{uuid4().hex[:8]}",
        name=slug or "helper-skill",
        description="d",
        bundle_file_id=f"bundle-{uuid4().hex[:8]}",
        bundle_sha256="0" * 64,
        is_public=is_public,
        enabled=enabled,
    )
    db_session.add(skill)
    db_session.flush()
    return skill


def make_built_in_skill_row(
    db_session: Session,
    *,
    built_in_skill_id: str,
    slug: str | None = None,
    name: str | None = None,
    description: str = "test built-in",
    is_public: bool = True,
    enabled: bool = True,
) -> Skill:
    """Insert a built-in-style ``Skill`` row pointing at a
    ``built_in_skill_id``. Slug defaults to ``built_in_skill_id`` (the
    default seeder convention), but can be overridden to test the
    multi-row case where several skills share the same built-in id.
    Bundle fields stay NULL (required by the XOR check constraint)."""
    skill = Skill(
        id=uuid4(),
        slug=slug or built_in_skill_id,
        name=name or built_in_skill_id,
        description=description,
        built_in_skill_id=built_in_skill_id,
        bundle_file_id=None,
        bundle_sha256=None,
        is_public=is_public,
        enabled=enabled,
    )
    db_session.add(skill)
    db_session.flush()
    return skill


def reset_built_in_skill_row(
    db_session: Session,
    *,
    built_in_skill_id: str,
    slug: str | None = None,
    name: str | None = None,
    description: str = "test built-in",
    is_public: bool = True,
    enabled: bool = True,
) -> Skill:
    """Idempotently (re)create a built-in row for ``built_in_skill_id``.

    Deletes any existing row with the same slug first, so tests stay
    robust whether or not the migration-seeded canonical row is present
    (it always is on a migrated DB, but another test's teardown may have
    removed it). Returns the freshly inserted row.
    """
    target_slug = slug or built_in_skill_id
    db_session.execute(delete(Skill).where(Skill.slug == target_slug))
    return make_built_in_skill_row(
        db_session,
        built_in_skill_id=built_in_skill_id,
        slug=slug,
        name=name,
        description=description,
        is_public=is_public,
        enabled=enabled,
    )


def make_external_app(
    db_session: Session,
    *,
    skill: Skill,
    auth_template: dict[str, Any],
    organization_credentials: dict[str, Any] | None = None,
    app_type: ExternalAppType = ExternalAppType.CUSTOM,
    upstream_url_patterns: list[str] | None = None,
    action_policies: dict[str, EndpointPolicy] | None = None,
) -> ExternalApp:
    """Insert an ``ExternalApp`` row backing ``skill``, plus any per-action
    policy overrides in ``action_policies`` (``{action_id: policy}``)."""
    app = ExternalApp(
        skill_id=skill.id,
        app_type=app_type,
        upstream_url_patterns=upstream_url_patterns or [],
        auth_template=auth_template,
        organization_credentials=organization_credentials or {},
    )
    db_session.add(app)
    db_session.flush()
    for action_id, policy in (action_policies or {}).items():
        db_session.add(
            ExternalAppPolicy(
                external_app_id=app.id,
                action_id=action_id,
                policy=policy,
            )
        )
    db_session.flush()
    return app


def make_user_credential(
    db_session: Session,
    *,
    app: ExternalApp,
    user: User,
    user_credentials: dict[str, Any],
) -> ExternalAppUserCredential:
    """Insert an ``ExternalAppUserCredential`` row for ``user`` + ``app``."""
    cred = ExternalAppUserCredential(
        external_app_id=app.id,
        user_id=user.id,
        user_credentials=user_credentials,
    )
    db_session.add(cred)
    db_session.flush()
    return cred


def grant_skill_to_group(
    db_session: Session, skill: Skill, group: UserGroup
) -> Skill__UserGroup:
    """Insert a ``Skill__UserGroup`` grant row."""
    grant = Skill__UserGroup(skill_id=skill.id, user_group_id=group.id)
    db_session.add(grant)
    db_session.flush()
    return grant


def make_cc_pair(
    db_session: Session,
    source: DocumentSource,
    *,
    user: User | None = None,
    access_type: AccessType = AccessType.PUBLIC,
    group: UserGroup | None = None,
    name_prefix: str = "test",
) -> ConnectorCredentialPair:
    """Create a Connector + Credential + ConnectorCredentialPair row trio.

    For per-user visibility tests:
    - ``access_type=PUBLIC`` + ``user=None`` → visible to everyone (default).
    - ``access_type=PRIVATE`` + ``user=<user>`` → visible only to creator
      (the creator-id branch of ``_add_user_filters``).
    - ``access_type=PRIVATE`` + ``group=<group>`` → visible only via the
      ``UserGroup__ConnectorCredentialPair`` mapping; pass ``user=None`` to
      test pure group-based visibility (the credential's ``user_id`` is also
      left ``None`` so the creator-id branch can't accidentally match).

    The ``user`` argument controls both ``Credential.user_id`` and
    ``ConnectorCredentialPair.creator_id``. When supplied with PUBLIC, it is
    set on both for convenience. When ``user`` is None for PRIVATE+group, both
    are explicitly None so visibility comes solely from the group mapping.
    """
    suffix = uuid4().hex[:6]
    connector = Connector(
        name=f"{name_prefix}-{source.value}-{suffix}",
        source=source,
        input_type=None,
        connector_specific_config={},
    )
    db_session.add(connector)
    db_session.flush()

    credential = Credential(
        credential_json={},
        user_id=user.id if user is not None else None,
        source=source,
    )
    db_session.add(credential)
    db_session.flush()

    cc_pair = ConnectorCredentialPair(
        name=f"{name_prefix}-cc-{suffix}",
        connector_id=connector.id,
        credential_id=credential.id,
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=access_type,
        creator_id=user.id if user is not None else None,
    )
    db_session.add(cc_pair)
    db_session.flush()

    if group is not None:
        db_session.add(
            UserGroup__ConnectorCredentialPair(
                user_group_id=group.id,
                cc_pair_id=cc_pair.id,
            )
        )
        db_session.flush()

    return cc_pair


def default_llm_config(
    provider: str = "openai",
    model_name: str = "gpt-5-mini",
    api_key: str = "test-key",
) -> LLMProviderConfig:
    """Standard ``LLMProviderConfig`` for tests that don't care about specifics."""
    return LLMProviderConfig(
        provider=provider,
        model_name=model_name,
        api_key=api_key,
        api_base=None,
    )


def action_entry(
    action_type: str,
    *,
    display_name: str = "Action",
    description: str = "An action.",
    policy: EndpointPolicy = EndpointPolicy.ASK,
) -> dict[str, Any]:
    """JSONB-shape dict for one `ActionApproval.actions` entry. Routes
    through `MatchedAction` so the shape can't drift from the production
    model."""
    return MatchedAction(
        action_type=action_type,
        display_name=display_name,
        description=description,
        policy=policy,
    ).model_dump(mode="json")


def default_action_entries() -> list[dict[str, Any]]:
    """Single ASK entry for tests that don't care about catalog specifics."""
    return [
        action_entry(
            "shell.exec",
            display_name="Run command",
            description="Run a shell command.",
        )
    ]
