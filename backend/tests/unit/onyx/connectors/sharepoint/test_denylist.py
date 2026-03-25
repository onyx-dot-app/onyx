from __future__ import annotations

import pytest

from onyx.connectors.sharepoint.connector import _build_item_relative_path
from onyx.connectors.sharepoint.connector import _is_path_excluded
from onyx.connectors.sharepoint.connector import _is_site_excluded
from onyx.connectors.sharepoint.connector import DriveItemData
from onyx.connectors.sharepoint.connector import SharepointConnector
from onyx.connectors.sharepoint.connector import SiteDescriptor


class TestIsSiteExcluded:
    def test_exact_match(self) -> None:
        assert _is_site_excluded(
            "https://contoso.sharepoint.com/sites/archive",
            ["https://contoso.sharepoint.com/sites/archive"],
        )

    def test_trailing_slash_mismatch(self) -> None:
        assert _is_site_excluded(
            "https://contoso.sharepoint.com/sites/archive/",
            ["https://contoso.sharepoint.com/sites/archive"],
        )

    def test_glob_wildcard(self) -> None:
        assert _is_site_excluded(
            "https://contoso.sharepoint.com/sites/archive-2024",
            ["*/sites/archive-*"],
        )

    def test_no_match(self) -> None:
        assert not _is_site_excluded(
            "https://contoso.sharepoint.com/sites/engineering",
            ["https://contoso.sharepoint.com/sites/archive"],
        )

    def test_empty_patterns(self) -> None:
        assert not _is_site_excluded(
            "https://contoso.sharepoint.com/sites/engineering",
            [],
        )

    def test_multiple_patterns(self) -> None:
        patterns = [
            "*/sites/archive-*",
            "*/sites/hr-confidential",
        ]
        assert _is_site_excluded(
            "https://contoso.sharepoint.com/sites/hr-confidential",
            patterns,
        )
        assert not _is_site_excluded(
            "https://contoso.sharepoint.com/sites/engineering",
            patterns,
        )


class TestIsPathExcluded:
    def test_filename_glob(self) -> None:
        assert _is_path_excluded("Engineering/report.tmp", ["*.tmp"])

    def test_filename_only(self) -> None:
        assert _is_path_excluded("report.tmp", ["*.tmp"])

    def test_office_lock_files(self) -> None:
        assert _is_path_excluded("Docs/~$document.docx", ["~$*"])

    def test_folder_glob(self) -> None:
        assert _is_path_excluded("Archive/old/report.docx", ["Archive/*"])

    def test_nested_folder_glob(self) -> None:
        assert _is_path_excluded("Projects/Archive/report.docx", ["*/Archive/*"])

    def test_no_match(self) -> None:
        assert not _is_path_excluded("Engineering/report.docx", ["*.tmp"])

    def test_empty_patterns(self) -> None:
        assert not _is_path_excluded("anything.docx", [])

    def test_multiple_patterns(self) -> None:
        patterns = ["*.tmp", "~$*", "Archive/*"]
        assert _is_path_excluded("test.tmp", patterns)
        assert _is_path_excluded("~$doc.docx", patterns)
        assert _is_path_excluded("Archive/old.pdf", patterns)
        assert not _is_path_excluded("Engineering/report.docx", patterns)


class TestBuildItemRelativePath:
    def test_with_folder(self) -> None:
        assert (
            _build_item_relative_path(
                "/drives/abc/root:/Engineering/API", "report.docx"
            )
            == "Engineering/API/report.docx"
        )

    def test_root_level(self) -> None:
        assert (
            _build_item_relative_path("/drives/abc/root:", "report.docx")
            == "report.docx"
        )

    def test_none_parent(self) -> None:
        assert _build_item_relative_path(None, "report.docx") == "report.docx"

    def test_no_root_marker(self) -> None:
        assert _build_item_relative_path("/drives/abc", "report.docx") == "report.docx"


class TestFilterExcludedSites:
    def test_filters_matching_sites(self) -> None:
        connector = SharepointConnector(
            excluded_sites=["*/sites/archive"],
        )
        descriptors = [
            SiteDescriptor(
                url="https://t.sharepoint.com/sites/archive",
                drive_name=None,
                folder_path=None,
            ),
            SiteDescriptor(
                url="https://t.sharepoint.com/sites/engineering",
                drive_name=None,
                folder_path=None,
            ),
        ]
        result = connector._filter_excluded_sites(descriptors)
        assert len(result) == 1
        assert result[0].url == "https://t.sharepoint.com/sites/engineering"

    def test_empty_excluded_returns_all(self) -> None:
        connector = SharepointConnector(excluded_sites=[])
        descriptors = [
            SiteDescriptor(
                url="https://t.sharepoint.com/sites/a",
                drive_name=None,
                folder_path=None,
            ),
            SiteDescriptor(
                url="https://t.sharepoint.com/sites/b",
                drive_name=None,
                folder_path=None,
            ),
        ]
        result = connector._filter_excluded_sites(descriptors)
        assert len(result) == 2


class TestIsDriveitemExcluded:
    def test_excluded_by_extension(self) -> None:
        connector = SharepointConnector(excluded_paths=["*.tmp"])
        item = DriveItemData(
            id="1",
            name="file.tmp",
            web_url="https://example.com/file.tmp",
            parent_reference_path="/drives/abc/root:/Docs",
        )
        assert connector._is_driveitem_excluded(item)

    def test_not_excluded(self) -> None:
        connector = SharepointConnector(excluded_paths=["*.tmp"])
        item = DriveItemData(
            id="1",
            name="file.docx",
            web_url="https://example.com/file.docx",
            parent_reference_path="/drives/abc/root:/Docs",
        )
        assert not connector._is_driveitem_excluded(item)

    def test_no_patterns_never_excludes(self) -> None:
        connector = SharepointConnector(excluded_paths=[])
        item = DriveItemData(
            id="1",
            name="file.tmp",
            web_url="https://example.com/file.tmp",
            parent_reference_path="/drives/abc/root:/Docs",
        )
        assert not connector._is_driveitem_excluded(item)

    def test_folder_pattern(self) -> None:
        connector = SharepointConnector(excluded_paths=["Archive/*"])
        item = DriveItemData(
            id="1",
            name="old.pdf",
            web_url="https://example.com/old.pdf",
            parent_reference_path="/drives/abc/root:/Archive",
        )
        assert connector._is_driveitem_excluded(item)

    @pytest.mark.parametrize(
        "whitespace_pattern",
        ["", "  ", "\t"],
    )
    def test_whitespace_patterns_ignored(self, whitespace_pattern: str) -> None:
        connector = SharepointConnector(excluded_paths=[whitespace_pattern])
        assert connector.excluded_paths == []
