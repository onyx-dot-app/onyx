# tests/knowledge_layer/test_db_models.py
import pytest
from knowledge_layer.db.models import TopicExt, WikiPage, WikiPageVersion, CrossRef, IngestRun


def test_table_names():
    assert TopicExt.__tablename__ == "kl_topic_ext"
    assert WikiPage.__tablename__ == "kl_wiki_page"
    assert WikiPageVersion.__tablename__ == "kl_wiki_page_version"
    assert CrossRef.__tablename__ == "kl_cross_ref"
    assert IngestRun.__tablename__ == "kl_ingest_run"


def test_wiki_page_required_fields():
    cols = {c.name for c in WikiPage.__table__.columns}
    assert {"id", "topic_id", "slug", "title", "content", "content_hash", "created_at", "updated_at"} <= cols


def test_ingest_run_statuses():
    from knowledge_layer.db.models import IngestStatus
    assert IngestStatus.PENDING == "pending"
    assert IngestStatus.SUCCESS == "success"
    assert IngestStatus.FAILED == "failed"


def test_relationships_configured():
    """Back-populates are symmetric and cascade is set."""
    from sqlalchemy import inspect as sa_inspect

    topic_rels = {r.key: r for r in sa_inspect(TopicExt).relationships}
    assert "wiki_pages" in topic_rels
    assert "delete-orphan" in topic_rels["wiki_pages"].cascade
    assert "ingest_runs" in topic_rels

    page_rels = {r.key: r for r in sa_inspect(WikiPage).relationships}
    assert "versions" in page_rels
    assert "delete-orphan" in page_rels["versions"].cascade
    assert "outgoing_refs" in page_rels
    assert "delete-orphan" in page_rels["outgoing_refs"].cascade


def test_unique_constraints():
    """Required unique constraints exist on WikiPage and WikiPageVersion."""
    wiki_page_constraint_names = {c.name for c in WikiPage.__table__.constraints}
    assert "uq_kl_wiki_page_topic_slug" in wiki_page_constraint_names

    version_constraint_names = {c.name for c in WikiPageVersion.__table__.constraints}
    assert "uq_kl_wiki_page_version" in version_constraint_names


def test_nullable_settings():
    """Critical columns are non-nullable."""
    cols = {c.name: c for c in WikiPage.__table__.columns}
    assert cols["topic_id"].nullable is False
    assert cols["slug"].nullable is False
    assert cols["content_hash"].nullable is False

    run_cols = {c.name: c for c in IngestRun.__table__.columns}
    assert run_cols["source_doc_id"].nullable is False
    assert run_cols["source_content_hash"].nullable is False
