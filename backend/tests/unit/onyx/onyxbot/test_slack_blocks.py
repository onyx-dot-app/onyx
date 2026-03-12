from datetime import datetime

import pytest
import pytz
import timeago  # type: ignore

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SavedSearchDoc
from onyx.onyxbot.slack.blocks import _build_documents_blocks
from onyx.onyxbot.slack.blocks import _extract_code_snippets
from onyx.onyxbot.slack.blocks import _split_text
from onyx.onyxbot.slack.handlers.handle_regular_answer import _SNIPPET_TYPE_MAP


def _make_saved_doc(updated_at: datetime | None) -> SavedSearchDoc:
    return SavedSearchDoc(
        db_doc_id=1,
        document_id="doc-1",
        chunk_ind=0,
        semantic_identifier="Example Doc",
        link="https://example.com",
        blurb="Some blurb",
        source_type=DocumentSource.FILE,
        boost=0,
        hidden=False,
        metadata={},
        score=0.0,
        match_highlights=[],
        updated_at=updated_at,
        primary_owners=["user@example.com"],
        secondary_owners=None,
        is_relevant=None,
        relevance_explanation=None,
        is_internet=False,
    )


def test_build_documents_blocks_formats_naive_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    naive_timestamp: datetime = datetime(2024, 1, 1, 12, 0, 0)
    captured: dict[str, datetime] = {}

    # Save the original timeago.format so we can call it inside the fake
    original_timeago_format = timeago.format

    def fake_timeago_format(doc_dt: datetime, now: datetime) -> str:
        captured["doc"] = doc_dt
        result = original_timeago_format(doc_dt, now)
        captured["result"] = result
        return result

    monkeypatch.setattr(
        "onyx.onyxbot.slack.blocks.timeago.format",
        fake_timeago_format,
    )

    blocks = _build_documents_blocks(
        documents=[_make_saved_doc(updated_at=naive_timestamp)],
        message_id=42,
    )

    assert len(blocks) >= 2
    section_block = blocks[1].to_dict()
    assert "result" in captured
    expected_text = (
        "<https://example.com|Example Doc>\n_Updated " f"{captured['result']}_\n>"
    )
    assert section_block["text"]["text"] == expected_text

    assert "doc" in captured
    formatted_timestamp: datetime = captured["doc"]
    expected_timestamp: datetime = naive_timestamp.replace(tzinfo=pytz.utc)
    assert formatted_timestamp == expected_timestamp


# ---------------------------------------------------------------------------
# _split_text tests
# ---------------------------------------------------------------------------


class TestSplitText:
    def test_short_text_returns_single_chunk(self) -> None:
        result = _split_text("hello world", limit=100)
        assert result == ["hello world"]

    def test_splits_at_space_boundary(self) -> None:
        text = "aaa bbb ccc ddd"
        result = _split_text(text, limit=8)
        assert len(result) >= 2

    def test_no_code_fences_splits_normally(self) -> None:
        text = "word " * 100  # 500 chars
        result = _split_text(text, limit=100)
        assert len(result) >= 5
        for chunk in result:
            assert "```" not in chunk


# ---------------------------------------------------------------------------
# _extract_code_snippets tests
# ---------------------------------------------------------------------------


