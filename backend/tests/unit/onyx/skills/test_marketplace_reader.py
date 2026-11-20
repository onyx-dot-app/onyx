import json

import pytest

from onyx.skills.bundle import DEFAULT_PER_FILE_MAX_BYTES, open_bundle_zip
from onyx.skills.marketplace import reader
from onyx.skills.marketplace.models import (
    BlockedPlugin,
    CompleteMarketplace,
    FailedMarketplace,
    GitHubRepoSource,
    MarketplaceReasonCode,
    ReadyPlugin,
    RemotePlugin,
    UnsupportedPlugin,
)
from onyx.skills.marketplace.reader import read_marketplace
from tests.unit.onyx.skills.marketplace_fixtures import (
    CLAUDE,
    CODEX,
    catalog,
    plugin_json,
    skill_md,
)


def _complete(
    files: dict[str, bytes], folder: str | None = None
) -> CompleteMarketplace:
    result = read_marketplace(files, folder)
    assert isinstance(result, CompleteMarketplace), result
    return result


def _ready(result: CompleteMarketplace, key: str) -> ReadyPlugin:
    entry = next(entry for entry in result.entries if entry.entry_key == key)
    assert isinstance(entry, ReadyPlugin), entry
    return entry


def _bundle_paths(entry: ReadyPlugin) -> list[str]:
    with open_bundle_zip(entry.bundle.content) as bundle_zip:
        return sorted(bundle_zip.namelist())


def _bundle_manifest(entry: ReadyPlugin) -> dict[str, object]:
    with open_bundle_zip(entry.bundle.content) as bundle_zip:
        return json.loads(bundle_zip.read(".claude-plugin/plugin.json"))


def test_local_entry_merges_plugin_json_over_entry_fields() -> None:
    files = {
        CLAUDE: catalog(
            {
                "name": "formatter",
                "source": "./plugins/formatter",
                "description": "From the entry",
                "version": "1.0.0",
            }
        ),
        "plugins/formatter/.claude-plugin/plugin.json": plugin_json(
            "formatter", description="From plugin.json"
        ),
        "plugins/formatter/skills/format/SKILL.md": skill_md("format"),
    }
    result = _complete(files)
    assert result.name == "test"
    entry = _ready(result, "formatter")
    assert entry.path == "plugins/formatter"
    assert entry.bundle.manifest.description == "From plugin.json"
    assert entry.bundle.manifest.version == "1.0.0"
    assert [skill.content.name for skill in entry.bundle.skills] == ["format"]
    assert _bundle_paths(entry) == [
        ".claude-plugin/plugin.json",
        "skills/format/SKILL.md",
    ]
    assert [item.path for item in entry.file_manifest] == _bundle_paths(entry)


def test_entry_without_plugin_json_writes_one_from_the_entry() -> None:
    files = {
        CLAUDE: catalog(
            {
                "name": "notes",
                "source": "./notes",
                "description": "Take notes",
                "strict": False,
            }
        ),
        "notes/skills/write/SKILL.md": skill_md("write"),
    }
    entry = _ready(_complete(files), "notes")
    assert _bundle_manifest(entry) == {"name": "notes", "description": "Take notes"}


def test_skills_list_entry_takes_only_the_listed_folders() -> None:
    files = {
        CLAUDE: catalog(
            {
                "name": "document-skills",
                "source": "./",
                "strict": False,
                "skills": ["./skills/xlsx", "./skills/docx"],
            },
            {
                "name": "example-skills",
                "source": "./",
                "strict": False,
                "skills": ["./examples"],
            },
        ),
        "skills/xlsx/SKILL.md": skill_md("xlsx"),
        "skills/xlsx/scripts/run.py": b"print(1)\n",
        "skills/docx/SKILL.md": skill_md("docx"),
        "skills/pdf/SKILL.md": skill_md("pdf"),
        "examples/art/SKILL.md": skill_md("art"),
        "examples/brand/SKILL.md": skill_md("brand"),
        "README.md": b"# Skills\n",
    }
    result = _complete(files)
    documents = _ready(result, "document-skills")
    assert documents.path == ""
    assert _bundle_paths(documents) == [
        ".claude-plugin/plugin.json",
        "skills/docx/SKILL.md",
        "skills/xlsx/SKILL.md",
        "skills/xlsx/scripts/run.py",
    ]
    assert "skills" not in _bundle_manifest(documents)
    examples = _ready(result, "example-skills")
    assert sorted(skill.content.name for skill in examples.bundle.skills) == [
        "art",
        "brand",
    ]


