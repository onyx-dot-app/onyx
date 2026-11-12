"""The per-user skill limit on a user's own writes (G7a): 500 MB or 5,000
files. Changes that admins and sharers make for other users are not refused.

Sizes are patched on plugin_version rows, so small real bundles stand for
large ones."""

import io
import zipfile
from collections.abc import Generator
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select, update

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Plugin, PluginVersion
from onyx.skills.built_in import BUILT_IN_SKILLS_USAGE
from onyx.skills.limits import SKILL_WRITE_MAX_BYTES, SKILL_WRITE_MAX_FILES
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.skills.conftest import share_skill, unique_name

_MB = 1024 * 1024


_FILLERS: list[UUID] = []


@pytest.fixture(autouse=True)
def _empty_fillers() -> Generator[None, None, None]:
    """Users near the limit would make later company-wide changes fail."""
    yield
    while _FILLERS:
        _set_size(_FILLERS.pop(), size=0, files=0)


def _set_size(
    skill_id: UUID | str, *, size: int | None = None, files: int | None = None
) -> None:
    """Patch the size of the plugin's current version."""
    values: dict[str, int] = {}
    if size is not None:
        values["unpacked_size_bytes"] = size
    if files is not None:
        values["file_count"] = files
    with get_session_with_current_tenant() as db_session:
        current = db_session.scalar(
            select(Plugin.current_version_id).where(Plugin.id == UUID(str(skill_id)))
        )
        db_session.execute(
            update(PluginVersion).where(PluginVersion.id == current).values(**values)
        )
        db_session.commit()


def _fill(user: DATestUser, *, free_bytes: int = 0, free_files: int = 0) -> UUID:
    """Give the user one enabled skill that leaves ``free_bytes`` and
    ``free_files`` under the limits (negative: past them)."""
    skill = SkillManager.create_custom(user, name=unique_name("filler"))
    _set_size(
        skill.id,
        size=SKILL_WRITE_MAX_BYTES - BUILT_IN_SKILLS_USAGE.bytes - free_bytes,
        files=SKILL_WRITE_MAX_FILES - BUILT_IN_SKILLS_USAGE.files - free_files,
    )
    _FILLERS.append(skill.id)
    return skill.id


def _group_share(group_id: int, policy: str) -> dict[str, Any]:
    return {
        "group_shares": [{"group_id": group_id, "permission": "VIEWER"}],
        "group_settings": [{"group_id": group_id, "installation_policy": policy}],
    }


def _multipart_headers(user: DATestUser) -> dict[str, str]:
    headers = dict(user.headers)
    headers.pop("Content-Type", None)
    return headers


def _upload(user: DATestUser, bundle: bytes, name: str) -> httpx.Response:
    return client.post(
        f"{API_SERVER_URL}/skills/custom",
        files={
            "auto_enable": (None, "true", None),
            "bundle": (f"{name}.zip", io.BytesIO(bundle), "application/zip"),
        },
        headers=_multipart_headers(user),
    )


def _bundle(name: str, extra_bytes: int = 0) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "SKILL.md",
            f"---\nname: {name}\ndescription: Limit test\n---\n\nDo the work.\n",
        )
        if extra_bytes:
            zf.writestr("data.txt", "a" * extra_bytes)
    return buf.getvalue()


def _assert_refused(response: httpx.Response) -> dict[str, Any]:
    assert response.status_code == 413, response.text
    body = response.json()
    assert body["error_code"] == "SKILL_LIMIT_EXCEEDED"
    limit = body["skill_limit"]
    assert set(limit) == {"usage", "max_bytes", "max_files"}
    assert limit["max_bytes"] == SKILL_WRITE_MAX_BYTES
    assert limit["max_files"] == SKILL_WRITE_MAX_FILES
    return limit


def _custom_names(user: DATestUser) -> set[str]:
    return {skill.name for skill in SkillManager.list_for_user(user).customs}


def test_upload_refused_past_500_mb() -> None:
    user = UserManager.create(name=unique_name("limit_bytes"))
    filler = _fill(user, free_bytes=10, free_files=100)

    name = unique_name("too-big")
    limit = _assert_refused(_upload(user, _bundle(name, extra_bytes=64), name))
    assert limit["usage"]["bytes"] > SKILL_WRITE_MAX_BYTES
    assert name not in _custom_names(user)

    # With room, the same upload is allowed.
    _set_size(filler, size=0, files=0)
    response = _upload(user, _bundle(name, extra_bytes=64), name)
    assert response.status_code == 200, response.text


