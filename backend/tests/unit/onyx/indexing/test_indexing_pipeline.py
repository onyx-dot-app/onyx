import random
import threading
import time
from typing import Any
from typing import cast
from typing import List
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from onyx.connectors.models import Document
from onyx.connectors.models import DocumentSource
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.hooks.executor import HookSkipped
from onyx.hooks.executor import HookSoftFailed
from onyx.hooks.points.document_ingestion import DocumentIngestionResponse
from onyx.hooks.points.document_ingestion import DocumentIngestionSection
from onyx.indexing.chunker import Chunker
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.indexing_pipeline import _apply_document_ingestion_hook
from onyx.indexing.indexing_pipeline import add_contextual_summaries
from onyx.indexing.indexing_pipeline import filter_documents
from onyx.indexing.indexing_pipeline import process_image_sections
from onyx.llm.constants import LlmProviderNames
from onyx.llm.model_response import Choice
from onyx.llm.model_response import Message
from onyx.llm.model_response import ModelResponse
from onyx.llm.utils import get_max_input_tokens


def create_test_document(
    doc_id: str = "test_id",
    title: str | None = "Test Title",
    semantic_id: str = "test_semantic_id",
    sections: List[TextSection] | None = None,
) -> Document:
    if sections is None:
        sections = [TextSection(text="Test content", link="test_link")]
    return Document(
        id=doc_id,
        title=title,
        semantic_identifier=semantic_id,
        sections=cast(list[TextSection | ImageSection], sections),
        source=DocumentSource.FILE,
        metadata={},
    )


def test_filter_documents_empty_title_and_content() -> None:
    doc = create_test_document(
        title="", semantic_id="", sections=[TextSection(text="", link="test_link")]
    )
    docs, failures = filter_documents([doc])
    assert len(docs) == 0
    assert len(failures) == 0


def test_filter_documents_empty_title_with_content() -> None:
    doc = create_test_document(
        title="", sections=[TextSection(text="Valid content", link="test_link")]
    )
    docs, failures = filter_documents([doc])
    assert len(docs) == 1
    assert docs[0].id == "test_id"
    assert len(failures) == 0


def test_filter_documents_empty_content_with_title() -> None:
    doc = create_test_document(
        title="Valid Title", sections=[TextSection(text="", link="test_link")]
    )
    docs, failures = filter_documents([doc])
    assert len(docs) == 1
    assert docs[0].id == "test_id"
    assert len(failures) == 0


def test_filter_documents_exceeding_max_chars() -> None:
    limit = 100
    long_text = "a" * (limit + 1)
    doc = create_test_document(sections=[TextSection(text=long_text, link="test_link")])
    with patch("onyx.indexing.indexing_pipeline.MAX_DOCUMENT_CHARS", limit):
        docs, failures = filter_documents([doc])
    assert len(docs) == 0
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == "test_id"
    assert "too large to index" in failures[0].failure_message
    assert "MAX_DOCUMENT_CHARS" in failures[0].failure_message


def test_filter_documents_valid_document() -> None:
    doc = create_test_document(
        title="Valid Title",
        sections=[TextSection(text="Valid content", link="test_link")],
    )
    docs, failures = filter_documents([doc])
    assert len(docs) == 1
    assert docs[0].id == "test_id"
    assert docs[0].title == "Valid Title"
    assert len(failures) == 0


def test_filter_documents_whitespace_only() -> None:
    doc = create_test_document(
        title="   ",
        semantic_id="  ",
        sections=[TextSection(text="   ", link="test_link")],
    )
    docs, failures = filter_documents([doc])
    assert len(docs) == 0
    assert len(failures) == 0


def test_filter_documents_semantic_id_no_title() -> None:
    doc = create_test_document(
        title=None,
        semantic_id="Valid Semantic ID",
        sections=[TextSection(text="Valid content", link="test_link")],
    )
    docs, failures = filter_documents([doc])
    assert len(docs) == 1
    assert docs[0].semantic_identifier == "Valid Semantic ID"
    assert len(failures) == 0


