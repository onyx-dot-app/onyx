from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.marketplace import (
    delete_github_marketplace__no_commit,
    get_github_marketplace,
)
from onyx.db.models import User
from onyx.db.users import delete_user_from_db__no_commit
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.server.features.skill import marketplace_api
from onyx.skills import ingest
from onyx.skills.ingest import delete_bundle_blob
from onyx.skills.marketplace import sync
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.craft.fake_github import (
    FakeGitHub,
    install_fake_github,
)
from tests.external_dependency_unit.craft.marketplace.helpers import Connections


@pytest.fixture
def fake_github(monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    return install_fake_github(monkeypatch)


@pytest.fixture
def connections(monkeypatch: pytest.MonkeyPatch) -> Connections:
    connections = Connections()
    for module in (sync, marketplace_api):
        monkeypatch.setattr(
            module, "github_authorization_for", connections.authorization_for
        )
    return connections


@pytest.fixture
def staged_file_ids(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    stored: list[str] = []
    real = ingest.save_skill_bundle_bytes

    def spy(bundle_bytes: bytes, *, display_name: str, file_store: FileStore) -> str:
        file_id = real(bundle_bytes, display_name=display_name, file_store=file_store)
        stored.append(file_id)
        return file_id

    monkeypatch.setattr(ingest, "save_skill_bundle_bytes", spy)
    return stored


@pytest.fixture(scope="module")
def created_user_ids() -> Iterator[list[UUID]]:
    ids: list[UUID] = []
    yield ids
    with get_session_with_tenant(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
    ) as session:
        for user_id in ids:
            user = session.get(User, user_id)
            if user is not None:
                delete_user_from_db__no_commit(user, session)
        session.commit()


@pytest.fixture
def users(db_session: Session, created_user_ids: list[UUID]) -> tuple[User, User, User]:
    made = tuple(make_user(db_session, standard_account=True) for _ in range(3))
    db_session.commit()
    created_user_ids.extend(user.id for user in made)
    return made[0], made[1], made[2]


@pytest.fixture
def marketplace_ids(db_session: Session) -> Iterator[list[UUID]]:
    ids: list[UUID] = []
    yield ids
    db_session.rollback()
    file_store = get_default_file_store()
    for marketplace_id in ids:
        if get_github_marketplace(marketplace_id, db_session) is None:
            continue
        _, file_ids = delete_github_marketplace__no_commit(marketplace_id, db_session)
        db_session.commit()
        for file_id in file_ids:
            delete_bundle_blob(file_store, file_id)
