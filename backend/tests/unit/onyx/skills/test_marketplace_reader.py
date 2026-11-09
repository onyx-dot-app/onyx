import gzip
import io
import json
import os
import random
import stat
import struct
import subprocess
import sys
import tarfile
import zipfile

import pytest
from pydantic import JsonValue

from onyx.skills import bundle as bundles
from onyx.skills.marketplace import archive as archives
from onyx.skills.marketplace import reader
from onyx.skills.marketplace.read_models import (
    BlockedSkill,
    CompleteMarketplace,
    FailedMarketplace,
    ReadySkill,
    UnsupportedPlugin,
)
from onyx.utils.bundle import compute_bundle_metadata
from tests.unit.onyx.skills.marketplace_fixtures import (
    CLAUDE,
    CODEX,
    _archive,
    _catalog,
    _files,
    _md,
)


def _entries(
    files: dict[str, bytes], kind: str = "zip"
) -> tuple[ReadySkill | BlockedSkill | UnsupportedPlugin, ...]:
    result = reader.read_marketplace_archive(_archive(files, kind))
    assert isinstance(result, CompleteMarketplace), result
    return result.entries


@pytest.mark.parametrize("kind", ["zip", "tar"])
@pytest.mark.parametrize("manifest", [CLAUDE, CODEX])
@pytest.mark.parametrize("wrapper", ["", "repo-commit/"])
def test_formats_and_folder_scope(kind: str, manifest: str, wrapper: str) -> None:
    source: JsonValue = (
        "./" if manifest == CLAUDE else {"source": "local", "path": "./"}
    )
    files = {
        f"team/{manifest}": _catalog(source=source),
        "team/skills/hello/SKILL.md": _md(),
        "other/SKILL.md": _md("other"),
    }
    result = reader.read_marketplace_archive(_archive(files, kind, wrapper), "team")
    assert isinstance(result, CompleteMarketplace)
    assert isinstance(result.entries, tuple)
    assert [e.entry_key for e in result.entries] == ["tools/hello"]
    assert isinstance(result.entries[0], ReadySkill)
    assert result.entries[0].path == "team/skills/hello"
    assert isinstance(
        reader.read_marketplace_archive(_archive(files, kind, wrapper), "missing"),
        FailedMarketplace,
    )


@pytest.mark.parametrize(
    "manifest",
    [
        b"{",
        b"[]",
        b"{}",
        b'{"name":"m","plugins":null}',
        b'{"name":"m","plugins":[],"plugins":[]}',
        b'{"name":"m","plugins":[],"metadata":null}',
        b'{"name":"m","plugins":[],"metadata":[]}',
        b'{"name":"m","plugins":[],"metadata":"plugins"}',
        b'{"name":"m","plugins":[],"metadata":false}',
        b'{"name":"m","plugins":[],"metadata":0}',
    ],
)
def test_bad_manifest_never_falls_back(manifest: bytes) -> None:
    files = _files()
    files[CODEX] = files[CLAUDE]
    files[CLAUDE] = manifest
    assert isinstance(
        reader.read_marketplace_archive(_archive(files)), FailedMarketplace
    )


def test_absent_manifest_and_precedence() -> None:
    assert isinstance(
        reader.read_marketplace_archive(_archive({"skills/hello/SKILL.md": _md()})),
        FailedMarketplace,
    )
    files = _files(skills=[])
    files[CODEX] = _catalog()
    assert _entries(files) == ()
    del files[CLAUDE]
    assert isinstance(_entries(files)[0], ReadySkill)


def test_explicit_official_anthropic_shape_and_determinism() -> None:
    # anthropics/skills .claude-plugin/marketplace.json: source './', strict false, skills list.
    files = _files(
        name="document-skills", source="./", strict=False, skills=["./skills/hello"]
    )
    files.update(
        {
            "skills/hello/scripts/a.py": b"print('hello')",
            "skills/stray/SKILL.md": _md("stray"),
            "skills/hello/.DS_Store": b"ignored",
        }
    )
    first = _entries(files)[0]
    second = _entries(dict(reversed(list(files.items()))), "tar")[0]
    assert isinstance(first, ReadySkill) and first == second
    assert first.entry_key == "document-skills/hello"
    assert (
        first.content_digest
        == compute_bundle_metadata(first.bundle_bytes).content_digest
    )
    with zipfile.ZipFile(io.BytesIO(first.bundle_bytes)) as archive:
        assert archive.namelist() == ["SKILL.md", "scripts/a.py"]
        assert all(
            info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist()
        )
    files["skills/hello/scripts/a.py"] += b"\n"
    assert _entries(files)[0] != first