def test_filter_documents_multiple_sections() -> None:
    doc = create_test_document(
        sections=[
            TextSection(text="Content 1", link="test_link"),
            TextSection(text="Content 2", link="test_link"),
            TextSection(text="Content 3", link="test_link"),
        ]
    )
    docs, failures = filter_documents([doc])
    assert len(docs) == 1
    assert len(docs[0].sections) == 3
    assert len(failures) == 0


def test_filter_documents_multiple_documents() -> None:
    docs_input = [
        create_test_document(doc_id="1", title="Title 1"),
        create_test_document(
            doc_id="2", title="", sections=[TextSection(text="", link="test_link")]
        ),  # Should be filtered (empty, no failure)
        create_test_document(doc_id="3", title="Title 3"),
    ]
    docs, failures = filter_documents(docs_input)
    assert len(docs) == 2
    assert {doc.id for doc in docs} == {"1", "3"}
    assert len(failures) == 0


def test_filter_documents_empty_batch() -> None:
    docs, failures = filter_documents([])
    assert len(docs) == 0
    assert len(failures) == 0


@patch("onyx.llm.utils.GEN_AI_MAX_TOKENS", 4096)
@pytest.mark.parametrize("enable_contextual_rag", [True, False])
def test_contextual_rag(
    embedder: DefaultIndexingEmbedder, enable_contextual_rag: bool
) -> None:
    short_section_1 = "This is a short section."
    long_section = (
        "This is a long section that should be split into multiple chunks. " * 100
    )
    short_section_2 = "This is another short section."
    short_section_3 = "This is another short section again."
    short_section_4 = "Final short section."
    semantic_identifier = "Test Document"

    document = Document(
        id="test_doc",
        source=DocumentSource.WEB,
        semantic_identifier=semantic_identifier,
        metadata={"tags": ["tag1", "tag2"]},
        doc_updated_at=None,
        sections=[
            TextSection(text=short_section_1, link="link1"),
            TextSection(text=short_section_2, link="link2"),
            TextSection(text=long_section, link="link3"),
            TextSection(text=short_section_3, link="link4"),
            TextSection(text=short_section_4, link="link5"),
        ],
    )
    indexing_documents = process_image_sections([document])

    mock_llm_invoke_count = 0
    counter_lock = threading.Lock()

    def mock_llm_invoke(
        *args: Any, **kwargs: Any  # noqa: ARG001
    ) -> ModelResponse:  # noqa: ARG001
        nonlocal mock_llm_invoke_count
        with counter_lock:
            mock_llm_invoke_count += 1
        return ModelResponse(
            id=f"test-{mock_llm_invoke_count}",
            created="2024-01-01T00:00:00Z",
            choice=Choice(message=Message(content=f"Test{mock_llm_invoke_count}")),
        )

    llm_tokenizer = embedder.embedding_model.tokenizer

    mock_llm = Mock()
    mock_llm.config.max_input_tokens = get_max_input_tokens(
        model_provider=LlmProviderNames.OPENAI, model_name="gpt-4o"
    )
    mock_llm.invoke = mock_llm_invoke

    chunker = Chunker(
        tokenizer=embedder.embedding_model.tokenizer,
        enable_multipass=False,
        enable_contextual_rag=enable_contextual_rag,
    )
    chunks = chunker.chunk(indexing_documents)

    chunks = add_contextual_summaries(
        chunks=chunks,
        llm=mock_llm,
        tokenizer=llm_tokenizer,
        chunk_token_limit=chunker.chunk_token_limit * 2,
    )

    assert len(chunks) == 5
    assert short_section_1 in chunks[0].content
    assert short_section_3 in chunks[-1].content
    assert short_section_4 in chunks[-1].content
    assert "tag1" in chunks[0].metadata_suffix_keyword
    assert "tag2" in chunks[0].metadata_suffix_semantic

    doc_summary = "Test1" if enable_contextual_rag else ""
    chunk_context = ""
    count = 2
    for chunk in chunks:
        if enable_contextual_rag:
            chunk_context = f"Test{count}"
            count += 1
        assert chunk.doc_summary == doc_summary
        assert chunk.chunk_context == chunk_context


