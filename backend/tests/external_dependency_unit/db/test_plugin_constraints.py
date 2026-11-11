"""Database rules of the plugin tables. Each test rolls back."""

from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.db.enums import MarketplaceKind, PluginKind
from onyx.db.models import Marketplace, Plugin, PluginSkill, PluginVersion, User
from tests.external_dependency_unit.craft.db_helpers import make_user


def _check_deferred_constraints(db_session: Session) -> None:
    """Run the checks a commit would run, without a commit."""
    db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def _account_uploads(db_session: Session, owner: User) -> Marketplace:
    marketplace = Marketplace(
        id=uuid4(),
        kind=MarketplaceKind.ACCOUNT_UPLOADS,
        name="My uploads",
        owner_user_id=owner.id,
    )
    db_session.add(marketplace)
    db_session.flush()
    return marketplace


def _plugin_with_first_version(
    marketplace_id: UUID | None,
    author: User | None,
    name: str = "deploy",
) -> tuple[Plugin, PluginVersion]:
    plugin_id, version_id = uuid4(), uuid4()
    plugin = Plugin(
        id=plugin_id,
        name=name,
        description="d",
        kind=PluginKind.SKILL,
        marketplace_id=marketplace_id,
        author_user_id=author.id if author else None,
        current_version_id=version_id,
    )
    version = PluginVersion(id=version_id, plugin_id=plugin_id, version_number=1)
    return plugin, version


def _refused(db_session: Session, write: Callable[[], object], constraint: str) -> None:
    savepoint = db_session.begin_nested()
    with pytest.raises(IntegrityError, match=constraint):
        write()
        db_session.flush()
        _check_deferred_constraints(db_session)
    savepoint.rollback()
    db_session.execute(text("SET CONSTRAINTS ALL DEFERRED"))


@pytest.fixture
def owner(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> User:
    return make_user(db_session, email_prefix="plugin_owner")


def test_one_transaction_inserts_a_plugin_and_its_first_version(
    db_session: Session, owner: User
) -> None:
    try:
        marketplace = _account_uploads(db_session, owner)
        plugin, version = _plugin_with_first_version(marketplace.id, owner)
        db_session.add_all([plugin, version])
        db_session.flush()
        db_session.add(
            PluginSkill(plugin_version_id=version.id, path="", name="deploy")
        )
        db_session.flush()
        _check_deferred_constraints(db_session)
    finally:
        db_session.rollback()


def test_database_refuses_invalid_plugins(db_session: Session, owner: User) -> None:
    try:
        marketplace = _account_uploads(db_session, owner)
        existing, existing_version = _plugin_with_first_version(marketplace.id, owner)
        db_session.add_all([existing, existing_version])
        db_session.flush()

        # Not published and no author.
        _refused(
            db_session,
            lambda: db_session.add_all(
                _plugin_with_first_version(marketplace.id, None, name="orphan")
            ),
            "ck_private_plugin_has_owner",
        )
        # No marketplace.
        _refused(
            db_session,
            lambda: db_session.add_all(
                _plugin_with_first_version(None, owner, name="homeless")
            ),
            "marketplace_id",
        )
        # A second plugin with the same name in one marketplace.
        _refused(
            db_session,
            lambda: db_session.add_all(
                _plugin_with_first_version(marketplace.id, owner)
            ),
            "uq_plugin_marketplace_name",
        )

        # A current version that belongs to another plugin.
        def _foreign_current_version() -> None:
            plugin, version = _plugin_with_first_version(
                marketplace.id, owner, name="pointer"
            )
            plugin.current_version_id = existing_version.id
            db_session.add_all([plugin, version])

        _refused(db_session, _foreign_current_version, "fk_plugin_current_version")

        # A published version that belongs to another plugin.
        def _foreign_published_version() -> None:
            plugin, version = _plugin_with_first_version(
                marketplace.id, owner, name="published"
            )
            plugin.published_version_id = existing_version.id
            db_session.add_all([plugin, version])

        _refused(db_session, _foreign_published_version, "fk_plugin_published_version")

        # A second skill with the same name in one version.
        db_session.add(
            PluginSkill(plugin_version_id=existing_version.id, path="", name="deploy")
        )
        db_session.flush()
        _refused(
            db_session,
            lambda: db_session.add(
                PluginSkill(
                    plugin_version_id=existing_version.id,
                    path="skills/deploy",
                    name="deploy",
                )
            ),
            "uq_plugin_skill_version_name",
        )
    finally:
        db_session.rollback()


def test_database_refuses_invalid_marketplaces(
    db_session: Session, owner: User
) -> None:
    try:
        _account_uploads(db_session, owner)
        # The migration added the one Organization library of the tenant.
        _refused(
            db_session,
            lambda: db_session.add(
                Marketplace(
                    id=uuid4(),
                    kind=MarketplaceKind.ORGANIZATION_LIBRARY,
                    name="Organization library",
                )
            ),
            "uq_plugin_marketplace_organization_library",
        )
        # A second "My uploads" for one user.
        _refused(
            db_session,
            lambda: _account_uploads(db_session, owner),
            "uq_plugin_marketplace_account_uploads_owner",
        )
        # "My uploads" with no owner, and a library with an owner.
        _refused(
            db_session,
            lambda: db_session.add(
                Marketplace(
                    id=uuid4(),
                    kind=MarketplaceKind.ACCOUNT_UPLOADS,
                    name="My uploads",
                )
            ),
            "ck_plugin_marketplace_owner_iff_account_uploads",
        )
        _refused(
            db_session,
            lambda: db_session.add(
                Marketplace(
                    id=uuid4(),
                    kind=MarketplaceKind.ORGANIZATION_LIBRARY,
                    name="Organization library",
                    owner_user_id=owner.id,
                )
            ),
            "ck_plugin_marketplace_owner_iff_account_uploads",
        )
    finally:
        db_session.rollback()