@pytest.mark.parametrize(
    "component", ["mcpServers", "hooks", "agents", "commands", "apps"]
)
@pytest.mark.parametrize(
    "location", ["entry", ".claude-plugin/plugin.json", ".codex-plugin/plugin.json"]
)
def test_mixed_plugins_are_not_partially_extracted(
    component: str, location: str
) -> None:
    files = _files()
    fields: dict[str, JsonValue] = {component: "./component.md"}
    files["component.md"] = b"Definition"
    if location == "entry":
        files[CLAUDE] = _catalog(**fields)
    else:
        files[location] = json.dumps({"name": "tools", **fields}).encode()
    assert isinstance(_entries(files)[0], UnsupportedPlugin)
    assert len(_entries(files)) == 1


@pytest.mark.parametrize(
    "path",
    [
        ".mcp.json",
        ".app.json",
        "hooks/hooks.json",
        "agents/worker.md",
        "commands/run.md",
    ],
)
def test_components_discovered_from_plugin_files(path: str) -> None:
    files = _files()
    files[path] = b"{}"
    assert isinstance(_entries(files)[0], UnsupportedPlugin)


@pytest.mark.parametrize("kind", ["github", "url", "git-subdir", "npm"])
def test_remote_sources_are_unsupported(kind: str) -> None:
    entries = _entries(
        _files(
            source={
                "source": kind,
                "repo": "acme/tools",
                "url": "https://example.com/tools.git",
                "path": "nested",
                "package": "tools",
            }
        )
    )
    assert isinstance(entries[0], UnsupportedPlugin) and kind in entries[0].reason


@pytest.mark.parametrize(
    "content", [b"invalid", _md("wrong"), b"---\nname: hello\n---\n"]
)
def test_invalid_skill_does_not_fail_other_entries(content: bytes) -> None:
    files = _files()
    files["skills/hello/SKILL.md"] = content
    files["skills/good/SKILL.md"] = _md("good")
    entries = _entries(files)
    assert [e.status for e in entries] == ["ok", "blocked"]
    assert entries[1].entry_key == "tools/hello"


def test_missing_declared_skill_is_blocked_and_move_keeps_identity() -> None:
    files = _files(skills=["./missing/hello"])
    assert isinstance(_entries(files)[0], BlockedSkill)
    files["missing/hello/SKILL.md"] = files.pop("skills/hello/SKILL.md")
    entry = _entries(files)[0]
    assert isinstance(entry, ReadySkill) and entry.entry_key == "tools/hello"


@pytest.mark.parametrize("field", ["source", "skills"])
@pytest.mark.parametrize(
    "path", ["../outside", "/etc", "C:/escape", "a\\b", "a/../b", "a//b", "a\x00b"]
)
def test_manifest_paths_fail_whole_read(field: str, path: str) -> None:
    files = _files(**{field: [path] if field == "skills" else path})
    assert isinstance(
        reader.read_marketplace_archive(_archive(files)), FailedMarketplace
    )


def test_duplicate_identities_and_json_failure() -> None:
    for fields in (
        {"skills": ["skills/hello", "other/hello"]},
        {"skills": ["skills/hello", "skills/hello"]},
    ):
        assert isinstance(
            reader.read_marketplace_archive(_archive(_files(**fields))),
            FailedMarketplace,
        )
    files = _files()
    files[CLAUDE] = (
        b'{"name":"test","plugins":[{"name":"p","source":"./"},{"name":"p","source":"./"}]}'
    )
    assert isinstance(
        reader.read_marketplace_archive(_archive(files)), FailedMarketplace
    )
    files = _files()
    files[".claude-plugin/plugin.json"] = b"broken"
    assert isinstance(
        reader.read_marketplace_archive(_archive(files)), FailedMarketplace
    )


