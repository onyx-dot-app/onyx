"""User library tests."""

from __future__ import annotations

from uuid import uuid4

from onyx.server.features.build.user_library.api import DeleteFileResponse
from onyx.server.features.build.user_library.api import LibraryEntryResponse
from onyx.server.features.build.user_library.api import UploadResponse
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.user_library_http import delete_user_library_file
from tests.integration.tests.craft.user_library_http import list_user_library_tree
from tests.integration.tests.craft.user_library_http import make_zip_bytes
from tests.integration.tests.craft.user_library_http import upload_user_library_files
from tests.integration.tests.craft.user_library_http import upload_user_library_zip


def _find_doc_by_name(
    entries: list[LibraryEntryResponse], name: str
) -> LibraryEntryResponse | None:
    return next((e for e in entries if e.name == name), None)


def test_upload_persists_file_to_s3(admin_user: DATestUser) -> None:
    """POST → ``CRAFT_FILE`` document + storage blob."""
    filename = f"persist-{uuid4().hex[:8]}.bin"
    payload = b"persisted-bytes-" + uuid4().hex.encode()
    response = upload_user_library_files(
        admin_user, [(filename, payload, "application/octet-stream")]
    )
    response.raise_for_status()
    body = UploadResponse.model_validate(response.json())

    assert body.total_uploaded == 1
    assert body.total_size_bytes == len(payload)
    [entry] = body.entries
    assert entry.name == filename
    assert entry.file_size == len(payload)
    assert entry.id.startswith("CRAFT_FILE__")

    tree = list_user_library_tree(admin_user)
    assert any(e.id == entry.id for e in tree)


def test_upload_batch_over_count_cap_rejects(admin_user: DATestUser) -> None:
    # CI lowers USER_LIBRARY_MAX_FILES_PER_UPLOAD to 5.
    files = [(f"tiny-{i}-{uuid4().hex[:6]}.txt", b"x", "text/plain") for i in range(6)]
    response = upload_user_library_files(admin_user, files)

    assert response.status_code == 400


def test_upload_zip_extracts_and_applies_caps_recursively(
    admin_user: DATestUser,
) -> None:
    """Zip upload extracts inner files; same caps apply."""
    small_member_name = f"inner-{uuid4().hex[:6]}.txt"
    small_zip = make_zip_bytes({small_member_name: b"hello"})
    response = upload_user_library_zip(admin_user, small_zip, filename="small.zip")
    response.raise_for_status()
    body = UploadResponse.model_validate(response.json())
    assert body.total_uploaded == 1
    [_entry] = body.entries
    tree = list_user_library_tree(admin_user)
    assert any(small_member_name in e.name for e in tree)

    # CI lowers USER_LIBRARY_MAX_FILES_PER_UPLOAD to 5; a 6-member zip trips it.
    over_cap_members = {f"file-{i}-{uuid4().hex[:4]}.txt": b"x" for i in range(6)}
    zip_bytes = make_zip_bytes(over_cap_members)
    response = upload_user_library_zip(admin_user, zip_bytes)
    assert response.status_code == 400


def test_delete_file_removes_s3_blob(admin_user: DATestUser) -> None:
    """DELETE → row gone from tree, storage blob deleted."""
    filename = f"delete-{uuid4().hex[:6]}.txt"
    response = upload_user_library_files(admin_user, [(filename, b"bye", "text/plain")])
    response.raise_for_status()
    upload_body = UploadResponse.model_validate(response.json())
    document_id = upload_body.entries[0].id

    assert _find_doc_by_name(list_user_library_tree(admin_user), filename) is not None

    delete_response = delete_user_library_file(admin_user, document_id)
    delete_response.raise_for_status()
    delete_body = DeleteFileResponse.model_validate(delete_response.json())
    assert delete_body.deleted == document_id

    assert _find_doc_by_name(list_user_library_tree(admin_user), filename) is None


def test_cross_user_access_returns_404(
    admin_user: DATestUser, basic_user: DATestUser
) -> None:
    """Foreign user -> 404 (or 403) on any file op."""
    filename = f"cross-{uuid4().hex[:6]}.txt"
    response = upload_user_library_files(
        admin_user, [(filename, b"private", "text/plain")]
    )
    response.raise_for_status()
    upload_body = UploadResponse.model_validate(response.json())
    document_id = upload_body.entries[0].id

    delete_response = delete_user_library_file(basic_user, document_id)
    assert delete_response.status_code in (403, 404)

    basic_tree = list_user_library_tree(basic_user)
    assert all(e.id != document_id for e in basic_tree)
