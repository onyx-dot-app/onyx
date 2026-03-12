from datetime import datetime

import pytest
import pytz
import timeago  # type: ignore

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SavedSearchDoc
from onyx.onyxbot.slack.blocks import _build_documents_blocks
from onyx.onyxbot.slack.blocks import _find_unclosed_fence
from onyx.onyxbot.slack.blocks import _split_text


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

    def test_code_block_not_split_when_fits(self) -> None:
        text = "before ```code here``` after"
        result = _split_text(text, limit=100)
        assert result == [text]

    def test_code_block_split_backs_up_before_fence(self) -> None:
        # Build text where the split point falls inside a code block,
        # but the code block itself fits within the limit. The split
        # should back up to before the opening ``` so the block stays intact.
        before = "some intro text here " * 5 + "\n"  # ~105 chars
        code_content = "x " * 20  # ~40 chars of code
        text = f"{before}```\n{code_content}\n```\nafter"
        # limit=120 means the initial split lands inside the code block
        # but the code block (~50 chars) fits in the next chunk
        result = _split_text(text, limit=120)

        assert len(result) >= 2
        # Every chunk must have balanced code fences (0 or 2)
        for chunk in result:
            fence_count = chunk.count("```")
            assert (
                fence_count % 2 == 0
            ), f"Unbalanced code fences in chunk: {chunk[:80]}..."
        # The code block should be fully contained in one chunk
        code_chunks = [c for c in result if "```" in c]
        assert len(code_chunks) == 1, "Code block should not be split across chunks"

    def test_no_code_fences_splits_normally(self) -> None:
        text = "word " * 100  # 500 chars
        result = _split_text(text, limit=100)
        assert len(result) >= 5
        for chunk in result:
            fence_count = chunk.count("```")
            assert fence_count == 0

    def test_code_block_exceeding_limit_falls_back_to_close_reopen(self) -> None:
        # When the code block itself is bigger than the limit, we can't
        # avoid splitting inside it — verify fences are still balanced.
        code_content = "x " * 100  # ~200 chars
        text = f"```\n{code_content}\n```"
        result = _split_text(text, limit=80)

        assert len(result) >= 2
        for chunk in result:
            fence_count = chunk.count("```")
            assert (
                fence_count % 2 == 0
            ), f"Unbalanced code fences in chunk: {chunk[:80]}..."

    def test_all_content_preserved_after_split(self) -> None:
        text = "intro paragraph and more text here\n```\nprint('hello')\n```\nconclusion here"
        result = _split_text(text, limit=50)

        # Key content should appear somewhere across the chunks
        joined = " ".join(result)
        assert "intro" in joined
        assert "print('hello')" in joined
        assert "conclusion" in joined

    def test_language_specifier_preserved_on_reopen(self) -> None:
        # When a ```python block exceeds the limit and must be split,
        # the continuation chunk should reopen with ```python, not ```.
        code_content = "x " * 100  # ~200 chars
        text = f"```python\n{code_content}\n```"
        result = _split_text(text, limit=80)

        assert len(result) >= 2
        for chunk in result[1:]:
            stripped = chunk.lstrip()
            if stripped.startswith("```"):
                assert stripped.startswith(
                    "```python"
                ), f"Language specifier lost in continuation: {chunk[:40]}"

    def test_inline_backticks_inside_code_block_ignored(self) -> None:
        # Triple backticks appearing mid-line inside a code block should
        # not be mistaken for fence boundaries.
        before = "some text here " * 6 + "\n"  # ~90 chars
        text = f"{before}```bash\necho '```'\necho done\n```\nafter"
        result = _split_text(text, limit=110)

        assert len(result) >= 2
        for chunk in result:
            is_open, _, _ = _find_unclosed_fence(chunk)
            assert not is_open, f"Chunk has unclosed fence: {chunk[:80]}..."


# ---------------------------------------------------------------------------
# _find_unclosed_fence tests
# ---------------------------------------------------------------------------


class TestFindUnclosedFence:
    def test_no_fences(self) -> None:
        is_open, _, _ = _find_unclosed_fence("just plain text")
        assert not is_open

    def test_balanced_fences(self) -> None:
        is_open, _, _ = _find_unclosed_fence("```\ncode\n```")
        assert not is_open

    def test_unclosed_fence(self) -> None:
        is_open, start, lang = _find_unclosed_fence("before\n```\ncode here")
        assert is_open
        assert start == len("before\n")
        assert lang == ""

    def test_unclosed_fence_with_lang(self) -> None:
        is_open, _, lang = _find_unclosed_fence("intro\n```python\ncode")
        assert is_open
        assert lang == "python"

    def test_inline_backticks_not_counted(self) -> None:
        # Backticks mid-line should not toggle fence state
        text = "```bash\necho '```'\necho done\n```"
        is_open, _, _ = _find_unclosed_fence(text)
        assert not is_open
