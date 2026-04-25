import hashlib
import pytest
from unittest.mock import MagicMock, patch


def _make_topic(id=1, name="test", watch_path="/raw/test"):
    t = MagicMock()
    t.id = id
    t.name = name
    t.watch_path = watch_path
    return t


def test_sha256_content_hash():
    from knowledge_layer.background.ingest_worker import _sha256
    content = "Hello world"
    expected = hashlib.sha256(content.encode()).hexdigest()
    assert _sha256(content) == expected


def test_skips_unchanged_content():
    import hashlib
    from knowledge_layer.background.ingest_worker import _should_skip

    content = "No change here."
    content_hash = hashlib.sha256(content.encode()).hexdigest()

    last_run = MagicMock()
    last_run.source_content_hash = content_hash
    last_run.status = "success"

    assert _should_skip(content_hash, last_run) is True


def test_processes_new_content():
    import hashlib
    from knowledge_layer.background.ingest_worker import _should_skip

    old_hash = hashlib.sha256(b"old").hexdigest()
    new_hash = hashlib.sha256(b"new").hexdigest()

    last_run = MagicMock()
    last_run.source_content_hash = old_hash
    last_run.status = "success"

    assert _should_skip(new_hash, last_run) is False


def test_processes_when_no_prior_run():
    import hashlib
    from knowledge_layer.background.ingest_worker import _should_skip
    content_hash = hashlib.sha256(b"content").hexdigest()
    assert _should_skip(content_hash, None) is False


def test_ingest_file_writes_wiki_pages():
    """ingest_file writes wiki pages to DB when LLM returns pages."""
    from knowledge_layer.background.ingest_worker import ingest_file
    from knowledge_layer.providers.base import WikiPageDraft, IngestResult

    mock_db = MagicMock()
    # last_run query: no prior run
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    # existing pages query: empty
    mock_db.query.return_value.filter.return_value.all.return_value = []
    # WikiPage upsert lookup: no existing page
    mock_db.query.return_value.filter.return_value.first.return_value = None
    # version count: 0
    mock_db.query.return_value.filter.return_value.count.return_value = 0

    mock_provider = MagicMock()
    mock_provider.ingest_call.return_value = IngestResult(
        wiki_pages=[WikiPageDraft(slug="test-page", title="Test Page", content="Content.")],
        cross_refs=[]
    )

    topic = _make_topic()

    ingest_file(
        db=mock_db,
        topic=topic,
        file_path="/raw/test/note.md",
        file_content="# Note\nSome content.",
        provider=mock_provider,
    )

    mock_db.add.assert_called()
    mock_db.commit.assert_called()