def test_skills_list_entry_keeps_the_mcp_file_that_the_entry_names() -> None:
    files = {
        CLAUDE: catalog(
            {
                "name": "tools",
                "source": "./",
                "strict": False,
                "skills": ["./skills/xlsx"],
                "mcpServers": "./config/mcp.json",
            }
        ),
        "skills/xlsx/SKILL.md": skill_md("xlsx"),
        "config/mcp.json": json.dumps(
            {"mcpServers": {"main": {"type": "http", "url": "https://mcp.test/mcp"}}}
        ).encode(),
    }
    entry = _ready(_complete(files), "tools")
    assert "config/mcp.json" in _bundle_paths(entry)
    assert [need.name for need in entry.bundle.needs] == ["main"]


def test_mcp_entry_imports_with_a_need() -> None:
    files = {
        CLAUDE: catalog(
            {
                "name": "linear",
                "source": "./linear",
                "mcpServers": {
                    "linear": {"type": "http", "url": "https://mcp.linear.app/mcp"}
                },
            }
        ),
        "linear/README.md": b"Linear\n",
    }
    entry = _ready(_complete(files), "linear")
    assert entry.bundle.skills == []
    assert [(need.name, need.supported) for need in entry.bundle.needs] == [
        ("linear", True)
    ]


def test_remote_sources() -> None:
    files = {
        CLAUDE: catalog(
            {"name": "remote", "source": {"source": "github", "repo": "acme/remote"}},
            {
                "name": "subdir",
                "source": {
                    "source": "git-subdir",
                    "url": "https://github.com/acme/mono.git",
                    "path": "./plugins/subdir",
                    "ref": "main",
                },
            },
            {
                "name": "gitlab",
                "source": {
                    "source": "git-subdir",
                    "url": "https://gitlab.com/acme/mono.git",
                    "path": "plugins/x",
                },
            },
            {"name": "npm", "source": {"source": "npm", "package": "@acme/x"}},
            {"name": "url", "source": {"source": "url", "url": "https://x.test/y.git"}},
            {
                "name": "github-url",
                "source": {
                    "source": "url",
                    "url": "https://github.com/acme/url-plugin.git",
                    "sha": "a" * 40,
                },
            },
        )
    }
    entries = {entry.entry_key: entry for entry in _complete(files).entries}
    remote = entries["remote"]
    assert isinstance(remote, RemotePlugin)
    assert remote.source == GitHubRepoSource(owner="acme", repo="remote")
    subdir = entries["subdir"]
    assert isinstance(subdir, RemotePlugin)
    assert subdir.source == GitHubRepoSource(
        owner="acme", repo="mono", ref="main", path="plugins/subdir"
    )
    github_url = entries["github-url"]
    assert isinstance(github_url, RemotePlugin)
    assert github_url.source == GitHubRepoSource(
        owner="acme", repo="url-plugin", sha="a" * 40
    )
    assert entries["gitlab"] == UnsupportedPlugin(
        entry_key="gitlab",
        reason="Onyx gets plugins only from github.com, not from gitlab.com.",
    )
    assert entries["url"] == UnsupportedPlugin(
        entry_key="url",
        reason="Onyx gets plugins only from github.com, not from x.test.",
    )
    assert entries["npm"] == UnsupportedPlugin(
        entry_key="npm", reason="Onyx cannot install a plugin from a 'npm' source."
    )


