# tests/knowledge_layer/test_index_pages.py
from unittest.mock import MagicMock


def _make_page(slug, title, content="", is_index=False):
    p = MagicMock()
    p.slug = slug
    p.title = title
    p.content = content
    p.is_index_page = is_index
    return p


def test_index_page_content_lists_all_pages():
    from knowledge_layer.background.ingest_worker import _build_index_content

    pages = [
        _make_page("signals", "Trading Signals"),
        _make_page("execution", "Execution Algorithms"),
    ]
    content = _build_index_content("trading", pages)

    assert "# trading Index" in content
    assert "[Trading Signals](signals)" in content
    assert "[Execution Algorithms](execution)" in content


def test_regenerate_index_upserts_index_page():
    from knowledge_layer.background.ingest_worker import _regenerate_index_page
    from knowledge_layer.db.models import WikiPage

    mock_db = MagicMock()
    mock_topic = MagicMock()
    mock_topic.id = 1
    mock_topic.name = "trading"

    pages = [_make_page("signals", "Trading Signals")]
    # No existing index page
    mock_db.query.return_value.filter.return_value.first.return_value = None

    _regenerate_index_page(mock_db, mock_topic, pages)

    added = [c.args[0] for c in mock_db.add.call_args_list]
    wiki_pages_added = [obj for obj in added if isinstance(obj, WikiPage)]
    assert len(wiki_pages_added) == 1
    assert wiki_pages_added[0].is_index_page is True
    assert wiki_pages_added[0].slug == "index"


def test_regenerate_index_updates_when_hash_differs():
    from knowledge_layer.background.ingest_worker import _regenerate_index_page

    mock_db = MagicMock()
    mock_topic = MagicMock()
    mock_topic.id = 1
    mock_topic.name = "trading"

    pages = [_make_page("signals", "Trading Signals")]

    # Existing index page with a stale hash
    existing = MagicMock()
    existing.content_hash = "stale_hash"
    mock_db.query.return_value.filter.return_value.first.return_value = existing

    _regenerate_index_page(mock_db, mock_topic, pages)

    # Content and hash should have been updated
    assert existing.content is not None
    assert existing.content_hash != "stale_hash"


def test_regenerate_index_skips_update_when_hash_matches():
    from knowledge_layer.background.ingest_worker import (
        _build_index_content,
        _regenerate_index_page,
    )
    import hashlib

    mock_db = MagicMock()
    mock_topic = MagicMock()
    mock_topic.id = 1
    mock_topic.name = "trading"

    pages = [_make_page("signals", "Trading Signals")]

    # Compute the current hash so we can simulate an up-to-date index page
    current_content = _build_index_content("trading", pages)
    current_hash = hashlib.sha256(current_content.encode()).hexdigest()

    existing = MagicMock()
    existing.content_hash = current_hash
    original_content = existing.content  # capture original
    mock_db.query.return_value.filter.return_value.first.return_value = existing

    _regenerate_index_page(mock_db, mock_topic, pages)

    # Should not have been updated — hash matched
    assert existing.content == original_content
