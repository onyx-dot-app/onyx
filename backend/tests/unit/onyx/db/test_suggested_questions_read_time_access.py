from sqlalchemy import Select, select
from sqlalchemy.dialects import postgresql

from onyx.configs.constants import DocumentSource
from onyx.db.models import ConnectorCredentialPair, Document
from onyx.db.suggested_questions import _skip_read_time_access


def _documents_by_pair() -> Select:
    return select(Document.id).join(
        ConnectorCredentialPair, ConnectorCredentialPair.id == Document.id
    )


def test_nothing_changes_without_censored_sources() -> None:
    stmt = _documents_by_pair()

    assert _skip_read_time_access(stmt, set()) is stmt


def test_censored_sources_are_skipped_unless_a_public_pair_holds_them() -> None:
    stmt = _skip_read_time_access(
        _documents_by_pair(),
        {DocumentSource.SALESFORCE},
    )

    sql = str(
        stmt.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert (
        "JOIN connector ON connector.id = connector_credential_pair.connector_id" in sql
    )
    assert "connector_credential_pair.access_type = 'PUBLIC'" in sql
    assert "connector.source NOT IN ('SALESFORCE')" in sql
