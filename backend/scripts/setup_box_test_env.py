"""
Script to set up Box test environment for connector tests.

This script:
1. Reads Box credentials and user IDs from .test.env
2. Creates the required folder structure
3. Creates test files with proper naming and content
4. Sets up sharing/permissions between users
5. Updates consts_and_utils.py with actual folder and user IDs

Usage:
    cd backend
    python scripts/setup_box_test_env.py
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from box_sdk_gen import BoxClient
from box_sdk_gen import BoxJWTAuth
from box_sdk_gen import JWTConfig
from box_sdk_gen.managers.folders import CreateFolderParent
from box_sdk_gen.schemas import File
from box_sdk_gen.schemas import Folder

from onyx.connectors.box.utils import parse_box_jwt_config

# Add backend to path
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))


def load_env_vars() -> None:
    """Load environment variables from .test.env."""
    env_file = backend_path / ".test.env"
    if not env_file.exists():
        raise FileNotFoundError(f".test.env file not found at {env_file}")

    with open(env_file, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                if "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value.strip('"')


def get_box_client(user_key: str = "admin") -> tuple[BoxClient, str]:
    """Get Box client for a specific user.

    Uses the same JWT config for all users, impersonating via user ID.
    """
    # Always use the same JWT config
    jwt_config_str = os.environ.get("BOX_JWT_CONFIG_JSON_STR")
    if not jwt_config_str:
        raise ValueError("BOX_JWT_CONFIG_JSON_STR not found in .test.env")

    # Get the user ID for impersonation
    user_id_map = {
        "admin": "BOX_PRIMARY_ADMIN_USER_ID",
        "test_user_1": "BOX_PRIMARY_ADMIN_USER_ID_TEST_USER_1",
        "test_user_2": "BOX_PRIMARY_ADMIN_USER_ID_TEST_USER_2",
        "test_user_3": "BOX_PRIMARY_ADMIN_USER_ID_TEST_USER_3",
    }

    primary_admin_id = os.environ.get(
        user_id_map.get(user_key, "BOX_PRIMARY_ADMIN_USER_ID")
    )

    # Parse and normalize the JWT config string
    jwt_config_dict = parse_box_jwt_config(jwt_config_str)
    # Re-serialize to ensure proper JSON format
    normalized_jwt_config_str = json.dumps(jwt_config_dict)

    # Use from_config_json_string (as used in connector)
    try:
        jwt_config = JWTConfig.from_config_json_string(normalized_jwt_config_str)
    except Exception as e:
        raise ValueError(
            f"Failed to parse JWT config: {e}. Please check your BOX_JWT_CONFIG_JSON_STR format."
        )

    auth = BoxJWTAuth(config=jwt_config)

    # Use primary admin user ID for impersonation if provided
    if primary_admin_id:
        user_auth = auth.with_user_subject(primary_admin_id)
        client = BoxClient(auth=user_auth)
        user_id = primary_admin_id
    else:
        client = BoxClient(auth=auth)
        # Get user ID
        user = client.users.get_user_me()
        user_id = user.id

    return client, user_id


def create_folder(client: BoxClient, name: str, parent_id: str = "0") -> Folder:
    """Create a folder in Box."""
    print(f"Creating folder '{name}' in parent {parent_id}...")
    try:
        from box_sdk_gen.box.errors import BoxAPIError

        folder = client.folders.create_folder(
            name=name,
            parent=CreateFolderParent(id=parent_id),
        )
        print(f"  ✓ Created folder '{name}' with ID: {folder.id}")
        return folder
    except BoxAPIError as e:
        # Handle folder already exists (409)
        error_msg = str(e)
        error_code = getattr(e, "code", None)

        if "409" in error_msg or error_code == "item_name_in_use":
            # Try to get the existing folder ID from the error
            try:
                if hasattr(e, "response") and hasattr(e.response, "body"):
                    body = e.response.body
                    if isinstance(body, dict):
                        context_info = body.get("context_info", {})
                        conflicts = context_info.get("conflicts", [])
                        if conflicts:
                            # Conflicts can be a list or dict
                            if isinstance(conflicts, list) and len(conflicts) > 0:
                                folder_id = conflicts[0].get("id")
                            elif isinstance(conflicts, dict):
                                folder_id = conflicts.get("id")
                            else:
                                folder_id = None

                            if folder_id:
                                folder = client.folders.get_folder_by_id(folder_id)
                                print(
                                    f"  ℹ Folder '{name}' already exists (ID: {folder_id})"
                                )
                                return folder
            except Exception:
                pass  # Will try listing approach below

            # If we can't get the folder from error response, try to find it by listing parent folder
            try:
                # List items in parent folder to find the folder by name
                items_response = client.folders.get_folder_items(parent_id)
                if hasattr(items_response, "entries"):
                    for item in items_response.entries:
                        # Check if this item matches the folder name
                        item_name = getattr(item, "name", None)
                        if item_name == name:
                            # Check if it's a folder (not a file)
                            item_type = getattr(item, "type", None)
                            # Box SDK Gen uses type.value or type enum
                            if hasattr(item_type, "value"):
                                item_type_str = item_type.value
                            else:
                                item_type_str = str(item_type)

                            if (
                                item_type_str == "folder"
                                or "folder" in item_type_str.lower()
                            ):
                                folder_id = item.id
                                folder = client.folders.get_folder_by_id(folder_id)
                                print(
                                    f"  ℹ Folder '{name}' already exists (ID: {folder_id})"
                                )
                                return folder
            except Exception:
                # If listing also fails, we'll try one more approach
                pass

            # Last resort: try to search for the folder
            try:
                # Use search to find the folder
                search_results = client.search.search(
                    query=name,
                    type="folder",
                    ancestor_folders=[parent_id],
                )
                if hasattr(search_results, "entries"):
                    for item in search_results.entries:
                        if getattr(item, "name", None) == name:
                            folder_id = item.id
                            folder = client.folders.get_folder_by_id(folder_id)
                            print(
                                f"  ℹ Folder '{name}' already exists (ID: {folder_id})"
                            )
                            return folder
            except Exception:
                pass

            # If we still can't get the folder, inform the user
            print(
                f"  ⚠️  Folder '{name}' already exists but could not retrieve it automatically"
            )
            print("     You may need to delete it manually or use a different name")
            raise ValueError(
                f"Folder '{name}' already exists. Please delete it manually or use a different name."
            )
        raise
    except Exception as e:
        print(f"  ✗ Error creating folder '{name}': {e}")
        raise


def upload_file(client: BoxClient, name: str, content: str, parent_id: str) -> File:
    """Upload a file to Box."""
    print(f"    Uploading file '{name}'...")
    try:
        import io
        from box_sdk_gen.box.errors import BoxAPIError

        file_content = content.encode("utf-8")
        file_size = len(file_content)
        file_io = io.BytesIO(file_content)

        # Use uploads.upload_file for small files (< 20MB)
        # Use chunked_uploads.upload_big_file for large files (>= 20MB)
        from box_sdk_gen.managers.uploads import UploadFileAttributes
        from box_sdk_gen.managers.uploads import UploadFileAttributesParentField

        if file_size < 20 * 1024 * 1024:  # 20MB threshold
            # Small file - use regular upload
            try:
                file_result = client.uploads.upload_file(
                    attributes=UploadFileAttributes(
                        name=name,
                        parent=UploadFileAttributesParentField(id=parent_id),
                    ),
                    file=file_io,
                )
                # upload_file returns Files object which contains entries list
                if hasattr(file_result, "entries") and file_result.entries:
                    uploaded_file = file_result.entries[0]
                else:
                    uploaded_file = file_result
            except BoxAPIError as e:
                # Handle file already exists (409) - check error message/code
                error_msg = str(e)
                error_code = getattr(e, "code", None)

                # Check if it's a 409 conflict error
                if "409" in error_msg or error_code == "item_name_in_use":
                    # Try to extract file ID from error response body
                    # The error response body contains conflicts with the file id
                    try:
                        # Parse the error to get the file ID from conflicts
                        # The error message shows conflicts in context_info
                        if hasattr(e, "response") and hasattr(e.response, "body"):
                            pass

                            body = e.response.body
                            if isinstance(body, dict):
                                context_info = body.get("context_info", {})
                                conflicts = context_info.get("conflicts", {})
                                if conflicts and "id" in conflicts:
                                    file_id = conflicts["id"]
                                    uploaded_file = client.files.get_file_by_id(file_id)
                                    print(
                                        f"      ℹ File '{name}' already exists (ID: {file_id})"
                                    )
                                    return uploaded_file
                    except Exception:
                        pass
                    # If we can't get the file ID, just skip with a message
                    print(f"      ℹ File '{name}' already exists, skipping upload")
                    # Return a dummy file object - the script will continue
                    from box_sdk_gen.schemas import File

                    return File(id="existing", name=name, type="file")
                raise
        else:
            # Large file - use chunked upload
            uploaded_file = client.chunked_uploads.upload_big_file(
                file=file_io,
                file_name=name,
                file_size=file_size,
                parent_folder_id=parent_id,
            )

        file_id = uploaded_file.id if hasattr(uploaded_file, "id") else "unknown"
        print(f"      ✓ Uploaded '{name}' with ID: {file_id}")
        return uploaded_file
    except Exception as e:
        print(f"      ✗ Error uploading '{name}': {e}")
        raise


def share_folder(
    client: BoxClient, folder_id: str, user_id: str, role: str = "viewer"
) -> None:
    """Share a folder with a user by creating a collaboration."""
    print(f"    Sharing folder {folder_id} with user {user_id} as {role}...")
    try:
        from box_sdk_gen import (
            CreateCollaborationAccessibleBy,
            CreateCollaborationAccessibleByTypeField,
            CreateCollaborationItem,
            CreateCollaborationItemTypeField,
            CreateCollaborationRole,
        )

        # Map role string to CreateCollaborationRole enum
        role_map = {
            "viewer": CreateCollaborationRole.VIEWER,
            "editor": CreateCollaborationRole.EDITOR,
            "co-owner": CreateCollaborationRole.CO_OWNER,
            "previewer": CreateCollaborationRole.PREVIEWER,
            "uploader": CreateCollaborationRole.UPLOADER,
            "previewer-uploader": CreateCollaborationRole.PREVIEWER_UPLOADER,
            "viewer-uploader": CreateCollaborationRole.VIEWER_UPLOADER,
        }

        collaboration_role = role_map.get(role.lower(), CreateCollaborationRole.VIEWER)

        # Create the collaboration
        collaboration = client.user_collaborations.create_collaboration(
            item=CreateCollaborationItem(
                type=CreateCollaborationItemTypeField.FOLDER,
                id=folder_id,
            ),
            accessible_by=CreateCollaborationAccessibleBy(
                type=CreateCollaborationAccessibleByTypeField.USER,
                id=user_id,
            ),
            role=collaboration_role,
        )

        print(
            f"      ✓ Successfully shared folder {folder_id} with user {user_id} as {role}"
        )
        if hasattr(collaboration, "id"):
            print(f"         Collaboration ID: {collaboration.id}")

    except Exception as e:
        error_msg = str(e)
        error_code = None
        if hasattr(e, "code"):
            error_code = e.code
        elif hasattr(e, "response") and hasattr(e.response, "status_code"):
            error_code = str(e.response.status_code)

        # Check if collaboration already exists (409 conflict or user_already_collaborator)
        if (
            error_code == "409"
            or "409" in error_msg
            or "already exists" in error_msg.lower()
            or "user_already_collaborator" in error_msg.lower()
            or getattr(e, "code", None) == "user_already_collaborator"
        ):
            print(
                f"      ℹ Collaboration already exists for folder {folder_id} and user {user_id}"
            )
        else:
            print(f"      ✗ Warning: Could not share folder: {e}")
            print(f"         Error code: {error_code}")
            print("      You may need to share this folder manually via Box UI:")
            print(f"        - Folder ID: {folder_id}")
            print(f"        - User ID: {user_id}")
            print(f"        - Role: {role}")


def remove_user_access(client: BoxClient, folder_id: str, user_id: str) -> None:
    """Remove a user's access to a folder by deleting their collaboration."""
    print(f"    Removing access for user {user_id} from folder {folder_id}...")
    try:
        # First, get all collaborations for the folder
        collaborations_response = client.list_collaborations.get_folder_collaborations(
            folder_id
        )

        # Find the collaboration for this user
        collaboration_to_delete = None
        if hasattr(collaborations_response, "entries"):
            for collab in collaborations_response.entries:
                accessible_by = getattr(collab, "accessible_by", None)
                if accessible_by:
                    collab_user_id = getattr(accessible_by, "id", None)
                    if collab_user_id == user_id:
                        collaboration_to_delete = collab
                        break

        if collaboration_to_delete:
            # Delete the collaboration
            collaboration_id = getattr(collaboration_to_delete, "id", None)
            if collaboration_id:
                client.user_collaborations.delete_collaboration_by_id(collaboration_id)
                print(
                    f"      ✓ Removed access for user {user_id} from folder {folder_id}"
                )
            else:
                print("      ⚠️  Found collaboration but no ID available")
        else:
            print(
                f"      ℹ User {user_id} does not have explicit access to folder {folder_id}"
            )

    except Exception as e:
        str(e)
        error_code = None
        if hasattr(e, "code"):
            error_code = e.code
        elif hasattr(e, "response") and hasattr(e.response, "status_code"):
            error_code = str(e.response.status_code)

        print(f"      ✗ Warning: Could not remove user access: {e}")
        print(f"         Error code: {error_code}")
        print("      You may need to remove access manually via Box UI")


