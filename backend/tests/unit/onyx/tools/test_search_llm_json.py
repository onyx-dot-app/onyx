"""Unit tests for the search-result → LLM surface.

Two concerns, one test file — they're the same pipeline end-to-end:

  1. `sandbox_filename_for_document_title` turns a Document title into the
     sandbox-safe filename used both in the LLM JSON and in the actual
     `ChatFile` staged to the Python sandbox. It's load-bearing that both
     paths produce identical names, so we pin the helper here.

  2. `convert_inference_sections_to_llm_string` wraps file-bearing hits
     with `CODE_INTERPRETER_GUIDANCE` and emits `code_interpreter_file` =
     the same sanitized filename, so the LLM knows which filename to
     reference in Python code.
"""

import json

import pytest

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.context.search.utils import sandbox_filename_for_document_title
from onyx.tools.tool_implementations.utils import CODE_INTERPRETER_GUIDANCE
from onyx.tools.tool_implementations.utils import (
    convert_inference_sections_to_llm_string,
)


# =============================================================================
# sandbox_filename_for_document_title
# =============================================================================


class TestSafeTitlePassthrough:
    def test_plain_name_with_extension_is_preserved(self) -> None:
        assert sandbox_filename_for_document_title("Q3 Sales.pdf") == "Q3 Sales.pdf"

    def test_extensionless_title_is_preserved_as_is(self) -> None:
        """No extension gets synthesized — the helper only sanitizes."""
        assert sandbox_filename_for_document_title("Quarterly Plan") == "Quarterly Plan"

    def test_spaces_and_underscores_are_preserved(self) -> None:
        assert (
            sandbox_filename_for_document_title("my_report v2.csv")
            == "my_report v2.csv"
        )


class TestUnsafeCharacterReplacement:
    def test_forward_slash_becomes_underscore(self) -> None:
        assert sandbox_filename_for_document_title("Q1/Q2 Report") == "Q1_Q2 Report"

    def test_backslash_becomes_underscore(self) -> None:
        assert sandbox_filename_for_document_title("path\\to\\file") == "path_to_file"

    def test_colon_becomes_underscore(self) -> None:
        assert sandbox_filename_for_document_title("Re: meeting") == "Re_ meeting"

    def test_wildcards_and_pipes_replaced(self) -> None:
        assert sandbox_filename_for_document_title("file*?|<>") == "file_"

    def test_quotes_and_angle_brackets_replaced(self) -> None:
        assert (
            sandbox_filename_for_document_title('"quoted" <html>') == "_quoted_ _html_"
        )

    def test_null_byte_replaced(self) -> None:
        assert sandbox_filename_for_document_title("ok\x00bad") == "ok_bad"

    def test_control_chars_replaced(self) -> None:
        assert sandbox_filename_for_document_title("line\x01\x02\x1fok") == "line_ok"

    def test_consecutive_unsafe_chars_collapse_to_single_underscore(self) -> None:
        """The regex uses `+`, so runs of unsafe chars produce exactly one `_`."""
        assert sandbox_filename_for_document_title("a///b\\\\c") == "a_b_c"

    def test_path_traversal_is_neutralized(self) -> None:
        """`../` attacks lose the slash, so the result is just a filename."""
        result = sandbox_filename_for_document_title("../etc/passwd")
        assert "/" not in result
        assert result == "_etc_passwd"


class TestTrimmingAndFallbacks:
    def test_leading_and_trailing_whitespace_stripped(self) -> None:
        assert sandbox_filename_for_document_title("   report.csv   ") == "report.csv"

    def test_leading_and_trailing_dots_stripped(self) -> None:
        assert sandbox_filename_for_document_title("...hidden...") == "hidden"

    def test_empty_input_returns_document_fallback(self) -> None:
        assert sandbox_filename_for_document_title("") == "document"

    def test_spaces_only_returns_document_fallback(self) -> None:
        """Plain spaces aren't matched by the unsafe-char regex, so the
        subsequent `.strip()` empties the string → fallback."""
        assert sandbox_filename_for_document_title("     ") == "document"

    def test_only_unsafe_chars_does_not_fall_back_to_document(self) -> None:
        """Unsafe chars get replaced with underscores BEFORE the empty-check,
        so a title that's all unsafe chars becomes `_`, not `document`.
        Same story for whitespace mixed with control chars (tabs are
        `\\x09` and get replaced, not stripped). Pinned here because the
        interaction is subtle."""
        assert sandbox_filename_for_document_title("////") == "_"
        assert sandbox_filename_for_document_title("   \t  ") == "_"

    def test_only_dots_returns_document_fallback(self) -> None:
        """Leading/trailing dot stripping eats the whole string, which
        triggers the empty-name fallback."""
        assert sandbox_filename_for_document_title("....") == "document"


