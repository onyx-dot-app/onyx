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
    from knowledge_layer.db.models import IngestStatus

    content = "No change here."
    content_hash = hashlib.sha256(content.encode()).hexdigest()

    last_run = MagicMock()
    last_run.source_content_hash = content_hash
    last_run.status = IngestStatus.SUCCESS

    assert _should_skip(content_hash, last_run) is True


def test_processes_new_content():
    import hashlib
    from knowledge_layer.background.ingest_worker import _should_skip
    from knowledge_layer.db.models import IngestStatus

    old_hash = hashlib.sha256(b"old").hexdigest()
    new_hash = hashlib.sha256(b"new").hexdigest()

    last_run = MagicMock()
    last_run.source_content_hash = old_hash
    last_run.status = IngestStatus.SUCCESS

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


def test_ingest_file_sets_failed_on_exception():
    """ingest_file sets status=FAILED and re-raises on provider error."""
    from knowledge_layer.background.ingest_worker import ingest_file
    from knowledge_layer.db.models import IngestStatus

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    mock_db.query.return_value.filter.return_value.all.return_value = []
    mock_db.query.return_value.filter.return_value.first.return_value = None
    mock_db.query.return_value.filter.return_value.count.return_value = 0

    mock_provider = MagicMock()
    mock_provider.ingest_call.side_effect = RuntimeError("LLM unavailable")

    topic = _make_topic()
    run_holder = []

    original_add = mock_db.add
    def capture_add(obj):
        from knowledge_layer.db.models import IngestRun
        if isinstance(obj, IngestRun):
            run_holder.append(obj)
        return original_add(obj)
    mock_db.add = capture_add

    with pytest.raises(RuntimeError, match="LLM unavailable"):
        ingest_file(
            db=mock_db,
            topic=topic,
            file_path="/raw/test/note.md",
            file_content="content",
            provider=mock_provider,
        )

    assert len(run_holder) >= 1
    failed_run = run_holder[0]
    assert failed_run.status == IngestStatus.FAILED
    assert "LLM unavailable" in failed_run.error_msg