def create_file_structure(
    client: BoxClient, parent_id: str, file_ids: list[int]
) -> None:
    """Create files in a folder."""
    # Import here to avoid module-level import after non-import statements (E402)
    try:
        from tests.daily.connectors.box.consts_and_utils import (
            SPECIAL_FILE_ID_TO_CONTENT_MAP as _SPECIAL_MAP,
        )
    except Exception:
        _SPECIAL_MAP = {}

    for file_id in file_ids:
        file_name = f"file_{file_id}.txt"
        if file_id in _SPECIAL_MAP:
            content = _SPECIAL_MAP[file_id]
        else:
            content = f"This is file {file_id}"
        upload_file(client, file_name, content, parent_id)


def setup_box_test_environment() -> dict[str, Any]:
    """Set up the complete Box test environment."""
    # Import test constants here to avoid E402 and ensure sys.path has been adjusted
    from tests.daily.connectors.box.consts_and_utils import (
        ADMIN_FILE_IDS,
        ADMIN_FOLDER_3_FILE_IDS,
        FOLDER_1_1_FILE_IDS,
        FOLDER_1_2_FILE_IDS,
        FOLDER_1_FILE_IDS,
        FOLDER_2_1_FILE_IDS,
        FOLDER_2_2_FILE_IDS,
        FOLDER_2_FILE_IDS,
        FOLDER_3_FILE_IDS,
        SECTIONS_FILE_IDS,
        TEST_USER_1_FILE_IDS,
        TEST_USER_2_FILE_IDS,
        TEST_USER_3_FILE_IDS,
    )

    print("=" * 80)
    print("Setting up Box test environment...")
    print("=" * 80)

    # Load environment variables
    load_env_vars()

    # Get parent folder ID from env, default to root ("0")
    parent_folder_id = os.environ.get("BOX_TEST_PARENT_FOLDER_ID", "0")
    if parent_folder_id == "0":
        print("\n⚠️  Creating test structure in ROOT folder (ID: 0)")
        print(
            "   To use a different folder, set BOX_TEST_PARENT_FOLDER_ID in .test.env"
        )
    else:
        print(f"\nCreating test structure in folder ID: {parent_folder_id}")

    # Get admin client
    admin_client, admin_user_id = get_box_client("admin")
    print(f"\nAdmin user ID: {admin_user_id}")

    # Get test user IDs (if configured)
    test_user_ids = {}
    for user_key in ["test_user_1", "test_user_2", "test_user_3"]:
        try:
            _, user_id = get_box_client(user_key)
            test_user_ids[user_key] = user_id
            print(f"{user_key} ID: {user_id}")
        except Exception as e:
            print(f"{user_key} not configured: {e}")

    # Store created folder IDs
    folder_ids = {}

    print("\n" + "=" * 80)
    print("Creating folder structure...")
    print("=" * 80)

    # Create root-level files
    print("\nCreating root-level files...")
    create_file_structure(admin_client, parent_folder_id, ADMIN_FILE_IDS)
    create_file_structure(admin_client, parent_folder_id, TEST_USER_1_FILE_IDS)
    if test_user_ids.get("test_user_2"):
        create_file_structure(admin_client, parent_folder_id, TEST_USER_2_FILE_IDS)
    if test_user_ids.get("test_user_3"):
        create_file_structure(admin_client, parent_folder_id, TEST_USER_3_FILE_IDS)

    # Create Folder 1 and subfolders
    print("\nCreating Folder 1 structure...")
    folder_1 = create_folder(admin_client, "Folder 1", parent_folder_id)
    folder_ids["FOLDER_1_ID"] = folder_1.id
    create_file_structure(admin_client, folder_1.id, FOLDER_1_FILE_IDS)

    folder_1_1 = create_folder(admin_client, "Folder 1-1", folder_1.id)
    folder_ids["FOLDER_1_1_ID"] = folder_1_1.id
    create_file_structure(admin_client, folder_1_1.id, FOLDER_1_1_FILE_IDS)

    folder_1_2 = create_folder(admin_client, "Folder 1-2", folder_1.id)
    folder_ids["FOLDER_1_2_ID"] = folder_1_2.id
    create_file_structure(admin_client, folder_1_2.id, FOLDER_1_2_FILE_IDS)

    # Create Folder 2 and subfolders
    print("\nCreating Folder 2 structure...")
    folder_2 = create_folder(admin_client, "Folder 2", parent_folder_id)
    folder_ids["FOLDER_2_ID"] = folder_2.id
    create_file_structure(admin_client, folder_2.id, FOLDER_2_FILE_IDS)

    folder_2_1 = create_folder(admin_client, "Folder 2-1", folder_2.id)
    folder_ids["FOLDER_2_1_ID"] = folder_2_1.id
    create_file_structure(admin_client, folder_2_1.id, FOLDER_2_1_FILE_IDS)

    folder_2_2 = create_folder(admin_client, "Folder 2-2", folder_2.id)
    folder_ids["FOLDER_2_2_ID"] = folder_2_2.id
    create_file_structure(admin_client, folder_2_2.id, FOLDER_2_2_FILE_IDS)

    # Create Folder 3
    print("\nCreating Folder 3...")
    folder_3 = create_folder(admin_client, "Folder 3", parent_folder_id)
    folder_ids["FOLDER_3_ID"] = folder_3.id
    create_file_structure(admin_client, folder_3.id, FOLDER_3_FILE_IDS)

    # Create Admin's Folder 3 (separate folder for sharing test)
    print("\nCreating Admin's Folder 3...")
    admin_folder_3 = create_folder(admin_client, "Admin Folder 3", parent_folder_id)
    folder_ids["ADMIN_FOLDER_3_ID"] = admin_folder_3.id
    create_file_structure(admin_client, admin_folder_3.id, ADMIN_FOLDER_3_FILE_IDS)

    # Create Sections folder
    print("\nCreating Sections folder...")
    sections_folder = create_folder(admin_client, "Sections Folder", parent_folder_id)
    folder_ids["SECTIONS_FOLDER_ID"] = sections_folder.id
    create_file_structure(admin_client, sections_folder.id, SECTIONS_FILE_IDS)

    # Set up sharing/permissions
    print("\n" + "=" * 80)
    print("Setting up sharing and permissions...")
    print("=" * 80)

    if test_user_ids.get("test_user_1"):
        user_1_id = test_user_ids["test_user_1"]
        print(f"\nSetting up permissions for test_user_1 ({user_1_id})...")
        # Share Folder 1 with test_user_1
        share_folder(admin_client, folder_1.id, user_1_id, "viewer")
        # Share Admin's Folder 3 with test_user_1
        share_folder(admin_client, admin_folder_3.id, user_1_id, "viewer")
        # Note: Individual file sharing would need to be done separately if needed

    # Set up permissions for test_user_3
    if test_user_ids.get("test_user_3"):
        user_3_id = test_user_ids["test_user_3"]
        print(f"\nSetting up permissions for test_user_3 ({user_3_id})...")
        # Share Folder 1-2 (public folder) with test_user_3 so they can access public files
        share_folder(admin_client, folder_1_2.id, user_3_id, "viewer")
        # Note: test_user_3's own files are in the root, which they should have access to
        # via their own account, but we don't need to explicitly share those

    # Explicitly restrict test_user_3 from ADMIN_FOLDER_3
    # This ensures the test_restricted_access test is useful
    if test_user_ids.get("test_user_3"):
        user_3_id = test_user_ids["test_user_3"]
        print(f"\nRestricting test_user_3 ({user_3_id}) from ADMIN_FOLDER_3...")
        remove_user_access(admin_client, admin_folder_3.id, user_3_id)

    if test_user_ids.get("test_user_2"):
        user_2_id = test_user_ids["test_user_2"]
        print(f"\nSetting up permissions for test_user_2 ({user_2_id})...")
        # Share Folder 1 with test_user_2
        share_folder(admin_client, folder_1.id, user_2_id, "viewer")
        # Share Folder 2-1 with test_user_2
        share_folder(admin_client, folder_2_1.id, user_2_id, "viewer")

    # Make Folder 1-2 public (if needed)
    print("\nMaking Folder 1-2 public...")
    try:
        # Try to update folder shared link settings
        from box_sdk_gen.managers.folders import (
            UpdateFolderByIdSharedLink,
            UpdateFolderByIdSharedLinkAccessField,
        )

        admin_client.folders.update_folder_by_id(
            folder_id=folder_1_2.id,
            shared_link=UpdateFolderByIdSharedLink(
                access=UpdateFolderByIdSharedLinkAccessField.OPEN
            ),
        )
        print("  ✓ Folder 1-2 is now public")
    except Exception as e:
        print(f"  ✗ Warning: Could not make folder public: {e}")
        print("  (This is optional - folder can be shared manually via Box UI)")
        print(f"  To make it public manually: Folder ID {folder_1_2.id}")

    # Compile results
    results = {
        "admin_user_id": admin_user_id,
        "test_user_ids": test_user_ids,
        "folder_ids": folder_ids,
    }

    print("\n" + "=" * 80)
    print("Setup complete!")
    print("=" * 80)
    print("\nCreated folder IDs:")
    for key, value in folder_ids.items():
        print(f"  {key}: {value}")
    print(f"\nAdmin User ID: {admin_user_id}")
    if test_user_ids:
        print("\nTest User IDs:")
        for key, value in test_user_ids.items():
            print(f"  {key}: {value}")

    return results


