"""Releases read search_settings.reclaim_status through a non-native Enum, so
IndexReclaimStatusType must store each status by its name. It also reads "RECLAIMD",
which releases without the widening migration write, as RECLAIMED."""

from sqlalchemy import String
from sqlalchemy.dialects import postgresql

from onyx.db.enums import IndexReclaimStatus
from onyx.db.models import IndexReclaimStatusType, SearchSettings

_DIALECT = postgresql.dialect()


def test_every_status_is_stored_by_name_and_reads_back() -> None:
    column_type = IndexReclaimStatusType()
    for status in IndexReclaimStatus:
        stored = column_type.process_bind_param(status, _DIALECT)
        assert stored == status.name
        assert column_type.process_result_value(stored, _DIALECT) == status


def test_short_reclaimed_value_reads_as_reclaimed() -> None:
    assert (
        IndexReclaimStatusType().process_result_value("RECLAIMD", _DIALECT)
        == IndexReclaimStatus.RECLAIMED
    )


def test_every_status_fits_the_column() -> None:
    """A longer status needs a migration that widens the column. A status longer
    than 9 characters also breaks the downgrade of migration ca7cc9a98a6b."""
    column_type = SearchSettings.__table__.c.reclaim_status.type
    assert isinstance(column_type, IndexReclaimStatusType)
    impl = column_type.impl_instance
    assert isinstance(impl, String) and impl.length is not None
    for status in IndexReclaimStatus:
        assert len(status.name) <= impl.length, status