class TestExtractCodeSnippets:
    def test_short_text_no_extraction(self) -> None:
        text = "short answer with ```python\nprint('hi')\n``` inline"
        cleaned, snippets = _extract_code_snippets(text, limit=3000)
        assert cleaned == text
        assert snippets == []

    def test_large_code_block_extracted(self) -> None:
        code = "x = 1\n" * 200  # ~1200 chars of code
        text = f"Here is the solution:\n```python\n{code}```\nHope that helps!"
        cleaned, snippets = _extract_code_snippets(text, limit=200)

        assert len(snippets) == 1
        assert snippets[0].language == "python"
        assert snippets[0].filename == "code_1.python"
        assert "x = 1" in snippets[0].code
        # Code block should be removed from cleaned text
        assert "```" not in cleaned
        assert "Here is the solution" in cleaned
        assert "Hope that helps!" in cleaned

    def test_multiple_code_blocks_only_large_ones_extracted(self) -> None:
        small_code = "print('hi')"
        large_code = "x = 1\n" * 300
        text = (
            f"First:\n```python\n{small_code}\n```\n"
            f"Second:\n```javascript\n{large_code}\n```\n"
            "Done!"
        )
        cleaned, snippets = _extract_code_snippets(text, limit=500)

        # The large block should be extracted
        assert len(snippets) >= 1
        langs = [s.language for s in snippets]
        assert "javascript" in langs

    def test_language_specifier_captured(self) -> None:
        code = "fn main() {}\n" * 100
        text = f"```rust\n{code}```"
        _, snippets = _extract_code_snippets(text, limit=100)

        assert len(snippets) == 1
        assert snippets[0].language == "rust"
        assert snippets[0].filename == "code_1.rust"

    def test_no_language_defaults_to_text(self) -> None:
        code = "some output\n" * 100
        text = f"```\n{code}```"
        _, snippets = _extract_code_snippets(text, limit=100)

        assert len(snippets) == 1
        assert snippets[0].language == "text"
        assert snippets[0].filename == "code_1.txt"

    def test_cleaned_text_has_no_triple_blank_lines(self) -> None:
        code = "x = 1\n" * 200
        text = f"Before\n\n```python\n{code}```\n\nAfter"
        cleaned, _ = _extract_code_snippets(text, limit=100)

        assert "\n\n\n" not in cleaned

    def test_multiple_blocks_cumulative_removal(self) -> None:
        """When multiple code blocks exist, extraction decisions should
        account for previously extracted blocks (two-pass logic).
        Blocks must be smaller than limit//2 so the 'very large block'
        override doesn't trigger — we're testing the cumulative logic only."""
        # Each fenced block is ~103 chars (```python\n + 15*6 + ```)
        block_a = "a = 1\n" * 15  # 90 chars of code
        block_b = "b = 2\n" * 15  # 90 chars of code
        prose = "x" * 200
        # Total: ~200 + 103 + 103 + overhead ≈ 420 chars
        # limit=300, limit//2=150. Each block (~103) < 150, so only
        # the cumulative check applies. Removing block_a (~103 chars)
        # brings us to ~317 > 300, so block_b should also be extracted.
        # But with limit=350: removing block_a → ~317 ≤ 350, stop.
        text = f"{prose}\n```python\n{block_a}```\n```python\n{block_b}```\nEnd"
        cleaned, snippets = _extract_code_snippets(text, limit=350)

        # After extracting block_a the text is ≤ 350, so block_b stays.
        assert len(snippets) == 1
        assert snippets[0].filename == "code_1.python"
        # block_b should still be in the cleaned text
        assert "b = 2" in cleaned


# ---------------------------------------------------------------------------
# _SNIPPET_TYPE_MAP tests
# ---------------------------------------------------------------------------


class TestSnippetTypeMap:
    @pytest.mark.parametrize(
        "alias,expected",
        [
            ("py", "python"),
            ("js", "javascript"),
            ("ts", "typescript"),
            ("tsx", "typescript"),
            ("jsx", "javascript"),
            ("sh", "shell"),
            ("bash", "shell"),
            ("yml", "yaml"),
            ("rb", "ruby"),
            ("rs", "rust"),
            ("cs", "csharp"),
            ("md", "markdown"),
            ("text", "plain_text"),
        ],
    )
    def test_common_aliases_normalized(self, alias: str, expected: str) -> None:
        assert _SNIPPET_TYPE_MAP[alias] == expected

    def test_unknown_language_passes_through(self) -> None:
        unknown = "haskell"
        assert _SNIPPET_TYPE_MAP.get(unknown, unknown) == "haskell"
