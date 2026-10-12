"""Migration 2adc6821bab2 copies the current groups of PRIVATE cc-pairs into
the data-access table. Runs the upgrade in the test transaction and rolls it
back."""

import importlib.util
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import AccessType, ConnectorManageRole
from onyx.db.models import (
    UserGroup,
    UserGroup__CCPairDataAccess,
    UserGroup__ConnectorCredentialPair,
)
from tests.external_dependency_unit.indexing_helpers import make_cc_pair

_MIGRATION_PATH = (
    Path(__file__).parents[3]
    / "alembic/versions/2adc6821bab2_copy_private_cc_pair_groups_to_data_.py"
)


def _run_upgrade(db_session: Session) -> None:
    spec = importlib.util.spec_from_file_location("copy_migration", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with Operations.context(MigrationContext.configure(db_session.connection())):
        migration.upgrade()


def test_copies_current_groups_of_private_pairs(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    try:
        private_pair = make_cc_pair(db_session, commit=False)
        private_pair.access_type = AccessType.PRIVATE
        public_pair = make_cc_pair(db_session, commit=False)
        current_group, outdated_group, copied_group = (
            UserGroup(name=f"copy-migration-{uuid4().hex[:8]}") for _ in range(3)
        )
        db_session.add_all([current_group, outdated_group, copied_group])
        db_session.flush()

        for pair, group, is_current in (
            (private_pair, current_group, True),
            (private_pair, outdated_group, False),
            (private_pair, copied_group, True),
            (public_pair, current_group, True),
        ):
            db_session.add(
                UserGroup__ConnectorCredentialPair(
                    user_group_id=group.id,
                    cc_pair_id=pair.id,
                    is_current=is_current,
                    role=ConnectorManageRole.EDITOR,
                )
            )
        # An existing row is kept, not duplicated.
        db_session.add(
            UserGroup__CCPairDataAccess(
                user_group_id=copied_group.id, cc_pair_id=private_pair.id
            )
        )
        db_session.flush()

        _run_upgrade(db_session)

        rows = set(
            db_session.execute(
                select(
                    UserGroup__CCPairDataAccess.cc_pair_id,
                    UserGroup__CCPairDataAccess.user_group_id,
                ).where(
                    UserGroup__CCPairDataAccess.cc_pair_id.in_(
                        [private_pair.id, public_pair.id]
                    )
                )
            ).tuples()
        )
        assert rows == {
            (private_pair.id, current_group.id),
            (private_pair.id, copied_group.id),
        }
    finally:
        db_session.rollback()
