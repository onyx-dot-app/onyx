"""Profile photo upload, replacement, removal and serving.

The upload is decoded and stored again as a small WebP, so the tests check
what the serve route returns rather than byte equality with the upload.
"""

import io
from collections.abc import Callable
from uuid import UUID

import httpx
from PIL import Image

from onyx.configs.constants import ANONYMOUS_USER_UUID
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.file_record import get_filerecord_by_file_id_optional
from onyx.db.models import User
from onyx.server.manage.profile_image import (
    MAX_PROFILE_IMAGE_UPLOAD_BYTES,
    PROFILE_IMAGE_MAX_SIDE_PX,
)
from onyx.utils.file import MAX_UPLOAD_IMAGE_PIXELS
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.settings import SettingsManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


def _image_bytes(image_format: str, size: tuple[int, int] = (800, 600)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 30, 90)).save(buffer, format=image_format)
    return buffer.getvalue()


def _upload(user: DATestUser, body: bytes, filename: str = "me.png") -> httpx.Response:
    return client.post(
        f"{API_SERVER_URL}/user/profile-image",
        files={"file": (filename, io.BytesIO(body), "image/png")},
        headers={k: v for k, v in user.headers.items() if k.lower() != "content-type"},
    )


def _me(user: DATestUser) -> dict:
    response = client.get(f"{API_SERVER_URL}/me", headers=user.headers)
    response.raise_for_status()
    return response.json()


def _fetch_photo(viewer: DATestUser, owner_id: str) -> httpx.Response:
    return client.get(
        f"{API_SERVER_URL}/user/{owner_id}/profile-image", headers=viewer.headers
    )


def _file_record_exists(file_id: str) -> bool:
    with get_session_with_current_tenant() as db_session:
        return get_filerecord_by_file_id_optional(file_id, db_session) is not None


def test_upload_serves_a_downscaled_webp_to_other_users(
    user_factory: Callable[[], DATestUser],
) -> None:
    owner = user_factory()
    viewer = user_factory()

    response = _upload(owner, _image_bytes("JPEG", (2000, 1000)), "me.jpg")
    response.raise_for_status()
    file_id = response.json()["profile_image_file_id"]
    assert _me(owner)["profile_image_file_id"] == file_id

    served = _fetch_photo(viewer, owner.id)
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/webp"
    assert served.headers["etag"].startswith(f'"{file_id}-')
    with Image.open(io.BytesIO(served.content)) as image:
        assert image.format == "WEBP"
        assert image.size == (PROFILE_IMAGE_MAX_SIDE_PX, PROFILE_IMAGE_MAX_SIDE_PX // 2)

    not_modified = client.get(
        f"{API_SERVER_URL}/user/{owner.id}/profile-image",
        headers={**viewer.headers, "If-None-Match": served.headers["etag"]},
    )
    assert not_modified.status_code == 304


def test_replacing_the_photo_deletes_the_old_file(
    user_factory: Callable[[], DATestUser],
) -> None:
    owner = user_factory()

    first = _upload(owner, _image_bytes("PNG"))
    first.raise_for_status()
    first_file_id = first.json()["profile_image_file_id"]
    second = _upload(owner, _image_bytes("WEBP"), "me.webp")
    second.raise_for_status()
    second_file_id = second.json()["profile_image_file_id"]

    assert second_file_id != first_file_id
    assert not _file_record_exists(first_file_id)
    assert _file_record_exists(second_file_id)
    assert _me(owner)["profile_image_file_id"] == second_file_id


def test_removing_the_photo_deletes_the_file(
    user_factory: Callable[[], DATestUser],
) -> None:
    owner = user_factory()
    upload = _upload(owner, _image_bytes("PNG"))
    upload.raise_for_status()
    file_id = upload.json()["profile_image_file_id"]

    response = client.delete(
        f"{API_SERVER_URL}/user/profile-image", headers=owner.headers
    )
    response.raise_for_status()

    assert not _file_record_exists(file_id)
    assert _me(owner)["profile_image_file_id"] is None
    assert _fetch_photo(owner, owner.id).status_code == 404


def test_rejected_uploads_keep_the_current_photo(
    user_factory: Callable[[], DATestUser],
) -> None:
    owner = user_factory()
    upload = _upload(owner, _image_bytes("PNG"))
    upload.raise_for_status()
    file_id = upload.json()["profile_image_file_id"]

    # GIF is inline-safe elsewhere but not an allowed profile photo type.
    assert _upload(owner, _image_bytes("GIF"), "me.gif").status_code == 400
    assert _upload(owner, b"<html><script>alert(1)</script></html>").status_code == 400

    # A PNG header with a broken raster only fails when it decodes.
    broken = bytearray(_image_bytes("PNG"))
    broken[60:] = bytes(len(broken) - 60)
    assert _upload(owner, bytes(broken)).status_code == 400

    # The decoded-pixel cap stops a small file that declares a huge raster.
    side = 4097
    assert side * side > MAX_UPLOAD_IMAGE_PIXELS
    huge = io.BytesIO()
    Image.new("L", (side, side)).save(huge, format="PNG")
    assert _upload(owner, huge.getvalue()).status_code == 400

    too_large = _image_bytes("PNG", (1, 1)) + bytes(MAX_PROFILE_IMAGE_UPLOAD_BYTES)
    assert _upload(owner, too_large).status_code == 413

    assert _me(owner)["profile_image_file_id"] == file_id
    assert _file_record_exists(file_id)


def test_user_without_photo_returns_404(
    user_factory: Callable[[], DATestUser],
) -> None:
    owner = user_factory()
    assert _fetch_photo(owner, owner.id).status_code == 404


def _set_anonymous_access(admin: DATestUser, enabled: bool) -> None:
    client.patch(
        f"{API_SERVER_URL}/admin/settings",
        json={"anonymous_user_enabled": enabled},
        headers=admin.headers,
    ).raise_for_status()


def test_anonymous_user_cannot_set_a_profile_photo(admin_user: DATestUser) -> None:
    # Every anonymous visitor shares one user row, so none of them may set its photo.
    settings, settings_error = SettingsManager.get_settings(admin_user)
    assert not settings_error, settings_error
    # Unset means disabled.
    was_enabled = bool(settings.get("anonymous_user_enabled"))
    _set_anonymous_access(admin_user, True)
    try:
        anonymous = UserManager.get_anonymous_user()
        assert _upload(anonymous, _image_bytes("PNG")).status_code == 403
        assert (
            client.delete(
                f"{API_SERVER_URL}/user/profile-image", headers=anonymous.headers
            ).status_code
            == 403
        )
        with get_session_with_current_tenant() as db_session:
            anonymous_row = db_session.get(User, UUID(ANONYMOUS_USER_UUID))
            assert anonymous_row is not None
            assert anonymous_row.profile_image_file_id is None
    finally:
        _set_anonymous_access(admin_user, was_enabled)