def test_symbolic_link_blocks_only_the_plugin_that_holds_it() -> None:
    files = {
        CLAUDE: catalog(
            {"name": "alpha", "source": "./plugins/alpha"},
            {"name": "beta", "source": "./plugins/beta"},
        ),
        "plugins/alpha/skills/alpha/SKILL.md": skill_md("alpha"),
        "plugins/beta/skills/beta/SKILL.md": skill_md("beta"),
    }
    links = frozenset({"docs/CLAUDE.md", "plugins/beta/README.md"})
    result = read_marketplace(files, None, links)
    assert isinstance(result, CompleteMarketplace), result
    entries = {entry.entry_key: entry for entry in result.entries}
    assert isinstance(entries["alpha"], ReadyPlugin)
    beta = entries["beta"]
    assert isinstance(beta, BlockedPlugin)
    assert "plugins/beta/README.md" in beta.reason


def test_bad_entries_block_only_themselves() -> None:
    files = {
        CLAUDE: catalog(
            {"name": "good", "source": "./good"},
            {"name": "Bad_Name", "source": "./bad"},
            {"name": "missing", "source": "./missing"},
            {"name": "broken", "source": "./broken"},
            {"name": "escape", "source": "../outside"},
            {"name": "empty", "source": "./empty"},
        ),
        "good/skills/good/SKILL.md": skill_md("good"),
        "bad/skills/bad/SKILL.md": skill_md("bad"),
        "broken/skills/broken/SKILL.md": b"no frontmatter",
        "empty/README.md": b"nothing to use\n",
    }
    entries = {entry.entry_key: entry for entry in _complete(files).entries}
    assert isinstance(entries["good"], ReadyPlugin)
    for key in ("Bad_Name", "missing", "broken", "escape", "empty"):
        assert isinstance(entries[key], BlockedPlugin), key
    blocked = entries["missing"]
    assert isinstance(blocked, BlockedPlugin)
    assert blocked.reason == "The plugin folder 'missing' is missing."


def test_source_kind_that_is_not_text_is_not_supported() -> None:
    files = {CLAUDE: catalog({"name": "odd", "source": {"source": []}})}
    (entry,) = _complete(files).entries
    assert isinstance(entry, UnsupportedPlugin)


def test_plugin_with_only_commands_is_not_supported() -> None:
    files = {
        CLAUDE: catalog({"name": "commands-only", "source": "./commands-only"}),
        "commands-only/commands/review.md": b"Review the diff.\n",
        "commands-only/hooks/hooks.json": b"{}",
    }
    (entry,) = _complete(files).entries
    assert entry == UnsupportedPlugin(
        entry_key="commands-only",
        reason="Onyx runs only skills and MCP servers.",
        reason_code=MarketplaceReasonCode.SKILLS_AND_MCP_ONLY,
    )


def test_size_limit_blocks_the_entry_not_the_read() -> None:
    files = {
        CLAUDE: catalog(
            {"name": "big", "source": "./big"}, {"name": "small", "source": "./small"}
        ),
        "big/skills/big/SKILL.md": skill_md("big"),
        "big/skills/big/data.bin": b"x" * (DEFAULT_PER_FILE_MAX_BYTES + 1),
        "small/skills/small/SKILL.md": skill_md("small"),
    }
    entries = {entry.entry_key: entry for entry in _complete(files).entries}
    assert isinstance(entries["big"], BlockedPlugin)
    assert isinstance(entries["small"], ReadyPlugin)


