import pytest
from pytest_alembic.runner import MigrationContext


@pytest.mark.alembic
def test_each_revision_round_trip(alembic_runner: MigrationContext) -> None:
    previous = "base"
    minimum = alembic_runner.config.minimum_downgrade_revision
    check_downgrade = minimum is None
    for revision in alembic_runner.history.revisions[1:-1]:
        alembic_runner.migrate_up_to(revision, current=previous, return_current=False)
        if check_downgrade:
            try:
                alembic_runner.migrate_down_to(
                    previous, current=revision, return_current=False
                )
                alembic_runner.migrate_up_to(
                    revision, current=previous, return_current=False
                )
            except Exception as error:
                pytest.fail(
                    f"Revision {revision} cannot downgrade and upgrade: {error}"
                )
        check_downgrade = check_downgrade or revision == minimum
        previous = revision
