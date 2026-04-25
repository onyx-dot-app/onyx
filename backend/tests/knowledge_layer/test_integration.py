# tests/knowledge_layer/test_integration.py
"""
Integration tests: full ingest → query round trip.
Requires: running Postgres (docker compose up), ANTHROPIC_API_KEY env var.
Run with: pytest tests/knowledge_layer/test_integration.py -v -m integration
"""
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def db_session():
    from onyx.db.engine.sql_engine import SqlEngine, get_session_with_current_tenant
    SqlEngine.init_engine(pool_size=2, max_overflow=2)
    with get_session_with_current_tenant() as db:
        yield db


@pytest.fixture(autouse=True)
def cleanup_topics(db_session):
    yield
    from knowledge_layer.db.models import TopicExt
    try:
        db_session.rollback()  # clear any failed transaction before cleanup
        db_session.query(TopicExt).filter(
            TopicExt.name.in_(["integ-topic-alpha", "integ-topic-beta"])
        ).delete(synchronize_session=False)
        db_session.commit()
    except Exception:
        pass  # best-effort cleanup; don't mask the original test failure


def test_ingest_and_query_single_topic(db_session, tmp_path):
    """Drop a markdown file → ingest → query → get answer with citation."""
    from knowledge_layer.db.models import TopicExt, WikiPage
    from knowledge_layer.background.ingest_worker import ingest_file
    from knowledge_layer.providers.claude import ClaudeProvider

    topic = TopicExt(
        name="integ-topic-alpha",
        description="Alpha integration test topic",
        watch_path=str(tmp_path),
    )
    db_session.add(topic)
    db_session.commit()
    db_session.refresh(topic)

    raw_file = tmp_path / "alpha-note.md"
    raw_file.write_text(
        "# Alpha System\n\nThe alpha system processes trades at 10ms latency. "
        "It uses a VWAP algorithm for execution."
    )

    provider = ClaudeProvider()
    ingest_file(
        db=db_session,
        topic=topic,
        file_path=str(raw_file),
        file_content=raw_file.read_text(),
        provider=provider,
    )

    pages = db_session.query(WikiPage).filter(WikiPage.topic_id == topic.id).all()
    assert len(pages) >= 1
    all_content = " ".join(p.content for p in pages).lower()
    assert "alpha" in all_content or "vwap" in all_content or "latency" in all_content

    from knowledge_layer.providers.base import WikiPageDraft
    drafts = [WikiPageDraft(slug=p.slug, title=p.title, content=p.content) for p in pages]
    result = provider.query_call(
        question="What latency does the alpha system have?",
        wiki_pages=drafts,
    )
    assert len(result.answer) > 0
    assert len(result.citations) >= 1


def test_two_topics_do_not_bleed(db_session, tmp_path):
    """Wiki pages from topic A must not appear when querying topic B."""
    from knowledge_layer.db.models import TopicExt, WikiPage
    from knowledge_layer.background.ingest_worker import ingest_file
    from knowledge_layer.providers.claude import ClaudeProvider

    dir_a = tmp_path / "alpha"
    dir_b = tmp_path / "beta"
    dir_a.mkdir()
    dir_b.mkdir()

    topic_a = TopicExt(name="integ-topic-alpha", description="", watch_path=str(dir_a))
    topic_b = TopicExt(name="integ-topic-beta", description="", watch_path=str(dir_b))
    db_session.add_all([topic_a, topic_b])
    db_session.commit()
    db_session.refresh(topic_a)
    db_session.refresh(topic_b)

    (dir_a / "doc.md").write_text(
        "# Xylophone\nThe xylophone is a percussion instrument made of wooden bars."
    )
    (dir_b / "doc.md").write_text(
        "# Accordion\nThe accordion is a wind instrument with a bellows mechanism."
    )

    provider = ClaudeProvider()
    for topic, doc_path in [(topic_a, dir_a / "doc.md"), (topic_b, dir_b / "doc.md")]:
        ingest_file(
            db=db_session,
            topic=topic,
            file_path=str(doc_path),
            file_content=doc_path.read_text(),
            provider=provider,
        )

    pages_a = db_session.query(WikiPage).filter(WikiPage.topic_id == topic_a.id).all()
    pages_b = db_session.query(WikiPage).filter(WikiPage.topic_id == topic_b.id).all()

    assert len(pages_a) >= 1
    assert len(pages_b) >= 1

    content_a = " ".join(p.content for p in pages_a).lower()
    content_b = " ".join(p.content for p in pages_b).lower()

    assert "xylophone" in content_a
    assert "accordion" in content_b
    # Topic A pages must not contain topic B's exclusive concept and vice versa
    assert "accordion" not in content_a
    assert "xylophone" not in content_b


def test_cross_ref_idempotency(db_session, tmp_path):
    """Ingesting the same file twice must not duplicate cross-ref rows."""
    from knowledge_layer.db.models import TopicExt, WikiPage, CrossRef
    from knowledge_layer.background.ingest_worker import ingest_file
    from knowledge_layer.providers.claude import ClaudeProvider

    topic = TopicExt(name="integ-topic-alpha", description="", watch_path=str(tmp_path))
    db_session.add(topic)
    db_session.commit()
    db_session.refresh(topic)

    raw_file = tmp_path / "idem.md"
    raw_file.write_text(
        "# VWAP Strategy\n\n"
        "VWAP is used for execution timing. "
        "It relates to risk management and signal generation."
    )

    provider = ClaudeProvider()
    # Ingest twice — second run should detect SUCCESS + same hash and skip
    ingest_file(db=db_session, topic=topic, file_path=str(raw_file),
                file_content=raw_file.read_text(), provider=provider)
    ingest_file(db=db_session, topic=topic, file_path=str(raw_file),
                file_content=raw_file.read_text(), provider=provider)

    pages = db_session.query(WikiPage).filter(
        WikiPage.topic_id == topic.id,
        WikiPage.is_index_page.is_(False),
    ).all()
    page_ids = [p.id for p in pages]
    assert len(page_ids) >= 1, "ingest produced no non-index pages"

    cross_refs = db_session.query(CrossRef).filter(
            CrossRef.from_page_id.in_(page_ids)
        ).all()
    seen = set()
    for ref in cross_refs:
        key = (ref.from_page_id, ref.to_slug, ref.link_type)
        assert key not in seen, f"Duplicate cross-ref: {key}"
        seen.add(key)


def test_index_page_created_after_ingest(db_session, tmp_path):
    """After ingesting a doc, the topic's index page must exist and list the page."""
    from knowledge_layer.db.models import TopicExt, WikiPage
    from knowledge_layer.background.ingest_worker import ingest_file
    from knowledge_layer.providers.claude import ClaudeProvider

    topic = TopicExt(name="integ-topic-alpha", description="", watch_path=str(tmp_path))
    db_session.add(topic)
    db_session.commit()
    db_session.refresh(topic)

    (tmp_path / "note.md").write_text(
        "# Widgets\nThis is a test document about the widget manufacturing process."
    )
    provider = ClaudeProvider()
    ingest_file(
        db=db_session,
        topic=topic,
        file_path=str(tmp_path / "note.md"),
        file_content=(tmp_path / "note.md").read_text(),
        provider=provider,
    )

    index_page = db_session.query(WikiPage).filter(
        WikiPage.topic_id == topic.id,
        WikiPage.is_index_page.is_(True),
        WikiPage.slug == "index",
    ).first()

    assert index_page is not None
    assert topic.name in index_page.content
