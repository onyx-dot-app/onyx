"""IndexReclaimStatusType must store every status in VARCHAR(8), the column that
databases migrated before RECLAIMED existed have. It must also read "RECLAIMED", which
databases created later already hold."""

from sqlalchemy.dialects import postgresql

from onyx.db.enums import IndexReclaimStatus
from onyx.db.models import IndexReclaimStatusType

# search_settings.reclaim_status on databases migrated before RECLAIMED existed.
# Release branches have no migration that widens it.
PRE_RECLAIMED_COLUMN_LENGTH = 8

_DIALECT = postgresql.dialect()


def test_every_status_fits_the_pre_reclaimed_column() -> None:
    column_type = IndexReclaimStatusType()
    for status in IndexReclaimStatus:
        stored = column_type.process_bind_param(status, _DIALECT)
        assert stored is not None
        assert len(stored) <= PRE_RECLAIMED_COLUMN_LENGTH, status


def test_every_status_reads_back_as_written() -> None:
    column_type = IndexReclaimStatusType()
    for status in IndexReclaimStatus:
        stored = column_type.process_bind_param(status, _DIALECT)
        assert column_type.process_result_value(stored, _DIALECT) == status


def test_statuses_other_than_reclaimed_keep_their_stored_value() -> None:
    """Older versions read these rows, so they must hold the member name as before."""
    column_type = IndexReclaimStatusType()
    for status in IndexReclaimStatus:
        if status == IndexReclaimStatus.RECLAIMED:
            continue
        assert column_type.process_bind_param(status, _DIALECT) == status.name


def test_legacy_reclaimed_value_reads_as_reclaimed() -> None:
    assert (
        IndexReclaimStatusType().process_result_value("RECLAIMED", _DIALECT)
        == IndexReclaimStatus.RECLAIMED
    )