# ---------------------------------------------------------------------------
# _apply_document_ingestion_hook
# ---------------------------------------------------------------------------

_PATCH_EXECUTE_HOOK = "onyx.indexing.indexing_pipeline.execute_hook"


def _make_doc(
    doc_id: str = "doc1",
    sections: list[TextSection | ImageSection] | None = None,
) -> Document:
    if sections is None:
        sections = [TextSection(text="Hello", link="http://example.com")]
    return Document(
        id=doc_id,
        title="Test Doc",
        semantic_identifier="test-doc",
        sections=sections,
        source=DocumentSource.FILE,
        metadata={},
    )


def test_document_ingestion_hook_skipped_passes_through() -> None:
    doc = _make_doc()
    with patch(_PATCH_EXECUTE_HOOK, return_value=HookSkipped()):
        result = _apply_document_ingestion_hook([doc], MagicMock())
    assert result == [doc]


def test_document_ingestion_hook_soft_failed_passes_through() -> None:
    doc = _make_doc()
    with patch(_PATCH_EXECUTE_HOOK, return_value=HookSoftFailed()):
        result = _apply_document_ingestion_hook([doc], MagicMock())
    assert result == [doc]


def test_document_ingestion_hook_none_sections_drops_document() -> None:
    doc = _make_doc()
    with patch(
        _PATCH_EXECUTE_HOOK,
        return_value=DocumentIngestionResponse(
            sections=None, rejection_reason="PII detected"
        ),
    ):
        result = _apply_document_ingestion_hook([doc], MagicMock())
    assert result == []


def test_document_ingestion_hook_all_invalid_sections_drops_document() -> None:
    """A non-empty list where every section has neither text nor image_file_id drops the doc."""
    doc = _make_doc()
    with patch(
        _PATCH_EXECUTE_HOOK,
        return_value=DocumentIngestionResponse(sections=[DocumentIngestionSection()]),
    ):
        result = _apply_document_ingestion_hook([doc], MagicMock())
    assert result == []


def test_document_ingestion_hook_empty_sections_drops_document() -> None:
    doc = _make_doc()
    with patch(
        _PATCH_EXECUTE_HOOK,
        return_value=DocumentIngestionResponse(sections=[]),
    ):
        result = _apply_document_ingestion_hook([doc], MagicMock())
    assert result == []


def test_document_ingestion_hook_rewrites_text_sections() -> None:
    doc = _make_doc(sections=[TextSection(text="original", link="http://a.com")])
    with patch(
        _PATCH_EXECUTE_HOOK,
        return_value=DocumentIngestionResponse(
            sections=[DocumentIngestionSection(text="rewritten", link="http://b.com")]
        ),
    ):
        result = _apply_document_ingestion_hook([doc], MagicMock())
    assert len(result) == 1
    assert len(result[0].sections) == 1
    section = result[0].sections[0]
    assert isinstance(section, TextSection)
    assert section.text == "rewritten"
    assert section.link == "http://b.com"


def test_document_ingestion_hook_preserves_image_section_order() -> None:
    """Hook receives all sections including images and controls final ordering."""
    image = ImageSection(image_file_id="img-1", link=None)
    doc = _make_doc(
        sections=[TextSection(text="original", link=None), image],
    )
    # Hook moves the image before the text section
    with patch(
        _PATCH_EXECUTE_HOOK,
        return_value=DocumentIngestionResponse(
            sections=[
                DocumentIngestionSection(image_file_id="img-1", link=None),
                DocumentIngestionSection(text="rewritten", link=None),
            ]
        ),
    ):
        result = _apply_document_ingestion_hook([doc], MagicMock())
    assert len(result) == 1
    sections = result[0].sections
    assert len(sections) == 2
    assert (
        isinstance(sections[0], ImageSection) and sections[0].image_file_id == "img-1"
    )
    assert isinstance(sections[1], TextSection) and sections[1].text == "rewritten"


