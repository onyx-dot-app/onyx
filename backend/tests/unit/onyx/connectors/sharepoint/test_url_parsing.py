from __future__ import annotations

from onyx.connectors.sharepoint.connector import SharepointConnector


def test_extract_site_and_drive_info_from_share_link() -> None:
    url = "https://tenant.sharepoint.com/:f:/r/sites/SampleSite/Shared%20Documents/Sample%20Folder"

    site_descriptors = SharepointConnector._extract_site_and_drive_info([url])

    assert len(site_descriptors) == 1
    descriptor = site_descriptors[0]
    assert descriptor.url == "https://tenant.sharepoint.com/sites/SampleSite"
    assert descriptor.drive_name == "Shared Documents"
    assert descriptor.folder_path == "Sample Folder"


def test_extract_site_and_drive_info_standard_url() -> None:
    url = (
        "https://tenant.sharepoint.com/sites/SampleSite/Shared%20Documents/Nested/Path"
    )

    site_descriptors = SharepointConnector._extract_site_and_drive_info([url])

    assert len(site_descriptors) == 1
    descriptor = site_descriptors[0]
    assert descriptor.url == "https://tenant.sharepoint.com/sites/SampleSite"
    assert descriptor.drive_name == "Shared Documents"
    assert descriptor.folder_path == "Nested/Path"


def test_extract_site_and_drive_info_tenant_root_url() -> None:
    """Tenant root URL (no /sites/ or /teams/) resolves to the root site
    with the trailing path treated as drive_name + folder_path."""
    url = "https://tenant.sharepoint.com/Shared%20Documents/Nested/Path"

    site_descriptors = SharepointConnector._extract_site_and_drive_info([url])

    assert len(site_descriptors) == 1
    descriptor = site_descriptors[0]
    assert descriptor.url == "https://tenant.sharepoint.com"
    assert descriptor.drive_name == "Shared Documents"
    assert descriptor.folder_path == "Nested/Path"


def test_extract_site_and_drive_info_tenant_root_url_drive_only() -> None:
    """Tenant root URL with only a drive name (no folder path)."""
    url = "https://tenant.sharepoint.com/Shared%20Documents"

    site_descriptors = SharepointConnector._extract_site_and_drive_info([url])

    assert len(site_descriptors) == 1
    descriptor = site_descriptors[0]
    assert descriptor.url == "https://tenant.sharepoint.com"
    assert descriptor.drive_name == "Shared Documents"
    assert descriptor.folder_path is None


def test_extract_site_and_drive_info_tenant_root_url_no_drive() -> None:
    """Bare tenant root URL: no drive, no folder."""
    url = "https://tenant.sharepoint.com"

    site_descriptors = SharepointConnector._extract_site_and_drive_info([url])

    assert len(site_descriptors) == 1
    descriptor = site_descriptors[0]
    assert descriptor.url == "https://tenant.sharepoint.com"
    assert descriptor.drive_name is None
    assert descriptor.folder_path is None


def test_extract_site_and_drive_info_sovereign_cloud_root_url() -> None:
    """Tenant root URL on a non-commercial Microsoft cloud (e.g. GCC High,
    DoD, 21Vianet) — the parser is host-agnostic, so the same root-site
    handling applies."""
    url = "https://tenant.sharepoint.us/Shared%20Documents/Folder"

    site_descriptors = SharepointConnector._extract_site_and_drive_info([url])

    assert len(site_descriptors) == 1
    descriptor = site_descriptors[0]
    assert descriptor.url == "https://tenant.sharepoint.us"
    assert descriptor.drive_name == "Shared Documents"
    assert descriptor.folder_path == "Folder"