class TestLengthCap:
    def test_long_name_truncated_to_max_length(self) -> None:
        long_title = "x" * 500
        result = sandbox_filename_for_document_title(long_title)
        assert len(result) == 200
        assert result == "x" * 200

    def test_just_under_cap_is_unchanged(self) -> None:
        title = "y" * 200
        assert sandbox_filename_for_document_title(title) == title

    def test_truncation_ignores_extension(self) -> None:
        """The cap is a raw char count — extensions aren't protected, so a
        very long title followed by `.pdf` still gets chopped. Deliberate
        tradeoff (simplicity over preserving extensions on pathological
        inputs)."""
        result = sandbox_filename_for_document_title("x" * 300 + ".pdf")
        assert len(result) == 200
        assert not result.endswith(".pdf")


# =============================================================================
# convert_inference_sections_to_llm_string
# =============================================================================


def _make_chunk(
    document_id: str,
    semantic_identifier: str | None = None,
    chunk_id: int = 0,
    file_id: str | None = None,
    content: str | None = None,
) -> InferenceChunk:
    return InferenceChunk(
        document_id=document_id,
        chunk_id=chunk_id,
        content=content if content is not None else f"content-{document_id}",
        source_type=DocumentSource.MOCK_CONNECTOR,
        semantic_identifier=semantic_identifier or f"sem-{document_id}",
        title=document_id,
        boost=1,
        score=0.5,
        hidden=False,
        metadata={},
        match_highlights=[],
        doc_summary="",
        chunk_context="",
        updated_at=None,
        image_file_id=None,
        source_links={},
        section_continuation=False,
        blurb=f"blurb-{document_id}",
        file_id=file_id,
    )


def _make_section(
    chunk: InferenceChunk,
    combined_content: str | None = None,
) -> InferenceSection:
    return InferenceSection(
        center_chunk=chunk,
        chunks=[chunk],
        combined_content=(
            combined_content if combined_content is not None else chunk.content
        ),
    )


class TestCodeInterpreterFilenameInLLMJson:
    def test_filename_derived_from_title_when_file_id_present(self) -> None:
        chunk = _make_chunk(
            "doc-a",
            semantic_identifier="Q3 Sales Report.pdf",
            file_id="file-abc123",
        )
        section = _make_section(chunk)

        llm_string, _ = convert_inference_sections_to_llm_string([section])
        payload = json.loads(llm_string)

        # Sandbox filename = sanitized title; same helper the staging
        # pipeline uses, so the LLM-visible name matches the filesystem.
        assert payload["results"][0]["code_interpreter_file"] == "Q3 Sales Report.pdf"
        # Internal-only — must not leak into the LLM JSON.
        assert "file_id" not in payload["results"][0]

    def test_omitted_when_no_file_id(self) -> None:
        chunk = _make_chunk("doc-b", file_id=None)
        section = _make_section(chunk)

        llm_string, _ = convert_inference_sections_to_llm_string([section])
        payload = json.loads(llm_string)

        assert "code_interpreter_file" not in payload["results"][0]

    def test_title_with_unsafe_chars_is_sanitized(self) -> None:
        chunk = _make_chunk(
            "doc-c",
            semantic_identifier="Report: Q1/Q2 Analysis",
            file_id="file-xyz",
        )
        section = _make_section(chunk)

        llm_string, _ = convert_inference_sections_to_llm_string([section])
        payload = json.loads(llm_string)

        assert payload["results"][0]["code_interpreter_file"] == (
            "Report_ Q1_Q2 Analysis"
        )

    def test_filename_matches_shared_helper(self) -> None:
        """The serializer must route through the same helper the staging
        pipeline uses — otherwise the LLM-visible name and the actual
        sandbox filename can drift apart."""
        title = "Weird/Name*With:Stuff"
        chunk = _make_chunk("doc-d", semantic_identifier=title, file_id="file-match")
        section = _make_section(chunk)

        llm_string, _ = convert_inference_sections_to_llm_string([section])
        payload = json.loads(llm_string)

        assert payload["results"][0][
            "code_interpreter_file"
        ] == sandbox_filename_for_document_title(title)

    def test_citation_mapping_unchanged_by_file_presence(self) -> None:
        """Adding code-interpreter guidance is purely additive — citation
        numbering still keys off document_id."""
        chunk = _make_chunk(
            "doc-e",
            semantic_identifier="Anything.csv",
            file_id="file-citation",
        )
        section = _make_section(chunk)

        _, citation_mapping = convert_inference_sections_to_llm_string(
            [section], citation_start=42
        )

        assert citation_mapping == {42: "doc-e"}


