"""
Test suite for Joplin connector exclusion filters.

This test validates that the exclude_folders and exclude_tags parameters
properly filter out notebooks and notes from being indexed.
"""

import os

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.joplin.connector import JoplinConnector


@pytest.fixture
def joplin_base_url() -> str:
    """Get Joplin base URL from environment or use default."""
    return os.environ.get("JOPLIN_TEST_BASE_URL", "http://localhost:41184")


@pytest.fixture
def joplin_api_token() -> str:
    """Get Joplin API token from environment."""
    token = os.environ.get("JOPLIN_TEST_API_TOKEN")
    if not token:
        pytest.skip("JOPLIN_TEST_API_TOKEN environment variable not set")
    return token


def test_joplin_connection_and_fetch(
    joplin_base_url: str, joplin_api_token: str
) -> None:
    """Test basic connection to Joplin and ability to fetch notes."""
    connector = JoplinConnector(base_url=joplin_base_url)
    connector.load_credentials({"joplin_api_token": joplin_api_token})

    # Validate connector settings (tests connection)
    connector.validate_connector_settings()

    doc_count = 0
    note_titles = []
    folders_found = set()
    tags_found = set()

    # Fetch all notes
    for doc_batch in connector.load_from_state():
        doc_count += len(doc_batch)
        for doc in doc_batch:
            # Validate basic document structure
            assert doc.id, "Document should have an ID"
            assert doc.semantic_identifier, "Document should have a title"
            assert doc.source == DocumentSource.JOPLIN
            assert "folder_path" in doc.metadata, "Document should have folder_path"
            assert len(doc.sections) > 0, "Document should have content sections"

            # Collect metadata for analysis
            note_titles.append(doc.semantic_identifier)
            folder_path = doc.metadata.get("folder_path", "")
            if folder_path:
                folders_found.add(folder_path)

            # Collect tags if present
            note_tags = doc.metadata.get("tags", [])
            for tag in note_tags:
                tags_found.add(tag)

    assert doc_count > 0, "Should have fetched at least one note from Joplin"

    print(f"\n✅ Successfully connected to Joplin")
    print(f"📊 Total notes fetched: {doc_count}")
    print(f"📁 Folders found: {sorted(folders_found)}")
    print(f"🏷️  Tags found: {sorted(tags_found)}")
    print(f"📝 Sample titles: {note_titles[:5]}")


def test_joplin_exclude_folders(
    joplin_base_url: str, joplin_api_token: str
) -> None:
    """Test that exclude_folders parameter properly filters out notebooks."""
    # First, get all notes to know what folders exist
    connector_all = JoplinConnector(base_url=joplin_base_url)
    connector_all.load_credentials({"joplin_api_token": joplin_api_token})

    all_folders = set()
    all_note_count = 0

    for doc_batch in connector_all.load_from_state():
        all_note_count += len(doc_batch)
        for doc in doc_batch:
            folder_path = doc.metadata.get("folder_path", "")
            if folder_path and folder_path != "Root":
                # Extract top-level folder name
                top_folder = folder_path.split("/")[0] if "/" in folder_path else folder_path
                all_folders.add(top_folder)

    if not all_folders:
        pytest.skip("No folders found in Joplin to test exclusion")

    print(f"\n📁 Available folders: {sorted(all_folders)}")

    # Pick folders to exclude (use environment variable or first folder)
    exclude_folders_env = os.environ.get("JOPLIN_TEST_EXCLUDE_FOLDERS", "")
    exclude_folders_list = [f.strip() for f in exclude_folders_env.split(",") if f.strip()]

    if not exclude_folders_list and all_folders:
        # Default: exclude the first folder alphabetically
        exclude_folders_list = [sorted(all_folders)[0]]

    print(f"🚫 Testing exclusion of folders: {exclude_folders_list}")

    # Create connector with exclusion filter
    connector_filtered = JoplinConnector(
        base_url=joplin_base_url,
        exclude_folders=exclude_folders_list,
    )
    connector_filtered.load_credentials({"joplin_api_token": joplin_api_token})

    filtered_folders = set()
    filtered_note_count = 0

    for doc_batch in connector_filtered.load_from_state():
        filtered_note_count += len(doc_batch)
        for doc in doc_batch:
            folder_path = doc.metadata.get("folder_path", "")

            # Verify excluded folders are not present
            for excluded_folder in exclude_folders_list:
                # Check if excluded folder matches exactly or is a path component
                folder_parts = folder_path.split('/')
                assert excluded_folder not in folder_parts, (
                    f"Note '{doc.semantic_identifier}' has excluded folder "
                    f"'{excluded_folder}' in path: {folder_path}"
                )

            if folder_path and folder_path != "Root":
                top_folder = folder_path.split("/")[0] if "/" in folder_path else folder_path
                filtered_folders.add(top_folder)

    print(f"✅ Filtered notes count: {filtered_note_count}")
    print(f"✅ Folders after exclusion: {sorted(filtered_folders)}")

    # Verify exclusion worked
    assert filtered_note_count < all_note_count, (
        "Exclusion should reduce note count"
    )

    for excluded_folder in exclude_folders_list:
        assert excluded_folder not in filtered_folders, (
            f"Excluded folder '{excluded_folder}' should not appear in results"
        )