@pytest.mark.parametrize(
    "limit",
    [
        "DEFAULT_PER_FILE_MAX_BYTES",
        "DEFAULT_TOTAL_MAX_BYTES",
        "DEFAULT_ZIP_MAX_BYTES",
        "DEFAULT_MAX_FILE_COUNT",
    ],
)
def test_each_skill_limit_at_boundary_and_over(
    limit: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = _files()
    files["skills/hello/data"] = random.Random(1).randbytes(1000)
    entry = _entries(files)[0]
    assert isinstance(entry, ReadySkill)
    boundaries = {
        "DEFAULT_PER_FILE_MAX_BYTES": 1000,
        "DEFAULT_TOTAL_MAX_BYTES": 1000 + len(_md()),
        "DEFAULT_ZIP_MAX_BYTES": len(entry.bundle_bytes),
        "DEFAULT_MAX_FILE_COUNT": 2,
    }
    monkeypatch.setattr(bundles, limit, boundaries[limit])
    assert isinstance(_entries(files)[0], ReadySkill)
    monkeypatch.setattr(bundles, limit, boundaries[limit] - 1)
    files["skills/good/SKILL.md"] = _md("good")
    entries = _entries(files)
    assert [e.status for e in entries] == ["ok", "blocked"]


def test_ignored_entries_count_and_unrelated_large_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bundles, "DEFAULT_MAX_FILE_COUNT", 1)
    monkeypatch.setattr(bundles, "DEFAULT_PER_FILE_MAX_BYTES", 1024)
    files = _files()
    files["unrelated"] = b"0" * 4096
    assert isinstance(_entries(files)[0], ReadySkill)
    files["skills/hello/.DS_Store"] = b"ignored"
    assert isinstance(_entries(files)[0], BlockedSkill)


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_archive_and_skill_count_boundaries(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = _files()
    data = _archive(files, kind)
    for setting, boundary in [
        ("ARCHIVE_MAX_BYTES", len(data)),
        ("ARCHIVE_MAX_ENTRIES", 2),
        ("GITHUB_SKILL_MAX_COUNT", 1),
    ]:
        with monkeypatch.context() as patch:
            patch.setattr(
                reader if setting == "GITHUB_SKILL_MAX_COUNT" else archives,
                setting,
                boundary,
            )
            assert isinstance(
                reader.read_marketplace_archive(data), CompleteMarketplace
            )
            patch.setattr(
                reader if setting == "GITHUB_SKILL_MAX_COUNT" else archives,
                setting,
                boundary - 1,
            )
            assert isinstance(reader.read_marketplace_archive(data), FailedMarketplace)


def test_bad_archives_and_compressed_bomb(monkeypatch: pytest.MonkeyPatch) -> None:
    for data in (b"invalid", _archive(_files())[:20], _archive(_files(), "tar")[:20]):
        assert isinstance(reader.read_marketplace_archive(data), FailedMarketplace)
    monkeypatch.setattr(bundles, "DEFAULT_TOTAL_MAX_BYTES", 100 * 1024)
    files = _files()
    files["skills/hello/bomb"] = b"0" * (2 * 1024 * 1024)
    files["skills/good/SKILL.md"] = _md("good")
    assert len(_archive(files)) < 10000
    assert [e.status for e in _entries(files)] == ["ok", "blocked"]


def test_production_count_limits() -> None:
    files = _files(skills=[f"./skills/s{i}" for i in range(500)])
    assert len(_entries(files)) == 500
    files[CLAUDE] = _catalog(skills=[f"./skills/s{i}" for i in range(501)])
    assert isinstance(
        reader.read_marketplace_archive(_archive(files)), FailedMarketplace
    )
    files = _files()
    files.update({f"unused/{i}": b"" for i in range(9998)})
    assert isinstance(_entries(files)[0], ReadySkill)
    files["one-more"] = b""
    assert isinstance(
        reader.read_marketplace_archive(_archive(files)), FailedMarketplace
    )


def test_recompressed_bundle_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    files = _files()
    files["skills/hello/data"] = random.Random(1).randbytes(16 * 1024)
    files["skills/hello/copy"] = files["skills/hello/data"]
    content = _archive(files, "tar")
    monkeypatch.setattr(bundles, "DEFAULT_ZIP_MAX_BYTES", 24 * 1024)
    assert len(content) < bundles.DEFAULT_ZIP_MAX_BYTES
    result = reader.read_marketplace_archive(content)
    assert isinstance(result, CompleteMarketplace)
    assert isinstance(result.entries[0], BlockedSkill)
    assert "zip" in result.entries[0].reason


def test_archive_corruption_fails_whole_read() -> None:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as archive:
        for path, data in _files().items():
            archive.writestr(path, data)
    data = out.getvalue().replace(b"Use the script.", b"BAD the script.")
    assert isinstance(reader.read_marketplace_archive(data), FailedMarketplace)


def test_manifest_and_tar_extension_bombs() -> None:
    files = _files()
    files[CLAUDE] = b" " * (reader.MANIFEST_MAX_BYTES + 1)
    assert isinstance(
        reader.read_marketplace_archive(_archive(files)), FailedMarketplace
    )
    info = tarfile.TarInfo("extension")
    info.type = tarfile.XHDTYPE
    info.size = reader.MANIFEST_MAX_BYTES * 2
    data = gzip.compress(info.tobuf() + b"0" * info.size)
    result = reader.read_marketplace_archive(data)
    assert isinstance(result, FailedMarketplace)


def test_reader_does_not_import_application_database_or_server_modules() -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from onyx.skills.marketplace.reader import read_marketplace_archive
allowed = {'onyx.db', 'onyx.db.zip_metadata'}
assert not any(
    name.startswith(('onyx.db', 'onyx.server', 'sqlalchemy')) and name not in allowed
    for name in sys.modules
)
""",
        ],
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        check=True,
    )


def test_shared_paths_reuse_bytes_and_nested_paths_have_total_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = _files()
    files[CLAUDE] = json.dumps(
        {"name": "m", "plugins": [{"name": f"p{i}", "source": "./"} for i in range(20)]}
    ).encode()
    entries = _entries(files)
    first = entries[0]
    assert isinstance(first, ReadySkill) and len(entries) == 20
    assert all(
        isinstance(e, ReadySkill) and e.bundle_bytes is first.bundle_bytes
        for e in entries
    )
    monkeypatch.setattr(reader, "BUNDLE_CACHE_MAX_BYTES", len(first.bundle_bytes))
    assert len(_entries(files)) == 20
    files = {
        CLAUDE: _catalog(skills=["outer", "outer/inner"]),
        "outer/SKILL.md": _md("outer"),
        "outer/inner/SKILL.md": _md("inner"),
    }
    monkeypatch.setattr(reader, "BUNDLE_CACHE_MAX_BYTES", 10000)
    nested = _entries(files)
    size = sum(len(e.bundle_bytes) for e in nested if isinstance(e, ReadySkill))
    assert len(nested) == 2 and all(isinstance(e, ReadySkill) for e in nested)
    monkeypatch.setattr(reader, "BUNDLE_CACHE_MAX_BYTES", size)
    assert _entries(files) == nested
    monkeypatch.setattr(reader, "BUNDLE_CACHE_MAX_BYTES", size - 1)
    result = reader.read_marketplace_archive(_archive(files))
    assert (
        isinstance(result, FailedMarketplace) and "Generated bundles" in result.reason
    )


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_work_limit_fails_whole_read(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = _files()
    files["skills/zlarge/SKILL.md"] = _md("zlarge")
    files["skills/zlarge/data"] = b"0" * 4096
    monkeypatch.setattr(archives, "MEMBER_READ_MAX_BYTES", 1024)
    result = reader.read_marketplace_archive(_archive(files, kind))
    assert isinstance(result, FailedMarketplace) and "member reads" in result.reason


@pytest.mark.parametrize(
    "path",
    [
        "bin/run",
        "output-styles/brief.md",
        "monitors/monitors.json",
        "workflows/run.js",
        "settings.json",
        "mcp.json",
        "hooks.json",
    ],
)
def test_additional_components(path: str) -> None:
    files = _files()
    files[path] = b"{}"
    assert isinstance(_entries(files)[0], UnsupportedPlugin)


@pytest.mark.parametrize(
    "fields",
    [
        {"workflows": "./custom"},
        {"experimental": {"monitors": "./custom"}},
        {"experimental": {"themes": "./custom"}},
    ],
)
def test_experimental_components(fields: dict[str, JsonValue]) -> None:
    assert isinstance(_entries(_files(**fields))[0], UnsupportedPlugin)


@pytest.mark.parametrize("folder", ["agents", "commands"])
@pytest.mark.parametrize("declaration", [None, [], ""])
def test_metadata_without_markdown_is_not_a_component(
    folder: str, declaration: JsonValue
) -> None:
    files = _files(**({folder: declaration} if declaration is not None else {}))
    files[f"{folder}/openai.yaml"] = b"interface: {}"
    assert isinstance(_entries(files)[0], ReadySkill)
    files[f"{folder}/nested/run.md"] = b"Definition"
    assert isinstance(_entries(files)[0], UnsupportedPlugin)


def test_explicit_container_retains_keys_and_overrides_default() -> None:
    assert _entries(_files(skills=["./skills"])) == _entries(_files())
    files = _files(skills=["./custom"])
    files["custom/other/SKILL.md"] = _md("other")
    assert [e.entry_key for e in _entries(files)] == ["tools/other"]


@pytest.mark.parametrize("kind", ["zip", "tar"])
@pytest.mark.parametrize(
    "path,status",
    [
        ("CLAUDE.md", "ok"),
        (CLAUDE, "failed"),
        (".claude-plugin", "failed"),
        (".codex-plugin/plugin.json", "failed"),
        ("skills/hello/data", "blocked"),
        ("skills/hello", "blocked"),
    ],
)
def test_special_member_scope(kind: str, path: str, status: str) -> None:
    files = {
        p: data
        for p, data in _files().items()
        if p != path and not p.startswith(path + "/")
    }
    files[CODEX] = _catalog()
    out = io.BytesIO()
    if kind == "zip":
        with zipfile.ZipFile(out, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)
            info = zipfile.ZipInfo(path)
            info.create_system = 3
            info.external_attr = stat.S_IFLNK << 16
            archive.writestr(info, "target")
        data = out.getvalue()
    else:
        with tarfile.open(fileobj=out, mode="w:gz") as archive:
            for name, content in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
            info = tarfile.TarInfo(path)
            info.type = tarfile.SYMTYPE
            info.linkname = "target"
            archive.addfile(info)
        data = out.getvalue()
    result = reader.read_marketplace_archive(data)
    if status == "failed":
        assert isinstance(result, FailedMarketplace)
    else:
        assert isinstance(result, CompleteMarketplace)
        assert [(e.entry_key, e.status) for e in result.entries] == [
            ("tools/hello", status)
        ]


def test_sibling_formats_and_relative_names() -> None:
    files = _files()
    files["docs/note:one"] = b"unrelated"
    assert isinstance(_entries(files)[0], ReadySkill)
    assert isinstance(
        reader.read_marketplace_archive(_archive(files, "tar", "./")),
        CompleteMarketplace,
    )
    files["plugin.json"] = b'{"$schema":"https://example.com/plugin.schema.json"}'
    assert isinstance(_entries(files)[0], UnsupportedPlugin)
    files = {
        "plugins/p/skills/hello/SKILL.md": _md(),
        CLAUDE: json.dumps(
            {
                "name": "m",
                "metadata": {"pluginRoot": "./plugins"},
                "plugins": [{"name": "p", "source": "p"}],
            }
        ).encode(),
    }
    assert isinstance(_entries(files)[0], ReadySkill)
    files[CLAUDE] = files[CLAUDE].replace(b'"source": "p"', b'"source": "./plugins/p"')
    assert isinstance(_entries(files)[0], ReadySkill)


@pytest.mark.parametrize("damage", ["header", "truncated", "partial_header"])
def test_incomplete_tar_body_never_reports_removed_skills(damage: str) -> None:
    files = _files()
    files["skills/later/SKILL.md"] = _md("later")
    payload = gzip.decompress(_archive(files, "tar"))
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        offset = archive.getmember("skills/later/SKILL.md").offset
    if damage == "header":
        payload = payload[:offset] + b"!" + payload[offset + 1 :]
    elif damage == "truncated":
        payload = payload[:offset]
    else:
        payload = payload[: offset + 200]
    result = reader.read_marketplace_archive(gzip.compress(payload))
    assert isinstance(result, FailedMarketplace), result


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_missing_explicit_skill_keeps_its_key(kind: str) -> None:
    files = {
        CLAUDE: _catalog(skills=["./skills/pdf"]),
        "skills/pdf/skill.md": _md("pdf"),
        "skills/pdf/scripts/run.py": b"print('pdf')",
        "skills/pdf/reference/guide.md": b"Reference",
    }
    entries = _entries(files, kind)
    assert [entry.entry_key for entry in entries] == ["tools/pdf"]
    assert isinstance(entries[0], BlockedSkill)


@pytest.mark.parametrize("kind", ["zip", "tar"])
@pytest.mark.parametrize("provider", ["claude", "codex"])
@pytest.mark.parametrize("declared", ["./extra", ["./extra"]])
def test_plugin_manifest_skill_paths(
    kind: str, provider: str, declared: JsonValue
) -> None:
    files = _files()
    files[f".{provider}-plugin/plugin.json"] = json.dumps({"skills": declared}).encode()
    files["extra/additional/SKILL.md"] = _md("additional")
    entries = _entries(files, kind)
    expected = {"tools/additional"}
    if provider == "claude":
        expected.add("tools/hello")
    assert {entry.entry_key for entry in entries} == expected
    assert all(isinstance(entry, ReadySkill) for entry in entries)


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_nested_plugin_root_skill(kind: str) -> None:
    files = {
        CLAUDE: _catalog(source="./plugins/hello"),
        "plugins/hello/SKILL.md": _md(),
    }
    entries = _entries(files, kind)
    assert [entry.entry_key for entry in entries] == ["tools/hello"]
    assert isinstance(entries[0], ReadySkill)


@pytest.mark.parametrize("provider", ["claude", "codex"])
@pytest.mark.parametrize("declared", [None, 1, {}, [1], ["../escape"]])
def test_invalid_plugin_skill_paths_fail_read(
    provider: str, declared: JsonValue
) -> None:
    files = _files()
    files[f".{provider}-plugin/plugin.json"] = json.dumps({"skills": declared}).encode()
    assert isinstance(
        reader.read_marketplace_archive(_archive(files)), FailedMarketplace
    )


def test_overlapping_default_and_manifest_paths_load_once() -> None:
    files = _files()
    files[".claude-plugin/plugin.json"] = b'{"skills":["./skills"]}'
    assert [entry.entry_key for entry in _entries(files)] == ["tools/hello"]
    files["extra/hello/SKILL.md"] = _md()
    files[".claude-plugin/plugin.json"] = b'{"skills":["./extra"]}'
    assert isinstance(
        reader.read_marketplace_archive(_archive(files)), FailedMarketplace
    )


def test_entry_paths_suppress_defaults_but_keep_manifest_paths() -> None:
    files = _files(skills=["./listed/selected"])
    files["listed/selected/SKILL.md"] = _md("selected")
    files["extra/additional/SKILL.md"] = _md("additional")
    files[".claude-plugin/plugin.json"] = b'{"skills":"./extra"}'
    entries = _entries(files)
    assert {entry.entry_key for entry in entries} == {
        "tools/selected",
        "tools/additional",
    }
    assert all(isinstance(entry, ReadySkill) for entry in entries)


def test_claude_manifest_precedes_codex_skill_paths() -> None:
    files = _files()
    files[".claude-plugin/plugin.json"] = b'{"skills":"./skills"}'
    files[".codex-plugin/plugin.json"] = b'{"skills":"./different"}'
    files["different/other/SKILL.md"] = _md("other")
    assert [entry.entry_key for entry in _entries(files)] == ["tools/hello"]


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_empty_manifest_skills_prevent_root_fallback(provider: str) -> None:
    files = {
        CLAUDE: _catalog(source="./plugins/hello"),
        "plugins/hello/SKILL.md": _md(),
        f"plugins/hello/.{provider}-plugin/plugin.json": b'{"skills":[]}',
    }
    assert _entries(files) == ()


def test_root_fallback_does_not_claim_repository_or_default_container() -> None:
    files = {CLAUDE: _catalog(), "SKILL.md": _md()}
    assert _entries(files) == ()
    files = {
        CLAUDE: _catalog(source="./plugins/hello"),
        "plugins/hello/SKILL.md": _md(),
        "plugins/hello/skills/child/SKILL.md": _md("child"),
    }
    assert [entry.entry_key for entry in _entries(files)] == ["tools/child"]
    files[CLAUDE] = _catalog(source="./plugins/hello", skills=[])
    assert _entries(files) == ()


def test_explicit_special_skill_path_stays_blocked() -> None:
    data = io.BytesIO(_archive({CLAUDE: _catalog(skills=["./skills/hello"])}))
    with zipfile.ZipFile(data, "a") as archive:
        info = zipfile.ZipInfo("skills/hello")
        info.create_system = 3
        info.external_attr = stat.S_IFLNK << 16
        archive.writestr(info, b"elsewhere")
    result = reader.read_marketplace_archive(data.getvalue())
    assert isinstance(result, CompleteMarketplace), result
    assert len(result.entries) == 1
    assert isinstance(result.entries[0], BlockedSkill)
    assert result.entries[0].entry_key == "tools/hello"


@pytest.mark.parametrize("kind", ["zip", "tar"])
@pytest.mark.parametrize("declaration", ["entry", "claude", "codex"])
@pytest.mark.parametrize("names", [["one"], ["one", "two"]])
def test_declared_default_container_keeps_broken_child_keys(
    kind: str, declaration: str, names: list[str]
) -> None:
    files = {CLAUDE: _catalog()}
    if declaration == "entry":
        files[CLAUDE] = _catalog(skills="./skills/")
    else:
        files[f".{declaration}-plugin/plugin.json"] = b'{"skills":"./skills/"}'
    for name in names:
        files[f"skills/{name}/scripts/run.py"] = b"pass"
    entries = _entries(files, kind)
    assert {entry.entry_key for entry in entries} == {f"tools/{name}" for name in names}
    assert all(isinstance(entry, BlockedSkill) for entry in entries)


def test_plugin_count_rejected_before_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reader, "PLUGIN_MAX_COUNT", 2)
    files = _files()
    files[CLAUDE] = json.dumps(
        {"name": "m", "plugins": [{"name": str(i), "source": "./"} for i in range(3)]}
    ).encode()
    result = reader.read_marketplace_archive(_archive(files))
    assert isinstance(result, FailedMarketplace), result
    assert "plugins" in result.reason


@pytest.mark.parametrize("source", ["entry", "claude", "codex"])
def test_declared_path_limit_applies_before_expansion(
    source: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reader, "DECLARED_PATH_MAX_COUNT", 2)
    paths = ["./missing"] * 3
    files = _files(skills=paths) if source == "entry" else _files()
    if source != "entry":
        files[f".{source}-plugin/plugin.json"] = json.dumps({"skills": paths}).encode()
    result = reader.read_marketplace_archive(_archive(files))
    assert isinstance(result, FailedMarketplace), result
    assert "declared component paths" in result.reason


def test_declared_path_budget_shared_across_plugins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reader, "DECLARED_PATH_MAX_COUNT", 2)
    files = _files()
    files[CLAUDE] = json.dumps(
        {
            "name": "m",
            "plugins": [
                {"name": str(i), "source": "./", "skills": "./skills"} for i in range(2)
            ],
        }
    ).encode()
    assert len(_entries(files)) == 2
    files[".codex-plugin/plugin.json"] = b'{"skills":"./skills"}'
    result = reader.read_marketplace_archive(_archive(files))
    assert isinstance(result, FailedMarketplace), result
    assert "declared component paths" in result.reason


@pytest.mark.parametrize("component", ["agents", "commands"])
@pytest.mark.parametrize("source", ["entry", "claude", "codex"])
def test_component_declarations_share_discovery_budget(
    component: str, source: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reader, "DECLARED_PATH_MAX_COUNT", 2)
    fields = {component: ["./absent"] * 3}
    files = _files()
    if source == "entry":
        catalog = json.loads(files[CLAUDE])
        catalog["plugins"][0].update(fields)
        files[CLAUDE] = json.dumps(catalog).encode()
    else:
        files[f".{source}-plugin/plugin.json"] = json.dumps(fields).encode()
    result = reader.read_marketplace_archive(_archive(files))
    assert isinstance(result, FailedMarketplace), result
    assert "declared" in result.reason


def test_component_budget_combines_fields_and_plugins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reader, "DECLARED_PATH_MAX_COUNT", 4)
    files = _files()
    files[CLAUDE] = json.dumps(
        {
            "name": "m",
            "plugins": [
                {
                    "name": str(i),
                    "source": "./",
                    "agents": ["./absent"],
                    "commands": ["./absent"],
                }
                for i in range(2)
            ],
        }
    ).encode()
    assert len(_entries(files)) == 2
    files[".codex-plugin/plugin.json"] = b'{"skills":"./skills"}'
    assert isinstance(
        reader.read_marketplace_archive(_archive(files)), FailedMarketplace
    )


@pytest.mark.parametrize("kind", ["zip", "tar"])
@pytest.mark.parametrize("shared_root", [False, True])
def test_unique_manifest_bytes_share_one_budget(
    kind: str, shared_root: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots = ["p", "p" if shared_root else "q"]
    files = {
        CLAUDE: json.dumps(
            {
                "name": "m",
                "plugins": [
                    {"name": str(i), "source": "./" + root}
                    for i, root in enumerate(roots)
                ],
            }
        ).encode()
    }
    for root in roots:
        files[f"{root}/.claude-plugin/plugin.json"] = b'{"name":"test"}'
        files[f"{root}/.codex-plugin/plugin.json"] = b'{"description":"test"}'
        files[f"{root}/skills/hello/SKILL.md"] = _md()
    limit = sum(len(data) for path, data in files.items() if path.endswith(".json"))
    monkeypatch.setattr(reader, "MANIFEST_TOTAL_MAX_BYTES", limit, raising=False)
    assert [e.entry_key for e in _entries(files, kind)] == ["0/hello", "1/hello"]
    monkeypatch.setattr(reader, "MANIFEST_TOTAL_MAX_BYTES", limit - 1)
    result = reader.read_marketplace_archive(_archive(files, kind))
    assert isinstance(result, FailedMarketplace), result
    assert "manifest bytes" in result.reason


def test_deep_yaml_blocks_only_its_skill() -> None:
    files = _files()
    files["skills/deep/SKILL.md"] = (
        b"---\nname: deep\ndescription: Test\nmetadata: "
        + b"[" * 5000
        + b"]" * 5000
        + b"\n---\nInstructions."
    )
    entries = {entry.entry_key: entry for entry in _entries(files)}
    assert isinstance(entries["tools/hello"], ReadySkill)
    assert isinstance(entries["tools/deep"], BlockedSkill)
    assert "not valid YAML" in entries["tools/deep"].reason


def test_truncated_sparse_extension_returns_failed_marketplace() -> None:
    info = tarfile.TarInfo("sparse")
    info.type = tarfile.GNUTYPE_SPARSE
    header = bytearray(info.tobuf(format=tarfile.GNU_FORMAT))
    header[482] = 1
    header[148:156] = b" " * 8
    header[148:156] = b"%06o\0 " % sum(header)
    result = reader.read_marketplace_archive(gzip.compress(header))
    assert isinstance(result, FailedMarketplace), result


@pytest.mark.parametrize("length_field", [30, 32])
def test_zip_catalog_rejects_swallowed_directory_entries(length_field: int) -> None:
    files = {CLAUDE: _catalog()}
    files.update({f"skills/s{i}/SKILL.md": _md(f"s{i}") for i in range(4)})
    data = bytearray(_archive(files))
    end = data.rfind(b"PK\x05\x06")
    central = struct.unpack_from("<I", data, end + 16)[0]
    second = data.index(b"PK\x01\x02", central + 4)
    third = data.index(b"PK\x01\x02", second + 4)
    struct.pack_into("<H", data, second + length_field, end - third)
    result = reader.read_marketplace_archive(bytes(data))
    assert isinstance(result, FailedMarketplace), result


@pytest.mark.parametrize("damage", ["name", "signature"])
def test_zip_catalog_checks_unselected_local_headers(damage: str) -> None:
    files = _files()
    files["skills/hello/reference.txt"] = b"Keep this supporting file"
    files["unrelated.txt"] = b"Outside the skill"
    data = bytearray(_archive(files))
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        offset = archive.getinfo("unrelated.txt").header_offset
    if damage == "name":
        data[offset + 30] ^= 1
    else:
        data[offset] = 0
    result = reader.read_marketplace_archive(bytes(data))
    assert isinstance(result, FailedMarketplace), result


@pytest.mark.parametrize("prefix", [b"", b"self extracting prefix"])
@pytest.mark.parametrize("zip64", [False, True])
def test_zip_catalog_accepts_comments_and_zip64(prefix: bytes, zip64: bool) -> None:
    data = bytearray(_archive(_files()))
    end = data.rfind(b"PK\x05\x06")
    if zip64:
        count = struct.unpack_from("<H", data, end + 10)[0]
        size, offset = struct.unpack_from("<II", data, end + 12)
        record = struct.pack(
            "<4sQHHIIQQQQ", b"PK\x06\x06", 44, 45, 45, 0, 0, count, count, size, offset
        )
        locator = struct.pack("<4sIQI", b"PK\x06\x07", 0, end, 1)
        struct.pack_into("<HHII", data, end + 8, 65535, 65535, 0xFFFFFFFF, 0xFFFFFFFF)
        data[end:end] = record + locator
        end += len(record) + len(locator)
    comment = b"archive comment"
    struct.pack_into("<H", data, end + 20, len(comment))
    data.extend(comment)
    result = reader.read_marketplace_archive(prefix + data)
    assert isinstance(result, CompleteMarketplace), result
    assert [entry.entry_key for entry in result.entries] == ["tools/hello"]
