"""Unit tests for the search-result → LLM surface."""

import json

import pytest

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.context.search.utils import sandbox_filename_for_document
from onyx.tools.tool_implementations.utils import (
    convert_inference_sections_to_llm_string,
)
from onyx.tools.tool_implementations.utils import FILE_ASSOCIATED_GUIDANCE

FID = "550e8400-e29b-41d4-a716-446655440000"


class TestSafeTitlePassthrough:
    def test_plain_name_with_extension(self) -> None:
        assert (
            sandbox_filename_for_document("Q3 Sales.pdf", FID) == f"Q3 Sales_{FID}.pdf"
        )

    def test_extensionless_title(self) -> None:
        assert (
            sandbox_filename_for_document("Quarterly Plan", FID)
            == f"Quarterly Plan_{FID}"
        )

    def test_spaces_and_underscores_preserved(self) -> None:
        assert (
            sandbox_filename_for_document("my_report v2.csv", FID)
            == f"my_report v2_{FID}.csv"
        )


class TestUnsafeCharacterReplacement:
    def test_forward_slash_becomes_underscore(self) -> None:
        assert (
            sandbox_filename_for_document("Q1/Q2 Report", FID) == f"Q1_Q2 Report_{FID}"
        )

    def test_backslash_becomes_underscore(self) -> None:
        assert (
            sandbox_filename_for_document("path\\to\\file", FID)
            == f"path_to_file_{FID}"
        )

    def test_colon_becomes_underscore(self) -> None:
        assert sandbox_filename_for_document("Re: meeting", FID) == f"Re_ meeting_{FID}"

    def test_wildcards_and_pipes_replaced(self) -> None:
        assert sandbox_filename_for_document("file*?|<>", FID) == f"file__{FID}"

    def test_quotes_and_angle_brackets_replaced(self) -> None:
        assert (
            sandbox_filename_for_document('"quoted" <html>', FID)
            == f"_quoted_ _html__{FID}"
        )

    def test_null_byte_replaced(self) -> None:
        assert sandbox_filename_for_document("ok\x00bad", FID) == f"ok_bad_{FID}"

    def test_control_chars_replaced(self) -> None:
        assert (
            sandbox_filename_for_document("line\x01\x02\x1fok", FID) == f"line_ok_{FID}"
        )

    def test_consecutive_unsafe_chars_collapse(self) -> None:
        assert sandbox_filename_for_document("a///b\\\\c", FID) == f"a_b_c_{FID}"

    def test_path_traversal_is_neutralized(self) -> None:
        result = sandbox_filename_for_document("../etc/passwd", FID)
        assert "/" not in result
        assert result == f"_etc_passwd_{FID}"


class TestTrimmingAndFallbacks:
    def test_leading_and_trailing_whitespace_stripped(self) -> None:
        assert (
            sandbox_filename_for_document("   report.csv   ", FID)
            == f"report_{FID}.csv"
        )

    def test_leading_and_trailing_dots_stripped(self) -> None:
        assert sandbox_filename_for_document("...hidden...", FID) == f"hidden_{FID}"

    def test_empty_input_falls_back_to_document(self) -> None:
        assert sandbox_filename_for_document("", FID) == f"document_{FID}"

    def test_spaces_only_falls_back_to_document(self) -> None:
        assert sandbox_filename_for_document("     ", FID) == f"document_{FID}"

    def test_only_unsafe_chars_does_not_fall_back(self) -> None:
        assert sandbox_filename_for_document("////", FID) == f"__{FID}"
        assert sandbox_filename_for_document("   \t  ", FID) == f"__{FID}"

    def test_only_dots_falls_back_to_document(self) -> None:
        assert sandbox_filename_for_document("....", FID) == f"document_{FID}"


class TestLengthCap:
    def test_long_base_truncated_but_file_id_and_ext_preserved(self) -> None:
        fid = "abc"
        result = sandbox_filename_for_document("x" * 500 + ".pdf", fid)
        assert len(result) == 200
        assert result.endswith(f"_{fid}.pdf")

    def test_extension_survives_pathological_input(self) -> None:
        fid = "abc"
        result = sandbox_filename_for_document("x" * 300 + ".pdf", fid)
        assert len(result) == 200
        assert result.endswith(".pdf")

    def test_file_id_never_truncated(self) -> None:
        result = sandbox_filename_for_document("x" * 500, FID)
        assert result.endswith(f"_{FID}")


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
    def test_filename_embeds_file_id_when_present(self) -> None:
        chunk = _make_chunk(
            "doc-a",
            semantic_identifier="Q3 Sales Report.pdf",
            file_id="file-abc123",
        )
        section = _make_section(chunk)

        llm_string, _ = convert_inference_sections_to_llm_string([section])
        payload = json.loads(llm_string)

        assert payload["results"][0]["file_name"] == ("Q3 Sales Report_file-abc123.pdf")
        assert "file_id" not in payload["results"][0]

    def test_omitted_when_no_file_id(self) -> None:
        chunk = _make_chunk("doc-b", file_id=None)
        section = _make_section(chunk)

        llm_string, _ = convert_inference_sections_to_llm_string([section])
        payload = json.loads(llm_string)

        assert "file_name" not in payload["results"][0]

    def test_same_title_distinct_file_ids_produce_distinct_names(self) -> None:
        a = _make_chunk("doc-a", semantic_identifier="Report.pdf", file_id="fid-A")
        b = _make_chunk("doc-b", semantic_identifier="Report.pdf", file_id="fid-B")

        llm_string, _ = convert_inference_sections_to_llm_string(
            [_make_section(a), _make_section(b)]
        )
        names = [r["file_name"] for r in json.loads(llm_string)["results"]]
        assert names == ["Report_fid-A.pdf", "Report_fid-B.pdf"]

    def test_filename_matches_shared_helper(self) -> None:
        title = "Weird/Name*With:Stuff"
        chunk = _make_chunk("doc-d", semantic_identifier=title, file_id="file-match")
        section = _make_section(chunk)

        llm_string, _ = convert_inference_sections_to_llm_string([section])
        payload = json.loads(llm_string)

        assert payload["results"][0]["file_name"] == sandbox_filename_for_document(
            title, "file-match"
        )

    def test_citation_mapping_unchanged_by_file_presence(self) -> None:
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

        expected = FILE_ASSOCIATED_GUIDANCE.format(
            filename="data_file-wrap.csv", content="just the center chunk"
        )
        assert content == expected
        assert "data_file-wrap.csv" in content
        assert "just the center chunk" in content
        assert "code interpreter" in content.lower()
        assert "PLUS adjacent" not in content

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
        assert "report_file-phrasing.pdf" in content
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

        assert "sheet_file-mixed.xlsx" in results[0]["content"]
        assert "code interpreter" in results[0]["content"].lower()
        assert results[1]["content"] == "plain combined"
        assert "file_name" not in results[1]


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