def test_upload_refused_past_5000_files() -> None:
    user = UserManager.create(name=unique_name("limit_files"))
    _fill(user, free_bytes=10 * _MB, free_files=0)

    name = unique_name("one-file-too-many")
    limit = _assert_refused(_upload(user, _bundle(name), name))
    assert limit["usage"]["files"] == SKILL_WRITE_MAX_FILES + 1
    assert name not in _custom_names(user)


def test_batch_upload_reports_limit_per_skill() -> None:
    user = UserManager.create(name=unique_name("limit_batch"))
    _fill(user, free_bytes=10, free_files=100)

    name = unique_name("batch-too-big")
    response = client.post(
        f"{API_SERVER_URL}/skills/custom/batch",
        files=[
            (
                "bundles",
                (
                    f"{name}.zip",
                    io.BytesIO(_bundle(name, extra_bytes=64)),
                    "application/zip",
                ),
            )
        ],
        headers=_multipart_headers(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported"] == []
    (refused,) = body["not_imported"]
    assert "The limit is 500 MB" in refused["reason"]


def test_toggle_on_refused_with_usage() -> None:
    owner = UserManager.create(name=unique_name("toggle_owner"))
    user = UserManager.create(name=unique_name("toggle_user"))
    skill = SkillManager.create_custom(
        owner, name=unique_name("toggle"), is_public=True
    )
    _set_size(skill.id, size=5 * _MB)
    _fill(user, free_bytes=1 * _MB, free_files=100)

    response = client.put(
        f"{API_SERVER_URL}/skills/{skill.id}/enabled",
        json={"enabled": True},
        headers=user.headers,
    )
    limit = _assert_refused(response)
    assert limit["usage"]["bytes"] > SKILL_WRITE_MAX_BYTES


def test_admin_change_past_the_limit_is_not_refused(admin_user: DATestUser) -> None:
    """A group setting that puts a member past the limit is saved. The member
    shows in the admin list of users past the limit."""
    author = UserManager.create(name=unique_name("req_author"))
    full = UserManager.create(name=unique_name("req_full"))
    group = UserGroupManager.create(
        admin_user, name=unique_name("req-group"), user_ids=[full.id]
    )
    skill = SkillManager.create_custom(author, name=unique_name("req"))
    _set_size(skill.id, size=10 * _MB)
    _fill(full, free_bytes=5 * _MB, free_files=100)

    share_skill(
        admin_user, skill.id, _group_share(group.id, "REQUIRED")
    ).raise_for_status()
    assert skill.name in _custom_names(full)
    over = client.get(
        f"{API_SERVER_URL}/skills/users-over-limit", headers=admin_user.headers
    )
    over.raise_for_status()
    assert full.id in {user["user_id"] for user in over.json()["users"]}


def test_save_counts_for_the_author() -> None:
    """A new version the author runs counts for the author."""
    author = UserManager.create(name=unique_name("save_author"))
    name = unique_name("saved")
    skill = SkillManager.create_custom(author, name=name)
    filler = _fill(author, free_bytes=1 * _MB, free_files=100)

    def save() -> httpx.Response:
        return client.put(
            f"{API_SERVER_URL}/skills/custom/{skill.id}/bundle",
            files={
                "bundle": (
                    "bundle.zip",
                    io.BytesIO(_bundle(name, extra_bytes=2 * _MB)),
                    "application/zip",
                )
            },
            headers=_multipart_headers(author),
        )

    _assert_refused(save())
    _set_size(filler, size=0, files=0)
    response = save()
    assert response.status_code == 200, response.text


def test_already_over_user_is_not_refused() -> None:
    owner = UserManager.create(name=unique_name("over_owner"))
    over = UserManager.create(name=unique_name("over_member"))
    skill = SkillManager.create_custom(owner, name=unique_name("over"), is_public=True)
    _set_size(skill.id, size=1 * _MB)
    _fill(over, free_bytes=-1 * _MB, free_files=100)

    response = client.put(
        f"{API_SERVER_URL}/skills/{skill.id}/enabled",
        json={"enabled": True},
        headers=over.headers,
    )
    assert response.status_code == 200, response.text
