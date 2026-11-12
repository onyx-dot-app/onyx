"""The per-user skill limit on writes (G7a): 500 MB or 5,000 files.

Sizes are patched on plugin_version rows, so small real bundles stand for
large ones."""

import io
import threading
import zipfile
from collections.abc import Generator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, update

from onyx.db.engine.sql_engine import SqlEngine, get_session_with_current_tenant
from onyx.db.models import Plugin, PluginVersion
from onyx.skills.built_in import BUILT_IN_SKILLS_USAGE
from onyx.skills.limits import SKILL_WRITE_MAX_BYTES, SKILL_WRITE_MAX_FILES
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser

_MB = 1024 * 1024


@pytest.fixture(autouse=True)
def _db_access() -> Generator[None, None, None]:
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


_FILLERS: list[UUID] = []


@pytest.fixture(autouse=True)
def _empty_fillers() -> Generator[None, None, None]:
    """Users near the limit would make later company-wide changes fail."""
    yield
    while _FILLERS:
        _set_size(_FILLERS.pop(), size=0, files=0)


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


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
    skill = SkillManager.create_custom(user, name=_name("filler"))
    _set_size(
        skill.id,
        size=SKILL_WRITE_MAX_BYTES - BUILT_IN_SKILLS_USAGE.bytes - free_bytes,
        files=SKILL_WRITE_MAX_FILES - BUILT_IN_SKILLS_USAGE.files - free_files,
    )
    _FILLERS.append(skill.id)
    return skill.id


def _share(
    user: DATestUser, skill_id: UUID | str, body: dict[str, Any]
) -> httpx.Response:
    return client.patch(
        f"{API_SERVER_URL}/skills/custom/{skill_id}/share",
        json=body,
        headers=user.headers,
    )


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


def _assert_refused(response: httpx.Response, users_over: int) -> dict[str, Any]:
    assert response.status_code == 413, response.text
    body = response.json()
    assert body["error_code"] == "SKILL_LIMIT_EXCEEDED"
    limit = body["skill_limit"]
    assert limit["users_over"] == users_over
    assert limit["max_bytes"] == SKILL_WRITE_MAX_BYTES
    assert limit["max_files"] == SKILL_WRITE_MAX_FILES
    return limit


def _custom_names(user: DATestUser) -> set[str]:
    return {skill.name for skill in SkillManager.list_for_user(user).customs}


def test_upload_refused_past_500_mb() -> None:
    user = UserManager.create(name=_name("limit_bytes"))
    filler = _fill(user, free_bytes=10, free_files=100)

    name = _name("too-big")
    limit = _assert_refused(_upload(user, _bundle(name, extra_bytes=64), name), 1)
    assert limit["usage"]["bytes"] > SKILL_WRITE_MAX_BYTES
    assert name not in _custom_names(user)

    # With room, the same upload is allowed.
    _set_size(filler, size=0, files=0)
    response = _upload(user, _bundle(name, extra_bytes=64), name)
    assert response.status_code == 200, response.text


def test_upload_refused_past_5000_files() -> None:
    user = UserManager.create(name=_name("limit_files"))
    _fill(user, free_bytes=10 * _MB, free_files=0)

    name = _name("one-file-too-many")
    limit = _assert_refused(_upload(user, _bundle(name), name), 1)
    assert limit["usage"]["files"] == SKILL_WRITE_MAX_FILES + 1
    assert name not in _custom_names(user)


def test_batch_upload_reports_limit_per_skill() -> None:
    user = UserManager.create(name=_name("limit_batch"))
    _fill(user, free_bytes=10, free_files=100)

    name = _name("batch-too-big")
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
    owner = UserManager.create(name=_name("toggle_owner"))
    user = UserManager.create(name=_name("toggle_user"))
    skill = SkillManager.create_custom(owner, name=_name("toggle"), is_public=True)
    _set_size(skill.id, size=5 * _MB)
    _fill(user, free_bytes=1 * _MB, free_files=100)

    response = client.put(
        f"{API_SERVER_URL}/skills/{skill.id}/enabled",
        json={"enabled": True},
        headers=user.headers,
    )
    limit = _assert_refused(response, 1)
    assert limit["usage"]["bytes"] > SKILL_WRITE_MAX_BYTES