def update_consts_file(results: dict[str, Any]) -> None:
    """Update consts_and_utils.py with actual IDs."""
    consts_file = (
        backend_path / "tests" / "daily" / "connectors" / "box" / "consts_and_utils.py"
    )

    print("\n" + "=" * 80)
    print("Updating consts_and_utils.py...")
    print("=" * 80)

    with open(consts_file, "r") as f:
        content = f.read()

    # Update folder IDs
    folder_ids = results["folder_ids"]
    for key, value in folder_ids.items():
        # Replace placeholder values - try multiple patterns
        patterns = [
            (f'{key} = "123456789"', f'{key} = "{value}"'),
            (f'{key} = "123456790"', f'{key} = "{value}"'),
            (f'{key} = "123456791"', f'{key} = "{value}"'),
            (f'{key} = "123456792"', f'{key} = "{value}"'),
            (f'{key} = "123456793"', f'{key} = "{value}"'),
            (f'{key} = "123456794"', f'{key} = "{value}"'),
            (f'{key} = "123456795"', f'{key} = "{value}"'),
            (f'{key} = "123456796"', f'{key} = "{value}"'),
            (f'{key} = "123456797"', f'{key} = "{value}"'),
        ]
        for pattern, replacement in patterns:
            if pattern in content:
                content = content.replace(pattern, replacement)
                print(f"  Updated {key} = {value}")
                break
        else:
            # Try regex pattern as fallback
            pattern = f'{key} = "[^"]*"'
            new_content = re.sub(pattern, f'{key} = "{value}"', content)
            if new_content != content:
                content = new_content
                print(f"  Updated {key} = {value}")

    # Update user IDs
    admin_user_id = results["admin_user_id"]
    content = re.sub(
        r'ADMIN_USER_ID = "[^"]*"',
        f'ADMIN_USER_ID = "{admin_user_id}"',
        content,
    )
    print(f"  Updated ADMIN_USER_ID = {admin_user_id}")

    test_user_ids = results["test_user_ids"]
    user_id_map = {
        "test_user_1": "TEST_USER_1_ID",
        "test_user_2": "TEST_USER_2_ID",
        "test_user_3": "TEST_USER_3_ID",
    }
    for user_key, const_name in user_id_map.items():
        if user_key in test_user_ids:
            content = re.sub(
                f'{const_name} = "[^"]*"',
                f'{const_name} = "{test_user_ids[user_key]}"',
                content,
            )
            print(f"  Updated {const_name} = {test_user_ids[user_key]}")

    with open(consts_file, "w") as f:
        f.write(content)

    print("\n✓ Updated consts_and_utils.py with actual IDs")


if __name__ == "__main__":
    try:
        results = setup_box_test_environment()
        update_consts_file(results)
        print("\n" + "=" * 80)
        print("✅ Box test environment setup complete!")
        print("=" * 80)
        print("\nYou can now run the tests with:")
        print("  pytest -v -s backend/tests/daily/connectors/box/")
    except Exception as e:
        print(f"\n❌ Error setting up test environment: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
