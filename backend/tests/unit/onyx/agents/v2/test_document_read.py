from types import SimpleNamespace

from onyx.agents.v2 import document_read as module


def test_unknown_citation_never_touches_index():
    result = module.read_cited_document(
        index=object(),
        user=object(),
        filters=None,
        known_citations={},
        read_citation=12,
        start_chunk=0,
        citation=20,
    )
    assert result.status == "error"


def test_read_refreshes_acl_and_bounds_page(monkeypatch):
    acl = object()
    calls = []
    monkeypatch.setattr(module, "document_read_filters", lambda _user, _filters: acl)
    chunk = SimpleNamespace(
        chunk_id=6,
        semantic_identifier="doc",
        content="later threshold table",
        source_type=SimpleNamespace(value="file"),
    )

    class Index:
        def id_based_retrieval(self, **kwargs):
            calls.append(kwargs)
            return [chunk]

    result = module.read_cited_document(
        index=Index(),
        user=object(),
        filters=None,
        known_citations={12: "doc"},
        read_citation=12,
        start_chunk=6,
        citation=20,
    )
    assert calls[0]["filters"] is acl
    request = calls[0]["chunk_requests"][0]
    assert (
        request.document_id == "doc"
        and request.min_chunk_ind == 6
        and request.max_chunk_ind == 11
    )
    assert result.citation_mapping == {20: "doc"}
    assert result.receipt["next_chunk"] is None
    assert "later threshold table" in result.content