def test_joplin_exclude_tags(
    joplin_base_url: str, joplin_api_token: str
) -> None:
    """Test that exclude_tags parameter properly filters out tagged notes."""
    # First, get all notes to know what tags exist
    connector_all = JoplinConnector(base_url=joplin_base_url)
    connector_all.load_credentials({"joplin_api_token": joplin_api_token})

    all_tags = set()
    all_note_count = 0

    for doc_batch in connector_all.load_from_state():
        all_note_count += len(doc_batch)
        for doc in doc_batch:
            note_tags = doc.metadata.get("tags", [])
            for tag in note_tags:
                all_tags.add(tag)

    if not all_tags:
        pytest.skip("No tags found in Joplin to test exclusion")

    print(f"\n🏷️  Available tags: {sorted(all_tags)}")

    # Pick tags to exclude (use environment variable or first tag)
    exclude_tags_env = os.environ.get("JOPLIN_TEST_EXCLUDE_TAGS", "")
    exclude_tags_list = [t.strip() for t in exclude_tags_env.split(",") if t.strip()]

    if not exclude_tags_list and all_tags:
        # Default: exclude the first tag alphabetically
        exclude_tags_list = [sorted(all_tags)[0]]

    print(f"🚫 Testing exclusion of tags: {exclude_tags_list}")

    # Create connector with tag exclusion filter
    connector_filtered = JoplinConnector(
        base_url=joplin_base_url,
        exclude_tags=exclude_tags_list,
    )
    connector_filtered.load_credentials({"joplin_api_token": joplin_api_token})

    filtered_tags = set()
    filtered_note_count = 0

    for doc_batch in connector_filtered.load_from_state():
        filtered_note_count += len(doc_batch)
        for doc in doc_batch:
            note_tags = doc.metadata.get("tags", [])

            # Verify excluded tags are not present
            for excluded_tag in exclude_tags_list:
                assert excluded_tag not in note_tags, (
                    f"Note '{doc.semantic_identifier}' has excluded tag "
                    f"'{excluded_tag}': {note_tags}"
                )

            for tag in note_tags:
                filtered_tags.add(tag)

    print(f"✅ Filtered notes count: {filtered_note_count}")
    print(f"✅ Tags after exclusion: {sorted(filtered_tags)}")

    # Verify exclusion worked
    assert filtered_note_count <= all_note_count, (
        "Exclusion should not increase note count"
    )

    for excluded_tag in exclude_tags_list:
        assert excluded_tag not in filtered_tags, (
            f"Excluded tag '{excluded_tag}' should not appear in results"
        )


