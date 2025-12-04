from __future__ import annotations

from onyx.connectors.sharepoint.connector import SharepointConnector


def test_extract_site_and_drive_info_from_share_link() -> None:
    url = "https://tenant.sharepoint.com/:f:/r/sites/CXEnablement/Shared%20Documents/Enablement%20Folder"

    site_descriptors = SharepointConnector._extract_site_and_drive_info([url])

    assert len(site_descriptors) == 1
    descriptor = site_descriptors[0]
    assert descriptor.url == "https://tenant.sharepoint.com/sites/CXEnablement"
    assert descriptor.drive_name == "Shared Documents"
    assert descriptor.folder_path == "Enablement Folder"


def test_extract_site_and_drive_info_standard_url() -> None:
    url = "https://tenant.sharepoint.com/sites/CXEnablement/Shared%20Documents/Nested/Path"

    site_descriptors = SharepointConnector._extract_site_and_drive_info([url])

    assert len(site_descriptors) == 1
    descriptor = site_descriptors[0]
    assert descriptor.url == "https://tenant.sharepoint.com/sites/CXEnablement"
    assert descriptor.drive_name == "Shared Documents"
    assert descriptor.folder_path == "Nested/Path"
