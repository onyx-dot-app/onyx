"""Each change to a custom skill's files adds one immutable plugin version.

The API has no plugin reads yet, so these tests read the plugin rows from the
database after each request."""

import hashlib
import io
import json
import threading
import zipfile
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from onyx.db.engine.sql_engine import SqlEngine, get_session_with_current_tenant
from onyx.db.enums import MarketplaceKind
from onyx.db.models import (
    Marketplace,
    Plugin,
    PluginSkill,
    PluginVersion,
    Skill,
    User,
)
from onyx.db.plugin import version_is_skill
from onyx.server.features.skill.response_helpers import skill_response_for_user
from onyx.skills.bundle import SKILL_MD_MAX_BYTES
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser

_ORGANIZATION_LIBRARY_ID = UUID("00000000-0000-4000-8000-00000000011b")


@pytest.fixture(autouse=True)
def _db_access() -> Generator[None, None, None]:
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@pytest.fixture
def user() -> DATestUser:
    return UserManager.create(name=f"plugin_versions_{uuid4().hex[:8]}")


# --- Bundles -----------------------------------------------------------------


def _skill_md(name: str, description: str, body: str = "Do the work.") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n"


def _bundle(files: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


def _manifest(files: dict[str, str | bytes]) -> list[dict[str, Any]]:
    entries = []
    for path, content in files.items():
        data = content.encode() if isinstance(content, str) else content
        entries.append(
            {
                "path": path,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return sorted(entries, key=lambda entry: entry["path"])


# --- Requests ----------------------------------------------------------------


def _multipart_headers(user: DATestUser) -> dict[str, str]:
    headers = dict(user.headers)
    headers.pop("Content-Type", None)
    return headers


def _upload(
    user: DATestUser, bundle: bytes, *, name: str, auto_enable: bool = True
) -> dict[str, Any]:
    response = client.post(
        f"{API_SERVER_URL}/skills/custom",
        files={
            "auto_enable": (None, str(auto_enable).lower(), None),
            "bundle": (f"{name}.zip", io.BytesIO(bundle), "application/zip"),
        },
        headers=_multipart_headers(user),
    )
    response.raise_for_status()
    return response.json()


def _create_from_editor(
    user: DATestUser, name: str, *, public: bool = False
) -> dict[str, Any]:
    files: dict[str, tuple[str | None, object, str | None]] = {
        "name": (None, name, None),
        "description": (None, "Editor description", None),
        "instructions_markdown": (None, "Editor instructions.", None),
        "auto_enable": (None, "false", None),
    }
    if public:
        files["sharing"] = (None, json.dumps({"public_permission": "VIEWER"}), None)
    response = client.post(
        f"{API_SERVER_URL}/skills/custom/editor",
        files=files,
        headers=_multipart_headers(user),
    )
    response.raise_for_status()
    return response.json()


def _patch(
    user: DATestUser,
    skill_id: str,
    body: dict[str, Any],
) -> httpx.Response:
    return client.patch(
        f"{API_SERVER_URL}/skills/custom/{skill_id}",
        json=body,
        headers=user.headers,
    )


def _replace(
    user: DATestUser,
    skill_id: str,
    bundle: bytes,
    base_version_id: str | None = None,
) -> httpx.Response:
    files: dict[str, tuple[str | None, object, str | None]] = {
        "bundle": ("bundle.zip", io.BytesIO(bundle), "application/zip")
    }
    if base_version_id is not None:
        files["base_version_id"] = (None, base_version_id, None)
    return client.put(
        f"{API_SERVER_URL}/skills/custom/{skill_id}/bundle",
        files=files,
        headers=_multipart_headers(user),
    )


def _add_file(
    user: DATestUser,
    skill_id: str,
    filename: str,
    content: bytes,
    base_version_id: str | None = None,
) -> httpx.Response:
    files: dict[str, tuple[str | None, object, str | None]] = {
        "upload": (filename, io.BytesIO(content), "application/octet-stream")
    }
    if base_version_id is not None:
        files["base_version_id"] = (None, base_version_id, None)
    return client.post(
        f"{API_SERVER_URL}/skills/custom/{skill_id}/files",
        files=files,
        headers=_multipart_headers(user),
    )


def _remove_file(
    user: DATestUser, skill_id: str, path: str, base_version_id: str | None = None
) -> httpx.Response:
    params = {"path": path}
    if base_version_id is not None:
        params["base_version_id"] = base_version_id
    return client.delete(
        f"{API_SERVER_URL}/skills/custom/{skill_id}/files",
        params=params,
        headers=user.headers,
    )


# --- Database reads ----------------------------------------------------------


@dataclass(frozen=True)
class _Version:
    id: UUID
    number: int
    bundle_file_id: str | None
    bundle_sha256: str | None
    is_valid: bool | None
    file_manifest: list[dict[str, Any]] | None
    unpacked_size_bytes: int | None
    file_count: int | None
    created_by_user_id: UUID | None
    created_by_email: str | None
    # (path, frontmatter name, skill_md, frontmatter) of each skill.
    skills: list[tuple[str, str, str | None, dict[str, Any]]]


@dataclass(frozen=True)
class _State:
    plugin_name: str
    plugin_description: str
    is_skill: bool
    marketplace_id: UUID
    marketplace_kind: MarketplaceKind
    author_user_id: UUID | None
    current_version_id: UUID
    published_version_id: UUID | None
    versions: list[_Version]
    skill_bundle_file_id: str | None
    skill_bundle_sha256: str | None
    skill_name: str
    skill_description: str
    skill_is_valid: bool | None

    @property
    def current(self) -> _Version:
        return next(v for v in self.versions if v.id == self.current_version_id)


def _state(skill_id: str | UUID) -> _State:
    with get_session_with_current_tenant() as db_session:
        plugin = db_session.get(Plugin, UUID(str(skill_id)))
        assert plugin is not None
        skill = db_session.get(Skill, plugin.id)
        assert skill is not None
        marketplace = db_session.get(Marketplace, plugin.marketplace_id)
        assert marketplace is not None
        versions = []
        for version in db_session.scalars(
            select(PluginVersion)
            .where(PluginVersion.plugin_id == plugin.id)
            .order_by(PluginVersion.version_number)
        ):
            skills = [
                (row.path, row.frontmatter["name"], row.skill_md, row.frontmatter)
                for row in db_session.scalars(
                    select(PluginSkill).where(
                        PluginSkill.plugin_version_id == version.id
                    )
                )
            ]
            versions.append(
                _Version(
                    id=version.id,
                    number=version.version_number,
                    bundle_file_id=version.bundle_file_id,
                    bundle_sha256=version.bundle_sha256,
                    is_valid=version.is_valid,
                    file_manifest=version.file_manifest,
                    unpacked_size_bytes=version.unpacked_size_bytes,
                    file_count=version.file_count,
                    created_by_user_id=version.created_by_user_id,
                    created_by_email=version.created_by_email,
                    skills=skills,
                )
            )
        return _State(
            plugin_name=plugin.name,
            plugin_description=plugin.description,
            is_skill=version_is_skill(plugin.current_version_id, db_session),
            marketplace_id=plugin.marketplace_id,
            marketplace_kind=marketplace.kind,
            author_user_id=plugin.author_user_id,
            current_version_id=plugin.current_version_id,
            published_version_id=plugin.published_version_id,
            versions=versions,
            skill_bundle_file_id=skill.bundle_file_id,
            skill_bundle_sha256=skill.bundle_sha256,
            skill_name=skill.name,
            skill_description=skill.description,
            skill_is_valid=skill.is_valid,
        )


def _user_uploads_id(user_id: str) -> UUID:
    return UUID(hashlib.md5(f"user_uploads:{user_id}".encode()).hexdigest())


def _assert_legacy_matches_current(state: _State) -> None:
    current = state.current
    assert state.skill_bundle_file_id == current.bundle_file_id
    assert state.skill_bundle_sha256 == current.bundle_sha256
    assert state.skill_is_valid == current.is_valid
    assert state.skill_name == current.skills[0][1]
    assert state.skill_description == state.plugin_description


# --- Tests -------------------------------------------------------------------


def test_upload_creates_plugin_version_1(user: DATestUser) -> None:
    name = f"upload-{uuid4().hex[:8]}"
    files: dict[str, str | bytes] = {
        "SKILL.md": _skill_md(name, "Uploaded description"),
        "scripts/run.py": "print('hi')\n",
    }
    response = _upload(user, _bundle(files), name=name)

    state = _state(response["id"])
    assert state.is_skill
    assert state.plugin_name == name
    assert state.plugin_description == "Uploaded description"
    assert state.marketplace_id == _user_uploads_id(user.id)
    assert state.marketplace_kind == MarketplaceKind.USER_UPLOADS
    assert state.author_user_id == UUID(user.id)
    assert state.published_version_id is None
    assert [v.number for v in state.versions] == [1]
    assert str(state.current_version_id) == response["current_version_id"]

    version = state.current
    assert version.file_manifest == _manifest(files)
    assert version.file_count == 2
    assert version.unpacked_size_bytes == sum(
        entry["size"] for entry in _manifest(files)
    )
    assert version.created_by_user_id == UUID(user.id)
    assert version.created_by_email == user.email
    assert version.skills == [
        (
            "",
            name,
            files["SKILL.md"],
            {"name": name, "description": "Uploaded description"},
        )
    ]
    _assert_legacy_matches_current(state)


def test_editor_and_batch_create_make_plugins(user: DATestUser) -> None:
    editor_name = f"editor-{uuid4().hex[:8]}"
    created = _create_from_editor(user, editor_name)
    state = _state(created["id"])
    assert [v.number for v in state.versions] == [1]
    assert state.current.skills[0][1] == editor_name
    assert state.current.file_manifest is not None
    _assert_legacy_matches_current(state)

    names = [f"batch-{uuid4().hex[:8]}" for _ in range(2)]
    response = client.post(
        f"{API_SERVER_URL}/skills/custom/batch",
        files=[
            (
                "bundles",
                (
                    f"{name}.zip",
                    io.BytesIO(_bundle({"SKILL.md": _skill_md(name, "Batch")})),
                    "application/zip",
                ),
            )
            for name in names
        ],
        headers=_multipart_headers(user),
    )
    response.raise_for_status()
    imported = response.json()["imported"]
    assert sorted(item["skill"]["name"] for item in imported) == sorted(names)
    for item in imported:
        batch_state = _state(item["skill"]["id"])
        assert [v.number for v in batch_state.versions] == [1]
        assert batch_state.marketplace_id == _user_uploads_id(user.id)
        _assert_legacy_matches_current(batch_state)


def test_each_file_change_adds_one_version(user: DATestUser) -> None:
    name = f"edits-{uuid4().hex[:8]}"
    skill = _upload(user, _bundle({"SKILL.md": _skill_md(name, "First")}), name=name)
    skill_id = skill["id"]

    edited = _patch(user, skill_id, {"description": "Second"})
    edited.raise_for_status()
    state = _state(skill_id)
    assert [v.number for v in state.versions] == [1, 2]
    assert str(state.current_version_id) == edited.json()["current_version_id"]
    assert state.plugin_description == "Second"
    assert state.current.skills[0][3] == {"name": name, "description": "Second"}
    _assert_legacy_matches_current(state)

    _add_file(user, skill_id, "notes.txt", b"notes").raise_for_status()
    state = _state(skill_id)
    assert [v.number for v in state.versions] == [1, 2, 3]
    assert state.current.file_count == 2
    assert [e["path"] for e in state.current.file_manifest or []] == [
        "SKILL.md",
        "notes.txt",
    ]

    _remove_file(user, skill_id, "notes.txt").raise_for_status()
    state = _state(skill_id)
    assert [v.number for v in state.versions] == [1, 2, 3, 4]
    assert state.current.file_count == 1

    _replace(
        user, skill_id, _bundle({"SKILL.md": _skill_md(name, "Third")})
    ).raise_for_status()
    state = _state(skill_id)
    assert [v.number for v in state.versions] == [1, 2, 3, 4, 5]
    assert state.plugin_description == "Third"
    _assert_legacy_matches_current(state)

    # Every version keeps its own bundle, and the skill id never changed.
    bundle_ids = [v.bundle_file_id for v in state.versions]
    assert len(set(bundle_ids)) == 5
    assert all(v.skills[0][1] == name for v in state.versions)
    assert state.published_version_id is None


def test_unchanged_editor_save_adds_no_version(user: DATestUser) -> None:
    name = f"unchanged-{uuid4().hex[:8]}"
    skill = _upload(user, _bundle({"SKILL.md": _skill_md(name, "Same")}), name=name)
    skill_id = skill["id"]
    body = {"description": "Same edited", "instructions_markdown": "Same body."}

    _patch(user, skill_id, body).raise_for_status()
    first = _state(skill_id)
    assert len(first.versions) == 2

    again = _patch(user, skill_id, body)
    again.raise_for_status()
    second = _state(skill_id)
    assert second.versions == first.versions
    assert second.skill_bundle_file_id == first.skill_bundle_file_id
    assert again.json()["current_version_id"] == str(first.current_version_id)

    _add_file(user, skill_id, "notes.txt", b"notes").raise_for_status()
    _add_file(user, skill_id, "notes.txt", b"notes").raise_for_status()
    assert len(_state(skill_id).versions) == 3


def test_same_zip_upload_adds_a_version(user: DATestUser) -> None:
    name = f"same-zip-{uuid4().hex[:8]}"
    bundle = _bundle({"SKILL.md": _skill_md(name, "Same zip")})
    skill = _upload(user, bundle, name=name)

    _replace(user, skill["id"], bundle).raise_for_status()
    _replace(user, skill["id"], bundle).raise_for_status()
    state = _state(skill["id"])
    assert [v.number for v in state.versions] == [1, 2, 3]
    assert len({v.bundle_sha256 for v in state.versions}) == 1
    _assert_legacy_matches_current(state)


def test_stale_base_version_gets_409(user: DATestUser) -> None:
    name = f"stale-{uuid4().hex[:8]}"
    skill = _upload(user, _bundle({"SKILL.md": _skill_md(name, "v1")}), name=name)
    skill_id = skill["id"]
    first_version = skill["current_version_id"]

    fresh = _patch(
        user, skill_id, {"description": "v2", "base_version_id": first_version}
    )
    fresh.raise_for_status()
    second_version = fresh.json()["current_version_id"]
    assert second_version != first_version

    stale_requests = [
        _patch(user, skill_id, {"description": "v3", "base_version_id": first_version}),
        _replace(
            user, skill_id, _bundle({"SKILL.md": _skill_md(name, "v3")}), first_version
        ),
        _add_file(user, skill_id, "notes.txt", b"notes", first_version),
    ]
    for response in stale_requests:
        assert response.status_code == 409, response.text
        assert response.json()["error_code"] == "PLUGIN_VERSION_STALE"

    _add_file(user, skill_id, "notes.txt", b"notes", second_version).raise_for_status()
    third_version = str(_state(skill_id).current_version_id)
    stale_remove = _remove_file(user, skill_id, "notes.txt", second_version)
    assert stale_remove.status_code == 409
    assert stale_remove.json()["error_code"] == "PLUGIN_VERSION_STALE"

    state = _state(skill_id)
    assert [v.number for v in state.versions] == [1, 2, 3]
    assert str(state.current_version_id) == third_version
    assert state.skill_description == "v2"
    _assert_legacy_matches_current(state)


def test_response_version_id_matches_the_files_it_shows(user: DATestUser) -> None:
    name = f"snapshot-{uuid4().hex[:8]}"
    skill = _upload(user, _bundle({"SKILL.md": _skill_md(name, "v1")}), name=name)
    first_version = skill["current_version_id"]

    with get_session_with_current_tenant() as db_session:
        # A response that loaded the skill row before another save commits
        # shows version 1, so it must return version 1 as the edit base.
        loaded = db_session.get(Skill, UUID(skill["id"]))
        db_user = db_session.get(User, UUID(user.id))
        assert loaded is not None and db_user is not None
        _patch(user, skill["id"], {"description": "v2"}).raise_for_status()
        response = skill_response_for_user(loaded, db_user, db_session)

    assert str(response.current_version_id) == first_version
    assert _state(skill["id"]).current.number == 2


def test_save_on_published_plugin_moves_both_pointers(user: DATestUser) -> None:
    name = f"published-{uuid4().hex[:8]}"
    created = _create_from_editor(user, name, public=True)
    state = _state(created["id"])
    assert state.marketplace_id == _ORGANIZATION_LIBRARY_ID
    assert state.published_version_id == state.current_version_id

    _patch(user, created["id"], {"description": "Published edit"}).raise_for_status()
    state = _state(created["id"])
    assert len(state.versions) == 2
    assert state.current.number == 2
    assert state.published_version_id == state.current_version_id


def test_save_on_private_plugin_keeps_published_pointer(user: DATestUser) -> None:
    name = f"private-{uuid4().hex[:8]}"
    created = _create_from_editor(user, name)
    _patch(user, created["id"], {"description": "Private edit"}).raise_for_status()
    state = _state(created["id"])
    assert state.current.number == 2
    assert state.published_version_id is None


def _assert_skill_md_refused(response: Any) -> None:
    assert response.status_code == 413
    body = response.json()
    assert body["limit"] == "skill_md_bytes"
    assert body["limit_value"] == SKILL_MD_MAX_BYTES
    assert "Split it into several files" in body["detail"]


def test_skill_md_over_limit_is_refused(user: DATestUser) -> None:
    name = f"large-{uuid4().hex[:8]}"
    large_body = "x" * SKILL_MD_MAX_BYTES
    large_bundle = _bundle({"SKILL.md": _skill_md(name, "Large", large_body)})

    upload = client.post(
        f"{API_SERVER_URL}/skills/custom",
        files={"bundle": (f"{name}.zip", io.BytesIO(large_bundle), "application/zip")},
        headers=_multipart_headers(user),
    )
    _assert_skill_md_refused(upload)

    batch = client.post(
        f"{API_SERVER_URL}/skills/custom/batch",
        files=[
            ("bundles", (f"{name}.zip", io.BytesIO(large_bundle), "application/zip"))
        ],
        headers=_multipart_headers(user),
    )
    batch.raise_for_status()
    assert batch.json()["imported"] == []
    [not_imported] = batch.json()["not_imported"]
    assert "Split it into several files" in not_imported["reason"]

    # Edits of a saved skill are refused too and add no version.
    skill = _upload(user, _bundle({"SKILL.md": _skill_md(name, "Small")}), name=name)
    _assert_skill_md_refused(
        _patch(user, skill["id"], {"instructions_markdown": large_body})
    )
    _assert_skill_md_refused(_replace(user, skill["id"], large_bundle))
    assert [v.number for v in _state(skill["id"]).versions] == [1]


def test_skill_md_with_nul_is_refused(user: DATestUser) -> None:
    name = f"nul-{uuid4().hex[:8]}"
    nul_bundle = _bundle({"SKILL.md": _skill_md(name, "Nul", "Before\x00after.")})

    upload = client.post(
        f"{API_SERVER_URL}/skills/custom",
        files={"bundle": (f"{name}.zip", io.BytesIO(nul_bundle), "application/zip")},
        headers=_multipart_headers(user),
    )
    assert upload.status_code == 400, upload.text
    assert "NUL character" in upload.json()["detail"]

    skill = _upload(user, _bundle({"SKILL.md": _skill_md(name, "Clean")}), name=name)
    replace = _replace(user, skill["id"], nul_bundle)
    assert replace.status_code == 400, replace.text
    assert "NUL character" in replace.json()["detail"]
    assert [v.number for v in _state(skill["id"]).versions] == [1]


def test_frontmatter_matches_skill_md(user: DATestUser) -> None:
    name = f"frontmatter-{uuid4().hex[:8]}"
    skill_md = (
        f"---\nname: {name}\ndescription: Dated\nallowed-tools: Bash\n"
        "released: 2024-01-02\ntags: [a, 1]\n---\n\nBody.\n"
    )
    skill = _upload(user, _bundle({"SKILL.md": skill_md}), name=name)
    assert _state(skill["id"]).current.skills[0][3] == {
        "name": name,
        "description": "Dated",
        "allowed-tools": "Bash",
        "released": "2024-01-02",
        "tags": ["a", 1],
    }


@pytest.mark.parametrize(
    "extra",
    [
        "score: .nan",
        "limit: .inf",
        'nul: "a\\0b"',
        'surrogate: "\\ud800"',
        "blob: !!binary aGk=",
        "big: " + "9" * 5000,
    ],
)
def test_frontmatter_value_jsonb_cannot_hold_is_dropped(
    user: DATestUser, extra: str
) -> None:
    name = f"unsafe-{uuid4().hex[:8]}"
    skill_md = (
        f"---\nname: {name}\ndescription: Unsafe\nallowed-tools: Bash\n{extra}\n"
        "---\n\nBody.\n"
    )
    skill = _upload(user, _bundle({"SKILL.md": skill_md}), name=name)

    current = _state(skill["id"]).current
    kept = {"name": name, "description": "Unsafe", "allowed-tools": "Bash"}
    assert current.skills == [("", name, skill_md, kept)]

    # The editor rewrites the frontmatter and still saves.
    _patch(user, skill["id"], {"description": "Edited"}).raise_for_status()
    edited = _state(skill["id"]).current
    assert edited.number == 2
    assert edited.skills[0][3] == {**kept, "description": "Edited"}


def test_new_version_with_another_skill_name_is_refused(user: DATestUser) -> None:
    name = f"named-{uuid4().hex[:8]}"
    skill = _upload(user, _bundle({"SKILL.md": _skill_md(name, "Named")}), name=name)
    renamed = _bundle({"SKILL.md": _skill_md(f"{name}-other", "Renamed")})

    response = _replace(user, skill["id"], renamed)
    assert response.status_code == 400
    assert len(_state(skill["id"]).versions) == 1


def test_second_skill_with_a_used_name_gets_a_free_plugin_name(
    user: DATestUser,
) -> None:
    name = f"deploy-{uuid4().hex[:8]}"
    first = _upload(user, _bundle({"SKILL.md": _skill_md(name, "First")}), name=name)
    second = _upload(
        user,
        _bundle({"SKILL.md": _skill_md(name, "Second")}),
        name=name,
        auto_enable=False,
    )

    first_state = _state(first["id"])
    second_state = _state(second["id"])
    assert first_state.plugin_name == name
    assert second_state.plugin_name == f"{name}-2"
    assert second_state.skill_name == name
    assert second_state.current.skills[0][1] == name
    assert second_state.marketplace_id == first_state.marketplace_id


def test_concurrent_first_uploads_share_my_uploads() -> None:
    user = UserManager.create(name=f"concurrent_{uuid4().hex[:8]}")
    names = [f"race-{uuid4().hex[:8]}" for _ in range(4)]
    results: dict[str, dict[str, Any]] = {}
    errors: list[BaseException] = []

    def upload(name: str) -> None:
        try:
            results[name] = _upload(
                user,
                _bundle({"SKILL.md": _skill_md(name, "Race")}),
                name=name,
                auto_enable=False,
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=upload, args=(name,)) for name in names]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    marketplace_ids = {_state(skill["id"]).marketplace_id for skill in results.values()}
    assert marketplace_ids == {_user_uploads_id(user.id)}
    with get_session_with_current_tenant() as db_session:
        owned = db_session.scalars(
            select(Marketplace.id).where(
                Marketplace.owner_user_id == UUID(user.id),
                Marketplace.kind == MarketplaceKind.USER_UPLOADS,
            )
        ).all()
    assert len(owned) == 1


def test_delete_removes_the_plugin(user: DATestUser) -> None:
    name = f"deleted-{uuid4().hex[:8]}"
    skill = _upload(user, _bundle({"SKILL.md": _skill_md(name, "Gone")}), name=name)
    _patch(user, skill["id"], {"description": "Edited"}).raise_for_status()

    client.delete(
        f"{API_SERVER_URL}/skills/custom/{skill['id']}", headers=user.headers
    ).raise_for_status()
    with get_session_with_current_tenant() as db_session:
        assert db_session.get(Plugin, UUID(skill["id"])) is None
        assert (
            db_session.scalar(
                select(PluginVersion.id).where(
                    PluginVersion.plugin_id == UUID(skill["id"])
                )
            )
            is None
        )


def _drop_plugin(skill_id: str) -> None:
    """Leave the skill with no plugin row, as an older server or a user
    delete of a stale copy does."""
    with get_session_with_current_tenant() as db_session:
        plugin = db_session.get(Plugin, UUID(skill_id))
        assert plugin is not None
        db_session.delete(plugin)
        db_session.commit()


@pytest.mark.parametrize("change", ["patch", "replace", "add_file"])
def test_save_on_skill_without_plugin_row_converges(
    user: DATestUser, change: str
) -> None:
    name = f"no-plugin-{uuid4().hex[:8]}"
    skill = _upload(user, _bundle({"SKILL.md": _skill_md(name, "Before")}), name=name)
    legacy_bundle = _state(skill["id"]).skill_bundle_file_id
    _drop_plugin(skill["id"])

    if change == "patch":
        response = _patch(user, skill["id"], {"description": "After"})
    elif change == "replace":
        response = _replace(
            user, skill["id"], _bundle({"SKILL.md": _skill_md(name, "After")})
        )
    else:
        response = _add_file(user, skill["id"], "notes.txt", b"notes")
    response.raise_for_status()

    state = _state(skill["id"])
    assert [v.number for v in state.versions] == [1, 2]
    legacy_version, new_version = state.versions
    assert legacy_version.bundle_file_id == legacy_bundle
    assert legacy_version.file_manifest is None
    assert legacy_version.skills[0][1] == name
    assert state.current_version_id == new_version.id
    assert new_version.file_manifest is not None
    assert response.json()["current_version_id"] == str(new_version.id)
    assert state.marketplace_id == _user_uploads_id(user.id)
    _assert_legacy_matches_current(state)


def test_unchanged_save_on_skill_without_plugin_row_adds_only_version_1(
    user: DATestUser,
) -> None:
    name = f"no-plugin-same-{uuid4().hex[:8]}"
    skill = _upload(user, _bundle({"SKILL.md": _skill_md(name, "Same")}), name=name)
    _patch(user, skill["id"], {"description": "Same"}).raise_for_status()
    _drop_plugin(skill["id"])

    _patch(user, skill["id"], {"description": "Same"}).raise_for_status()
    state = _state(skill["id"])
    assert [v.number for v in state.versions] == [1]
    assert state.current.bundle_file_id == state.skill_bundle_file_id