def test_joplin_combined_exclusion(
    joplin_base_url: str, joplin_api_token: str
) -> None:
    """Test combined folder and tag exclusion filters."""
    # Get baseline data
    connector_all = JoplinConnector(base_url=joplin_base_url)
    connector_all.load_credentials({"joplin_api_token": joplin_api_token})

    all_folders = set()
    all_tags = set()
    all_note_count = 0

    for doc_batch in connector_all.load_from_state():
        all_note_count += len(doc_batch)
        for doc in doc_batch:
            folder_path = doc.metadata.get("folder_path", "")
            if folder_path and folder_path != "Root":
                top_folder = folder_path.split("/")[0] if "/" in folder_path else folder_path
                all_folders.add(top_folder)

            note_tags = doc.metadata.get("tags", [])
            for tag in note_tags:
                all_tags.add(tag)

    if not all_folders and not all_tags:
        pytest.skip("No folders or tags found to test combined exclusion")

    # Select items to exclude
    exclude_folders_list = [sorted(all_folders)[0]] if all_folders else []
    exclude_tags_list = [sorted(all_tags)[0]] if all_tags else []

    print(f"\n🚫 Combined exclusion test:")
    print(f"   Folders: {exclude_folders_list}")
    print(f"   Tags: {exclude_tags_list}")

    # Create connector with combined filters
    connector_filtered = JoplinConnector(
        base_url=joplin_base_url,
        exclude_folders=exclude_folders_list,
        exclude_tags=exclude_tags_list,
    )
    connector_filtered.load_credentials({"joplin_api_token": joplin_api_token})

    filtered_note_count = 0

    for doc_batch in connector_filtered.load_from_state():
        filtered_note_count += len(doc_batch)
        for doc in doc_batch:
            folder_path = doc.metadata.get("folder_path", "")
            note_tags = doc.metadata.get("tags", [])

            # Verify no excluded folders
            for excluded_folder in exclude_folders_list:
                assert excluded_folder not in folder_path

            # Verify no excluded tags
            for excluded_tag in exclude_tags_list:
                assert excluded_tag not in note_tags

    print(f"✅ Combined filter result: {filtered_note_count} notes")

    # Should be fewer notes than baseline
    assert filtered_note_count <= all_note_count


def test_joplin_exclusion_priority_over_inclusion(
    joplin_base_url: str, joplin_api_token: str
) -> None:
    """Test that exclusion filters take priority over inclusion filters."""
    # Get available folders
    connector_all = JoplinConnector(base_url=joplin_base_url)
    connector_all.load_credentials({"joplin_api_token": joplin_api_token})

    all_folders = set()
    for doc_batch in connector_all.load_from_state():
        for doc in doc_batch:
            folder_path = doc.metadata.get("folder_path", "")
            if folder_path and folder_path != "Root":
                top_folder = folder_path.split("/")[0] if "/" in folder_path else folder_path
                all_folders.add(top_folder)

    if len(all_folders) < 2:
        pytest.skip("Need at least 2 folders to test priority")

    sorted_folders = sorted(all_folders)
    folder_to_test = sorted_folders[0]

    print(f"\n🔄 Testing priority with folder: {folder_to_test}")
    print(f"   include_folders=['{folder_to_test}']")
    print(f"   exclude_folders=['{folder_to_test}']")
    print(f"   Expected: Exclusion wins, no notes from this folder")

    # Create connector with conflicting include/exclude
    connector = JoplinConnector(
        base_url=joplin_base_url,
        include_folders=[folder_to_test],
        exclude_folders=[folder_to_test],
    )
    connector.load_credentials({"joplin_api_token": joplin_api_token})

    note_count = 0
    for doc_batch in connector.load_from_state():
        note_count += len(doc_batch)
        for doc in doc_batch:
            folder_path = doc.metadata.get("folder_path", "")
            # Exclusion should win - folder should not appear
            assert folder_to_test not in folder_path, (
                f"Excluded folder '{folder_to_test}' should not appear "
                f"even though it's in include list. Path: {folder_path}"
            )

    print(f"✅ Priority test passed: {note_count} notes (excluded folder not present)")
