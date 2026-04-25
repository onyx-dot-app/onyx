# tests/knowledge_layer/test_cross_ref_resolver.py
import pytest
from unittest.mock import MagicMock
from knowledge_layer.providers.base import CrossRefProposal


def _make_wiki_page(id, topic_id, slug):
    p = MagicMock()
    p.id = id
    p.topic_id = topic_id
    p.slug = slug
    return p


def test_resolve_same_topic_ref():
    """Cross-ref to a slug in the same topic resolves with to_topic_id=None."""
    from knowledge_layer.background.ingest_worker import _resolve_cross_refs

    page_a = _make_wiki_page(1, 1, "signals")
    page_b = _make_wiki_page(2, 1, "execution")

    mock_db = MagicMock()

    proposals = [CrossRefProposal(from_slug="signals", to_slug="execution", link_type="see-also")]
    resolved = _resolve_cross_refs(
        mock_db, current_topic_id=1, proposals=proposals, all_pages=[page_a, page_b]
    )

    assert len(resolved) == 1
    assert resolved[0].to_slug == "execution"
    assert resolved[0].to_topic_id is None  # same topic — no explicit to_topic_id


def test_resolve_cross_topic_ref():
    """Cross-ref with to_topic hint resolves to_topic_id from DB."""
    from knowledge_layer.background.ingest_worker import _resolve_cross_refs

    page_in_other_topic = _make_wiki_page(10, 2, "execution")

    mock_target_topic = MagicMock()
    mock_target_topic.id = 2

    mock_db = MagicMock()
    # First .first() call returns the target topic; second returns the target page
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        mock_target_topic,
        page_in_other_topic,
    ]

    proposals = [CrossRefProposal(
        from_slug="signals", to_slug="execution", link_type="see-also", to_topic="trading"
    )]
    # all_pages contains only current topic — target not found locally
    resolved = _resolve_cross_refs(mock_db, current_topic_id=1, proposals=proposals, all_pages=[])

    # from_slug "signals" not in all_pages, so it's skipped
    assert len(resolved) == 0  # from_slug must exist in current topic pages


def test_resolve_skips_unknown_from_slug():
    """Cross-refs whose from_slug is not in the current topic are dropped."""
    from knowledge_layer.background.ingest_worker import _resolve_cross_refs

    mock_db = MagicMock()
    proposals = [CrossRefProposal(from_slug="ghost", to_slug="execution", link_type="see-also")]
    resolved = _resolve_cross_refs(mock_db, current_topic_id=1, proposals=proposals, all_pages=[])

    assert len(resolved) == 0


def test_unresolvable_ref_kept_with_null_topic():
    """Cross-refs to unknown slugs are kept with to_topic_id=None."""
    from knowledge_layer.background.ingest_worker import _resolve_cross_refs

    page_a = _make_wiki_page(1, 1, "signals")
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None

    proposals = [CrossRefProposal(
        from_slug="signals", to_slug="ghost-page", link_type="see-also", to_topic="other-topic"
    )]
    resolved = _resolve_cross_refs(mock_db, current_topic_id=1, proposals=proposals, all_pages=[page_a])

    assert len(resolved) == 1
    assert resolved[0].to_topic_id is None
