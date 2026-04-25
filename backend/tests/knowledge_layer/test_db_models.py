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
