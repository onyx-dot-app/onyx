"""Database rules of the plugin tables. Each test rolls back."""

from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.db.enums import MarketplaceKind
from onyx.db.models import Marketplace, Plugin, PluginSkill, PluginVersion, User
from tests.external_dependency_unit.craft.db_helpers import make_user


def _user_uploads(db_session: Session, owner: User) -> Marketplace:
    marketplace = Marketplace(
        id=uuid4(),
        kind=MarketplaceKind.USER_UPLOADS,
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
        marketplace_id=marketplace_id,
        author_user_id=author.id if author else None,
        current_version_id=version_id,
    )
    version = PluginVersion(id=version_id, plugin_id=plugin_id, version_number=1)
    return plugin, version


def _frontmatter(name: str) -> dict[str, str]:
    return {"name": name, "description": "d"}


def _refused(db_session: Session, write: Callable[[], object], constraint: str) -> None:
    savepoint = db_session.begin_nested()
    with pytest.raises(IntegrityError, match=constraint):
        write()
        db_session.flush()
    savepoint.rollback()


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
        marketplace = _user_uploads(db_session, owner)
        plugin, version = _plugin_with_first_version(marketplace.id, owner)
        db_session.add_all([plugin, version])
        db_session.flush()
        db_session.add(
            PluginSkill(
                plugin_version_id=version.id,
                path="",
                frontmatter=_frontmatter("deploy"),
            )
        )
        db_session.flush()
    finally:
        db_session.rollback()


def test_database_refuses_invalid_plugins(db_session: Session, owner: User) -> None:
    try:
        marketplace = _user_uploads(db_session, owner)
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

        # A second skill with the same name in one version.
        db_session.add(
            PluginSkill(
                plugin_version_id=existing_version.id,
                path="",
                frontmatter=_frontmatter("deploy"),
            )
        )
        db_session.flush()
        _refused(
            db_session,
            lambda: db_session.add(
                PluginSkill(
                    plugin_version_id=existing_version.id,
                    path="skills/deploy",
                    frontmatter=_frontmatter("deploy"),
                )
            ),
            "uq_plugin_skill_version_name",
        )
        # A frontmatter with no name, or a name that is not a string.
        for frontmatter in ({"description": "d"}, {"name": 7, "description": "d"}):
            _refused(
                db_session,
                lambda frontmatter=frontmatter: db_session.add(
                    PluginSkill(
                        plugin_version_id=existing_version.id,
                        path="skills/other",
                        frontmatter=frontmatter,
                    )
                ),
                "ck_plugin_skill_frontmatter_name",
            )
    finally:
        db_session.rollback()


def test_database_refuses_invalid_marketplaces(
    db_session: Session, owner: User
) -> None:
    try:
        _user_uploads(db_session, owner)
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
            lambda: _user_uploads(db_session, owner),
            "uq_plugin_marketplace_user_uploads_owner",
        )
        # "My uploads" with no owner, and a library with an owner.
        _refused(
            db_session,
            lambda: db_session.add(
                Marketplace(
                    id=uuid4(),
                    kind=MarketplaceKind.USER_UPLOADS,
                    name="My uploads",
                )
            ),
            "ck_plugin_marketplace_owner_iff_user_uploads",
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
            "ck_plugin_marketplace_owner_iff_user_uploads",
        )
    finally:
        db_session.rollback()
