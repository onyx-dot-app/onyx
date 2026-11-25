"""Unit tests for the search-result → LLM surface."""

import hashlib
import json

import pytest

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk, InferenceSection
from onyx.server.features.build.sandbox.harness_base import search_file_name
from onyx.tools.tool_implementations.utils import (
    FILE_ASSOCIATED_GUIDANCE,
    convert_inference_sections_to_llm_string,
)

FID = "550e8400-e29b-41d4-a716-446655440000"


class TestSearchFileName:
    def test_the_prefix_is_a_hash_of_the_file_id(self) -> None:
        digest = hashlib.sha256(FID.encode()).hexdigest()[:8]
        assert search_file_name(FID, "Q3 Sales.pdf") == f"{digest}-Q3 Sales.pdf"

    def test_one_title_with_two_files_gets_two_names(self) -> None:
        # Connector IDs that share their leading digits still differ.
        assert search_file_name("1234567890", "Report.pdf") != search_file_name(
            "1234567891", "Report.pdf"
        )

    def test_shell_and_path_characters_are_replaced(self) -> None:
        name = search_file_name(FID, "$(curl evil)`id`; rm -rf ~.csv")
        assert not set(name) & set("$`'\";&|()<>!*?[]{}~#/")
        assert name.endswith(".csv")

    def test_a_title_with_slashes_stays_whole(self) -> None:
        assert search_file_name(FID, "Q1/Q2 Report\\v2.csv").endswith(
            "-Q1_Q2 Report_v2.csv"
        )

    def test_a_multibyte_title_fits_the_byte_limit(self) -> None:
        name = search_file_name(FID, "報告" * 100 + ".csv")
        assert len(name.encode()) <= 255
        assert name.endswith(".csv")


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


def _convert_with_files(
    sections: list[InferenceSection], citation_start: int = 1
) -> tuple[str, dict[int, str]]:
    """Convert where a tool opens the file of every section that has one."""
    return convert_inference_sections_to_llm_string(
        sections,
        citation_start=citation_start,
        file_names={
            chunk.file_id: search_file_name(chunk.file_id, chunk.semantic_identifier)
            for chunk in (section.center_chunk for section in sections)
            if chunk.file_id is not None
        },
    )


class TestCodeInterpreterFilenameInLLMJson:
    def test_filename_embeds_file_id_when_present(self) -> None:
        chunk = _make_chunk(
            "doc-a",
            semantic_identifier="Q3 Sales Report.pdf",
            file_id="file-abc123",
        )
        section = _make_section(chunk)

        llm_string, _ = _convert_with_files([section])
        payload = json.loads(llm_string)

        assert payload["results"][0]["file_name"] == search_file_name(
            "file-abc123", "Q3 Sales Report.pdf"
        )
        assert "file_id" not in payload["results"][0]

    def test_omitted_when_no_file_id(self) -> None:
        chunk = _make_chunk("doc-b", file_id=None)
        section = _make_section(chunk)

        llm_string, _ = _convert_with_files([section])
        payload = json.loads(llm_string)

        assert "file_name" not in payload["results"][0]

    def test_same_title_distinct_file_ids_produce_distinct_names(self) -> None:
        a = _make_chunk("doc-a", semantic_identifier="Report.pdf", file_id="fid-A")
        b = _make_chunk("doc-b", semantic_identifier="Report.pdf", file_id="fid-B")

        llm_string, _ = _convert_with_files([_make_section(a), _make_section(b)])
        names = [r["file_name"] for r in json.loads(llm_string)["results"]]
        assert names == [
            search_file_name("fid-A", "Report.pdf"),
            search_file_name("fid-B", "Report.pdf"),
        ]

    def test_citation_mapping_unchanged_by_file_presence(self) -> None:
        chunk = _make_chunk(
            "doc-e",
            semantic_identifier="Anything.csv",
            file_id="file-citation",
        )
        section = _make_section(chunk)

        _, citation_mapping = _convert_with_files([section], citation_start=42)

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

        llm_string, _ = _convert_with_files([section])
        payload = json.loads(llm_string)
        content = payload["results"][0]["content"]

        expected = FILE_ASSOCIATED_GUIDANCE.format(
            filename=search_file_name("file-wrap", "data.csv"),
            content="just the center chunk",
        )
        assert content == expected
        assert search_file_name("file-wrap", "data.csv") in content
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

        llm_string, _ = _convert_with_files([section])
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

        llm_string, _ = _convert_with_files([section])
        payload = json.loads(llm_string)
        content = payload["results"][0]["content"]

        assert "excerpt" in content.lower()
        assert search_file_name("file-phrasing", "report.pdf") in content
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

        llm_string, _ = _convert_with_files(sections)
        results = json.loads(llm_string)["results"]

        assert search_file_name("file-mixed", "sheet.xlsx") in results[0]["content"]
        assert "code interpreter" in results[0]["content"].lower()
        assert results[1]["content"] == "plain combined"
        assert "file_name" not in results[1]


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])


def test_a_file_that_no_tool_opens_gets_no_sentence() -> None:
    chunk = _make_chunk(
        "doc-k", semantic_identifier="sheet.xlsx", file_id="file-k", content="body"
    )
    sections = [_make_section(chunk, combined_content="all of the section")]

    for file_names in (None, {}, {"other-file": "other.csv"}):
        llm_string, _ = convert_inference_sections_to_llm_string(
            sections, file_names=file_names
        )
        [result] = json.loads(llm_string)["results"]
        assert result["content"] == "all of the section"
        assert "file_name" not in result
