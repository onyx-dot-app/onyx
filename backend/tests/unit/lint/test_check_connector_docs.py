"""The connector docs check reads the registry keys, finds a page by name,
folder or group, honours the override file, and reports stale overrides."""

from pathlib import Path

from lint import check_connector_docs as check

_CONSTANTS = {"SLACK": "slack", "GMAIL": "gmail", "TEAMS": "teams", "GCS": "gcs"}


def _docs(tmp_path: Path) -> Path:
    (tmp_path / "slack.mdx").write_text("")
    (tmp_path / "gmail").mkdir()
    (tmp_path / "microsoft-365").mkdir()
    (tmp_path / "microsoft-365" / "teams.mdx").write_text("")
    (tmp_path / "google_storage.mdx").write_text("")
    return tmp_path


def test_registered_sources_reads_document_source_keys() -> None:
    source = "MAP = {DocumentSource.SLACK: x, DocumentSource.GMAIL: y, other: z}\n"
    assert check.registered_sources(source, _CONSTANTS) == ["gmail", "slack"]


def test_pages_are_found_by_file_folder_and_group(tmp_path: Path) -> None:
    docs = _docs(tmp_path)
    assert check.check(["slack", "gmail", "teams"], {}, docs) == []


def test_missing_page_fails_unless_overridden(tmp_path: Path) -> None:
    docs = _docs(tmp_path)
    assert len(check.check(["gcs"], {}, docs)) == 1
    assert check.check(["gcs"], {"gcs": "google_storage.mdx"}, docs) == []
    assert check.check(["gcs"], {"gcs": "none"}, docs) == []
    assert len(check.check(["gcs"], {"gcs": "gone.mdx"}, docs)) == 1


def test_override_for_an_unregistered_source_fails(tmp_path: Path) -> None:
    assert len(check.check([], {"old": "none"}, _docs(tmp_path))) == 1


def test_parse_map_needs_a_reason_and_no_duplicates() -> None:
    entries, errors = check.parse_map(
        "# comment\na b.mdx\nc none: test only\nd none:\na x.mdx\ne\n"
    )
    assert entries == {"a": "b.mdx", "c": "none"}
    assert len(errors) == 3