class TestContentFieldWrappingForFileBearingHits:
    """The `content` value differs for file-bearing hits vs. ordinary hits."""

    def test_file_hit_wraps_content_with_guidance(self) -> None:
        chunk = _make_chunk(
            "doc-f",
            semantic_identifier="data.csv",
            file_id="file-wrap",
            content="just the center chunk",
        )
        section = _make_section(
            chunk, combined_content="center chunk\nPLUS adjacent\nAND MORE"
        )

        llm_string, _ = convert_inference_sections_to_llm_string([section])
        payload = json.loads(llm_string)
        content = payload["results"][0]["content"]

        # Content is the guidance template wrapped around the center chunk.
        # Expanded section content is NOT included (code interpreter is
        # the better path for the full file).
        expected = CODE_INTERPRETER_GUIDANCE.format(
            filename="data.csv", content="just the center chunk"
        )
        assert content == expected
        # Concrete properties we care about for LLM steering:
        assert "data.csv" in content
        assert "just the center chunk" in content
        assert "code interpreter" in content.lower()
        assert "PLUS adjacent" not in content  # combined_content suppressed

    def test_non_file_hit_uses_combined_content_unchanged(self) -> None:
        chunk = _make_chunk(
            "doc-g",
            content="only this chunk",
            file_id=None,
        )
        section = _make_section(
            chunk, combined_content="full combined section text here"
        )

        llm_string, _ = convert_inference_sections_to_llm_string([section])
        payload = json.loads(llm_string)

        assert payload["results"][0]["content"] == "full combined section text here"

    def test_guidance_mentions_filename_and_interpreter(self) -> None:
        """Load-bearing phrasing: the LLM should be able to read the
        content field and know (1) this is an excerpt, (2) what the real
        filename is, (3) which tool gets it the full file."""
        chunk = _make_chunk(
            "doc-h",
            semantic_identifier="report.pdf",
            file_id="file-phrasing",
            content="excerpt body",
        )
        section = _make_section(chunk)

        llm_string, _ = convert_inference_sections_to_llm_string([section])
        payload = json.loads(llm_string)
        content = payload["results"][0]["content"]

        assert "excerpt" in content.lower()
        assert "report.pdf" in content
        # Whichever exact wording CODE_INTERPRETER_GUIDANCE uses, the
        # Python code interpreter recommendation must be there.
        assert "python code interpreter" in content.lower()

    def test_mixed_batch_only_file_hits_get_guidance(self) -> None:
        file_chunk = _make_chunk(
            "doc-i",
            semantic_identifier="sheet.xlsx",
            file_id="file-mixed",
            content="body",
        )
        plain_chunk = _make_chunk("doc-j", content="plain", file_id=None)
        sections = [
            _make_section(file_chunk, combined_content="file combined"),
            _make_section(plain_chunk, combined_content="plain combined"),
        ]

        llm_string, _ = convert_inference_sections_to_llm_string(sections)
        results = json.loads(llm_string)["results"]

        assert "sheet.xlsx" in results[0]["content"]
        assert "code interpreter" in results[0]["content"].lower()
        # Plain hit carries its combined_content as-is, no guidance text.
        assert results[1]["content"] == "plain combined"
        assert "code_interpreter_file" not in results[1]


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