def test_plugin_root_folder() -> None:
    files = {
        f"market/{CLAUDE}": catalog(
            {"name": "tool", "source": "tool"},
            metadata={"pluginRoot": "./plugins"},
        ),
        "market/plugins/tool/skills/tool/SKILL.md": skill_md("tool"),
    }
    result = read_marketplace(files, "market")
    assert isinstance(result, CompleteMarketplace)
    entry = _ready(result, "tool")
    assert entry.path == "market/plugins/tool"
    assert isinstance(read_marketplace(files, None), FailedMarketplace)


def test_claude_manifest_comes_before_codex() -> None:
    files = {
        CLAUDE: catalog({"name": "claude", "source": "./a"}),
        CODEX: catalog({"name": "codex", "source": "./a"}),
        "a/skills/a/SKILL.md": skill_md("a"),
    }
    assert [entry.entry_key for entry in _complete(files).entries] == ["claude"]
    del files[CLAUDE]
    assert [entry.entry_key for entry in _complete(files).entries] == ["codex"]


def test_same_files_give_the_same_bundle() -> None:
    files = {
        CLAUDE: catalog({"name": "tool", "source": "./tool"}),
        "tool/skills/tool/SKILL.md": skill_md("tool"),
        "tool/skills/tool/a.txt": b"a",
    }
    first = _ready(_complete(files), "tool")
    second = _ready(_complete(dict(reversed(list(files.items())))), "tool")
    assert first.bundle.content == second.bundle.content


@pytest.mark.parametrize(
    "manifest",
    [
        b"{not json",
        b'{"name": "x", "name": "y", "plugins": []}',
        b'{"name": "x", "plugins": {}}',
        b'{"plugins": []}',
        json.dumps({"name": "x", "plugins": [{"name": "a"}, {"name": "a"}]}).encode(),
        json.dumps({"name": "x", "plugins": [{"source": "./a"}]}).encode(),
    ],
)
def test_bad_manifest_fails_the_whole_read(manifest: bytes) -> None:
    assert isinstance(read_marketplace({CLAUDE: manifest}, None), FailedMarketplace)


def test_missing_manifest_fails() -> None:
    result = read_marketplace({"README.md": b"hi"}, None)
    assert isinstance(result, FailedMarketplace)
    assert CLAUDE in result.reason


def test_limits_fail_the_whole_read(monkeypatch: pytest.MonkeyPatch) -> None:
    files = {
        CLAUDE: catalog(
            {"name": "one", "source": "./one"}, {"name": "two", "source": "./two"}
        ),
        "one/skills/one/SKILL.md": skill_md("one"),
        "two/skills/two/SKILL.md": skill_md("two"),
    }
    monkeypatch.setattr(reader, "GITHUB_SKILL_MAX_COUNT", 1)
    assert isinstance(read_marketplace(files, None), FailedMarketplace)
    monkeypatch.setattr(reader, "GITHUB_SKILL_MAX_COUNT", 2)
    monkeypatch.setattr(reader, "PLUGIN_ENTRY_MAX_COUNT", 1)
    assert isinstance(read_marketplace(files, None), FailedMarketplace)


_DEEP = b'{"a": ' * 100_000 + b"1" + b"}" * 100_000


def test_deeply_nested_plugin_json_blocks_only_its_entry() -> None:
    files = {
        CLAUDE: catalog(
            {"name": "good", "source": "./good"},
            {"name": "deep", "source": "./deep"},
        ),
        "good/skills/good/SKILL.md": skill_md("good"),
        "deep/.claude-plugin/plugin.json": _DEEP,
        "deep/skills/deep/SKILL.md": skill_md("deep"),
    }
    entries = {entry.entry_key: entry for entry in _complete(files).entries}
    assert isinstance(entries["good"], ReadyPlugin)
    deep = entries["deep"]
    assert isinstance(deep, BlockedPlugin)
    assert "nested too deeply" in deep.reason


def test_deeply_nested_marketplace_json_fails_cleanly() -> None:
    result = read_marketplace({CLAUDE: _DEEP}, None)
    assert isinstance(result, FailedMarketplace)
    assert "nested too deeply" in result.reason
