from __future__ import annotations

from onyx.connectors.sharepoint.connector import extract_site_descriptors


def test_extract_site_and_drive_info_from_share_link() -> None:
    url = "https://tenant.sharepoint.com/:f:/r/sites/SampleSite/Shared%20Documents/Sample%20Folder"

    site_descriptors = extract_site_descriptors([url])

    assert len(site_descriptors) == 1
    descriptor = site_descriptors[0]
    assert descriptor.url == "https://tenant.sharepoint.com/sites/SampleSite"
    assert descriptor.drive_name == "Shared Documents"
    assert descriptor.folder_path == "Sample Folder"


def test_extract_site_and_drive_info_standard_url() -> None:
    url = (
        "https://tenant.sharepoint.com/sites/SampleSite/Shared%20Documents/Nested/Path"
    )

    site_descriptors = extract_site_descriptors([url])

    assert len(site_descriptors) == 1
    descriptor = site_descriptors[0]
    assert descriptor.url == "https://tenant.sharepoint.com/sites/SampleSite"
    assert descriptor.drive_name == "Shared Documents"
    assert descriptor.folder_path == "Nested/Path"