def test_required_group_setting_refused_for_one_member(
    admin_user: DATestUser,
) -> None:
    author = UserManager.create(name=_name("req_author"))
    full = UserManager.create(name=_name("req_full"))
    roomy = UserManager.create(name=_name("req_roomy"))
    group = UserGroupManager.create(
        admin_user, name=_name("req-group"), user_ids=[full.id, roomy.id]
    )
    skill = SkillManager.create_custom(author, name=_name("req"))
    _set_size(skill.id, size=10 * _MB)
    _fill(full, free_bytes=5 * _MB, free_files=100)

    response = _share(admin_user, skill.id, _group_share(group.id, "REQUIRED"))
    limit = _assert_refused(response, 1)
    # An admin is not one of the users who go over.
    assert limit["usage"] is None
    assert skill.name not in _custom_names(roomy)

    # Installed by default turns it on too, so it is refused as well.
    _assert_refused(_share(admin_user, skill.id, _group_share(group.id, "DEFAULT")), 1)

    # Available gives access only: nobody has it until they turn it on.
    _share(admin_user, skill.id, _group_share(group.id, "AVAILABLE")).raise_for_status()
    assert skill.name in _custom_names(roomy)


def test_concurrent_admin_changes_one_refused(admin_user: DATestUser) -> None:
    author = UserManager.create(name=_name("conc_author"))
    member = UserManager.create(name=_name("conc_member"))
    group = UserGroupManager.create(
        admin_user, name=_name("conc-group"), user_ids=[member.id]
    )
    first = SkillManager.create_custom(author, name=_name("conc-a"))
    second = SkillManager.create_custom(author, name=_name("conc-b"))
    _set_size(first.id, size=10 * _MB)
    _set_size(second.id, size=10 * _MB)
    # Room for one of the two skills, not both.
    _fill(member, free_bytes=15 * _MB, free_files=100)

    responses: list[httpx.Response] = []
    barrier = threading.Barrier(2)

    def share(skill_id: UUID) -> None:
        barrier.wait()
        responses.append(
            _share(admin_user, skill_id, _group_share(group.id, "REQUIRED"))
        )

    threads = [
        threading.Thread(target=share, args=(skill_id,))
        for skill_id in (first.id, second.id)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200, 413], [response.text for response in responses]


def test_save_on_published_skill_counts_for_share_recipients_only(
    admin_user: DATestUser,
) -> None:
    author = UserManager.create(name=_name("pub_author"))
    recipient = UserManager.create(name=_name("pub_recipient"))
    org_only = UserManager.create(name=_name("pub_org_only"))
    name = _name("published")
    skill = SkillManager.create_custom(author, name=name, is_public=True)
    _share(
        author,
        skill.id,
        {"user_shares": [{"user_id": recipient.id, "permission": "VIEWER"}]},
    ).raise_for_status()
    _share(admin_user, skill.id, {"installation_policy": "DEFAULT"}).raise_for_status()
    assert name in _custom_names(org_only)
    assert name in _custom_names(recipient)

    recipient_filler = _fill(recipient, free_bytes=1 * _MB, free_files=100)
    _fill(org_only, free_bytes=1 * _MB, free_files=100)

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

    # The recipient runs the current version, so the save counts for them.
    _assert_refused(save(), 1)

    # With room for the recipient, the save passes. The organization-only
    # user runs the published version, so the larger draft does not count.
    _set_size(recipient_filler, size=0, files=0)
    response = save()
    assert response.status_code == 200, response.text


def test_already_over_user_is_not_refused(admin_user: DATestUser) -> None:
    author = UserManager.create(name=_name("over_author"))
    over = UserManager.create(name=_name("over_member"))
    group = UserGroupManager.create(
        admin_user, name=_name("over-group"), user_ids=[over.id]
    )
    skill = SkillManager.create_custom(author, name=_name("over"))
    _set_size(skill.id, size=1 * _MB)
    _fill(over, free_bytes=-1 * _MB, free_files=100)

    _share(admin_user, skill.id, _group_share(group.id, "REQUIRED")).raise_for_status()
    assert skill.name in _custom_names(over)


def test_inactive_user_is_ignored(admin_user: DATestUser) -> None:
    author = UserManager.create(name=_name("inactive_author"))
    inactive = UserManager.create(name=_name("inactive_member"))
    group = UserGroupManager.create(
        admin_user, name=_name("inactive-group"), user_ids=[inactive.id]
    )
    skill = SkillManager.create_custom(author, name=_name("inactive"))
    _set_size(skill.id, size=10 * _MB)
    _fill(inactive, free_bytes=1 * _MB, free_files=100)
    UserManager.set_status(inactive, False, admin_user)

    _share(admin_user, skill.id, _group_share(group.id, "REQUIRED")).raise_for_status()