def test_document_ingestion_hook_mixed_batch() -> None:
    """Drop one doc, rewrite another, pass through a third."""
    doc_drop = _make_doc(doc_id="drop")
    doc_rewrite = _make_doc(doc_id="rewrite")
    doc_skip = _make_doc(doc_id="skip")

    def _side_effect(**kwargs: Any) -> Any:
        doc_id = kwargs["payload"]["document_id"]
        if doc_id == "drop":
            return DocumentIngestionResponse(sections=None)
        if doc_id == "rewrite":
            return DocumentIngestionResponse(
                sections=[DocumentIngestionSection(text="new text", link=None)]
            )
        return HookSkipped()

    with patch(_PATCH_EXECUTE_HOOK, side_effect=_side_effect):
        result = _apply_document_ingestion_hook(
            [doc_drop, doc_rewrite, doc_skip], MagicMock()
        )

    assert len(result) == 2
    ids = {d.id for d in result}
    assert ids == {"rewrite", "skip"}
    rewritten = next(d for d in result if d.id == "rewrite")
    assert isinstance(rewritten.sections[0], TextSection)
    assert rewritten.sections[0].text == "new text"


# ---------------------------------------------------------------------------
# process_image_sections
# ---------------------------------------------------------------------------

_PATCH_PREFIX = "onyx.indexing.indexing_pipeline"


def _mock_file_store(image_map: dict[str, bytes]) -> MagicMock:
    """Build a fake file store that serves images from a dict."""
    store = MagicMock()

    def _read_file_record(file_id: str) -> MagicMock | None:
        if file_id not in image_map:
            return None
        record = MagicMock()
        record.display_name = file_id
        return record

    def _read_file(file_id: str) -> MagicMock:
        data = MagicMock()
        data.read.return_value = image_map[file_id]
        return data

    store.read_file_record = _read_file_record
    store.read_file = _read_file
    return store


def _make_image_doc(
    doc_id: str,
    sections: list[TextSection | ImageSection],
) -> Document:
    return Document(
        id=doc_id,
        title=f"Doc {doc_id}",
        semantic_identifier=doc_id,
        sections=sections,
        source=DocumentSource.FILE,
        metadata={},
    )


