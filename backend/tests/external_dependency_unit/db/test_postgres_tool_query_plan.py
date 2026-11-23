"""Query plans of the postgres_query document queries on a skewed corpus.

One large connector and many small ones make Postgres underestimate the
large pair when a query joins the pair table. On large deployments it then
visited every document of that pair to apply a selective date filter, and the
query timed out.
"""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from onyx.db.models import (
    ConnectorCredentialPair,
    Document,
    DocumentByConnectorCredentialPair,
)
from onyx.db.postgres_tool import count_documents_for_tool
from onyx.db.postgres_tool_models import DocumentScope
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_LARGE_PAIR_DOCS = 40_000
_SMALL_PAIRS = 40
_SMALL_PAIR_DOCS = 25
_RECENT_DOCS = 50


@pytest.fixture
def skewed_pairs(
    db_session: Session,
) -> Generator[tuple[ConnectorCredentialPair, str], None, None]:
    prefix = f"plan-{uuid4().hex[:8]}-"
    pairs = [make_cc_pair(db_session) for _ in range(_SMALL_PAIRS + 1)]
    large = pairs[0]
    try:
        for pair in pairs:
            size = _LARGE_PAIR_DOCS if pair is large else _SMALL_PAIR_DOCS
            params = {
                "prefix": f"{prefix}{pair.id}-",
                "size": size,
                # Only the large pair has recent documents.
                "recent": _RECENT_DOCS if pair is large else 0,
                "connector_id": pair.connector_id,
                "credential_id": pair.credential_id,
            }
            db_session.execute(
                text(
                    "INSERT INTO document (id, boost, hidden, semantic_id, doc_updated_at) "
                    "SELECT :prefix || i, 0, false, 'doc ' || i, "
                    "CASE WHEN i <= :recent THEN now() - interval '1 day' "
                    "ELSE now() - interval '400 days' END "
                    "FROM generate_series(1, :size) i"
                ),
                params,
            )
            db_session.execute(
                text(
                    "INSERT INTO document_by_connector_credential_pair "
                    "(id, connector_id, credential_id, has_been_indexed) "
                    "SELECT :prefix || i, :connector_id, :credential_id, true "
                    "FROM generate_series(1, :size) i"
                ),
                params,
            )
        db_session.commit()
        db_session.execute(text("ANALYZE document"))
        db_session.execute(text("ANALYZE document_by_connector_credential_pair"))
        # Statistics are transactional: a rollback would drop them.
        db_session.commit()
        yield large, prefix
    finally:
        db_session.rollback()
        db_session.execute(
            delete(DocumentByConnectorCredentialPair).where(
                DocumentByConnectorCredentialPair.id.startswith(prefix)
            )
        )
        db_session.execute(delete(Document).where(Document.id.startswith(prefix)))
        db_session.commit()
        for pair in pairs:
            cleanup_cc_pair(db_session, pair)


def _pair_row_underestimates(plan: dict[str, Any]) -> list[float]:
    """Actual over estimated rows per loop of each scan of the pair table."""
    ratios = [
        plan["Actual Rows"] / max(plan["Plan Rows"], 1)
        for _ in [None]
        if plan.get("Relation Name") == "document_by_connector_credential_pair"
    ]
    for child in plan.get("Plans", []):
        ratios.extend(_pair_row_underestimates(child))
    return ratios


def test_planner_sees_the_size_of_a_large_pair(
    db_session: Session,
    skewed_pairs: tuple[ConnectorCredentialPair, str],  # noqa: ARG001
) -> None:
    statements: list[tuple[str, Any]] = []

    def capture(
        conn: Connection,  # noqa: ARG001
        cursor: Any,  # noqa: ARG001
        statement: str,
        parameters: Any,
        context: Any,  # noqa: ARG001
        executemany: bool,  # noqa: ARG001
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT COUNT(DISTINCT"):
            statements.append((statement, parameters))

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        count = count_documents_for_tool(
            db_session,
            None,
            [],
            updated_after=datetime.now(timezone.utc) - timedelta(days=7),
            scope=DocumentScope(),
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
        db_session.rollback()

    assert count >= _RECENT_DOCS
    statement, parameters = statements[-1]
    raw = db_session.connection().connection.cursor()
    try:
        raw.execute(
            "EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON) " + statement, parameters
        )
        row = raw.fetchone()
        assert row is not None
        plan = row[0][0]["Plan"]
    finally:
        raw.close()
        db_session.rollback()
    # Joined to the pair table, each pair was estimated from the two key
    # columns alone, about 40x below the large pair's size.
    ratios = _pair_row_underestimates(plan)
    assert ratios
    assert max(ratios) < 10