class TestProcessImageSections:
    """Validate that parallel image summarization places results in the
    correct section positions — especially under concurrent execution."""

    def _run(
        self,
        documents: list[Document],
        image_map: dict[str, bytes],
        summarize_side_effect: Any = None,
    ) -> list[Any]:
        """Helper that patches all external deps and calls process_image_sections."""
        if summarize_side_effect is None:

            def summarize_side_effect(
                **kwargs: Any,
            ) -> str:
                return f"summary-of-{kwargs['context_name']}"

        with (
            patch(
                f"{_PATCH_PREFIX}.get_image_extraction_and_analysis_enabled",
                return_value=True,
            ),
            patch(
                f"{_PATCH_PREFIX}.get_default_llm_with_vision",
                return_value=MagicMock(),
            ),
            patch(
                f"{_PATCH_PREFIX}.get_default_file_store",
                return_value=_mock_file_store(image_map),
            ),
            patch(
                f"{_PATCH_PREFIX}.summarize_image_with_error_handling",
                side_effect=summarize_side_effect,
            ),
        ):
            return process_image_sections(documents)

    def test_interleaved_sections_preserve_order(self) -> None:
        """Text and image sections must stay in their original positions."""
        doc = _make_image_doc(
            "doc1",
            [
                TextSection(text="text-0", link="link-0"),
                ImageSection(image_file_id="img-A"),
                TextSection(text="text-2", link="link-2"),
                ImageSection(image_file_id="img-B"),
                TextSection(text="text-4", link="link-4"),
            ],
        )
        image_map = {"img-A": b"aa", "img-B": b"bb"}
        result = self._run([doc], image_map)

        sections = result[0].processed_sections
        assert len(sections) == 5
        assert sections[0].text == "text-0"
        assert sections[1].text == "summary-of-img-A"
        assert sections[1].image_file_id == "img-A"
        assert sections[2].text == "text-2"
        assert sections[3].text == "summary-of-img-B"
        assert sections[3].image_file_id == "img-B"
        assert sections[4].text == "text-4"

    def test_multiple_documents_preserve_order(self) -> None:
        """Each document's sections must be independent and correctly ordered."""
        doc1 = _make_image_doc(
            "doc1",
            [
                ImageSection(image_file_id="img-1"),
                TextSection(text="middle", link=None),
                ImageSection(image_file_id="img-2"),
            ],
        )
        doc2 = _make_image_doc(
            "doc2",
            [
                TextSection(text="start", link=None),
                ImageSection(image_file_id="img-3"),
            ],
        )
        image_map = {"img-1": b"a", "img-2": b"b", "img-3": b"c"}
        result = self._run([doc1, doc2], image_map)

        s1 = result[0].processed_sections
        assert len(s1) == 3
        assert s1[0].text == "summary-of-img-1"
        assert s1[1].text == "middle"
        assert s1[2].text == "summary-of-img-2"

        s2 = result[1].processed_sections
        assert len(s2) == 2
        assert s2[0].text == "start"
        assert s2[1].text == "summary-of-img-3"

    def test_ordering_under_varied_latency(self) -> None:
        """Simulate threads finishing in random order — results must still
        land in the correct section positions."""
        num_images = 10
        sections: list[TextSection | ImageSection] = []
        image_map: dict[str, bytes] = {}
        for i in range(num_images):
            fid = f"img-{i}"
            sections.append(TextSection(text=f"text-{i}", link=None))
            sections.append(ImageSection(image_file_id=fid))
            image_map[fid] = f"data-{i}".encode()

        doc = _make_image_doc("doc1", sections)

        def _slow_summarize(**kwargs: Any) -> str:
            time.sleep(random.uniform(0.001, 0.02))
            return f"summary-of-{kwargs['context_name']}"

        result = self._run([doc], image_map, summarize_side_effect=_slow_summarize)

        ps = result[0].processed_sections
        assert len(ps) == num_images * 2
        for i in range(num_images):
            assert ps[i * 2].text == f"text-{i}"
            assert ps[i * 2 + 1].text == f"summary-of-img-{i}"
            assert ps[i * 2 + 1].image_file_id == f"img-{i}"

    def test_text_only_document_unchanged(self) -> None:
        doc = _make_image_doc(
            "doc1",
            [
                TextSection(text="hello", link="a"),
                TextSection(text="world", link="b"),
            ],
        )
        result = self._run([doc], {})

        sections = result[0].processed_sections
        assert len(sections) == 2
        assert sections[0].text == "hello"
        assert sections[1].text == "world"

    def test_missing_file_record_does_not_corrupt_order(self) -> None:
        """An image whose file record is missing should get a placeholder
        without shifting other sections."""
        doc = _make_image_doc(
            "doc1",
            [
                ImageSection(image_file_id="exists"),
                ImageSection(image_file_id="missing"),
                TextSection(text="after", link=None),
            ],
        )
        image_map = {"exists": b"data"}
        result = self._run([doc], image_map)

        sections = result[0].processed_sections
        assert len(sections) == 3
        assert sections[0].text == "summary-of-exists"
        assert sections[1].text == "[Image could not be processed]"
        assert sections[2].text == "after"

    def test_summarization_failure_does_not_corrupt_order(self) -> None:
        """If one summarization fails, other sections must be unaffected."""
        doc = _make_image_doc(
            "doc1",
            [
                ImageSection(image_file_id="ok"),
                ImageSection(image_file_id="fail"),
                ImageSection(image_file_id="ok2"),
            ],
        )
        image_map = {"ok": b"a", "fail": b"b", "ok2": b"c"}

        def _sometimes_fail(**kwargs: Any) -> str | None:
            if kwargs["context_name"] == "fail":
                raise ValueError("boom")
            return f"summary-of-{kwargs['context_name']}"

        result = self._run([doc], image_map, summarize_side_effect=_sometimes_fail)

        sections = result[0].processed_sections
        assert len(sections) == 3
        assert sections[0].text == "summary-of-ok"
        # allow_failures=True → None result → fallback text
        assert sections[1].text == "[Error processing image]"
        assert sections[2].text == "summary-of-ok2"
