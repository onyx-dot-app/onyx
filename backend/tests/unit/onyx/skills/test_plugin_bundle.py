import io
import json
import zipfile

import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.models import (
    PluginAuthor,
    PluginManifest,
    PluginUnusedPart,
)
from onyx.skills.plugin_bundle import read_plugin_bundle


def _zip(files: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle_zip:
        for path, content in files.items():
            bundle_zip.writestr(path, content)
    return output.getvalue()


def _skill_md(name: str, description: str = "Does a thing.") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\nSteps.\n"


def _paths(zip_bytes: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as bundle_zip:
        return sorted(bundle_zip.namelist())


def test_reads_a_wrapped_claude_plugin() -> None:
    bundle = read_plugin_bundle(
        _zip(
            {
                "review-kit/.claude-plugin/plugin.json": json.dumps(
                    {
                        "name": "review-kit",
                        "version": "1.2.0",
                        "description": "Review tools.",
                        "author": {"name": "Ana", "email": "ana@example.com"},
                        "repository": {"type": "git", "url": "https://git.test/r"},
                        "keywords": ["review", 3],
                        "hooks": "./hooks/hooks.json",
                    }
                ),
                "review-kit/skills/review/SKILL.md": _skill_md("review"),
                "review-kit/skills/review/ref.md": "Reference.",
                "review-kit/skills/lint/SKILL.md": _skill_md("lint-it"),
                "review-kit/commands/go.md": "Go.",
                "review-kit/.mcp.json": json.dumps(
                    {
                        "mcpServers": {
                            "linear": {
                                "type": "http",
                                "url": "HTTPS://MCP.Linear.app:443/mcp/",
                            },
                            "local": {"command": "npx", "args": ["server"]},
                            "untyped": {"url": "https://untyped.test/mcp"},
                            "secret": {
                                "type": "sse",
                                "url": "https://${HOST}/sse",
                            },
                        }
                    }
                ),
                "__MACOSX/review-kit/._SKILL.md": "junk",
            }
        )
    )

    assert bundle.manifest == PluginManifest(
        name="review-kit",
        version="1.2.0",
        description="Review tools.",
        author=PluginAuthor(name="Ana", email="ana@example.com"),
        repository="https://git.test/r",
        keywords=["review"],
        unused_parts=[PluginUnusedPart.COMMANDS, PluginUnusedPart.HOOKS],
    )
    assert [
        (skill.content.path, skill.content.name, skill.warnings)
        for skill in bundle.skills
    ] == [
        (
            "skills/lint",
            "lint-it",
            [
                "The folder skills/lint holds the skill 'lint-it'. Onyx uses the "
                "name 'lint-it'."
            ],
        ),
        ("skills/review", "review", []),
    ]
    assert [need.model_dump() for need in bundle.needs] == [
        {
            "kind": "mcp",
            "name": "linear",
            "url": "https://mcp.linear.app/mcp",
            "transport": "http",
            "supported": True,
            "url_problem": None,
        },
        {
            "kind": "mcp",
            "name": "local",
            "url": None,
            "transport": "stdio",
            "supported": False,
            "url_problem": None,
        },
        {
            "kind": "mcp",
            "name": "secret",
            "url": None,
            "transport": "sse",
            "supported": False,
            "url_problem": "variable",
        },
        {
            "kind": "mcp",
            "name": "untyped",
            "url": "https://untyped.test/mcp",
            "transport": None,
            "supported": False,
            "url_problem": None,
        },
    ]
    assert bundle.warnings == []
    assert _paths(bundle.content) == [
        ".claude-plugin/plugin.json",
        ".mcp.json",
        "commands/go.md",
        "skills/lint/SKILL.md",
        "skills/review/SKILL.md",
        "skills/review/ref.md",
    ]


def test_reads_a_codex_plugin_with_inline_servers() -> None:
    bundle = read_plugin_bundle(
        _zip(
            {
                ".codex-plugin/plugin.json": json.dumps(
                    {
                        "name": "notion",
                        "author": "Notion",
                        "mcpServers": {
                            "notion": {
                                "type": "streamable-http",
                                "url": "https://mcp.notion.com/mcp",
                            }
                        },
                    }
                ),
                "SKILL.md": _skill_md("stray"),
            }
        )
    )

    assert bundle.manifest.author == PluginAuthor(name="Notion")
    assert bundle.skills == []
    assert [need.model_dump() for need in bundle.needs] == [
        {
            "kind": "mcp",
            "name": "notion",
            "url": "https://mcp.notion.com/mcp",
            "transport": "streamable-http",
            "supported": True,
            "url_problem": None,
        },
    ]
    assert bundle.warnings == [
        "Onyx skips SKILL.md. A skill must be in skills/<name>/SKILL.md."
    ]


def test_reads_servers_from_a_file_the_manifest_names() -> None:
    bundle = read_plugin_bundle(
        _zip(
            {
                "plugin.json": json.dumps(
                    {"name": "kit", "mcpServers": "./config/servers.json"}
                ),
                "config/servers.json": json.dumps(
                    {"docs": {"type": "http", "url": "https://docs.test/mcp"}}
                ),
            }
        )
    )

    assert [need.name for need in bundle.needs] == ["docs"]


def test_reads_servers_from_an_array_of_files_and_objects() -> None:
    bundle = read_plugin_bundle(
        _zip(
            {
                "plugin.json": json.dumps(
                    {
                        "name": "kit",
                        "mcpServers": [
                            "./config/servers.json",
                            {"wiki": {"type": "sse", "url": "https://wiki.test/sse"}},
                            {"docs": {"type": "http", "url": "https://other.test"}},
                            ".mcp.json",
                        ],
                    }
                ),
                "config/servers.json": json.dumps(
                    {"docs": {"type": "http", "url": "https://docs.test/mcp"}}
                ),
                ".mcp.json": json.dumps(
                    {"mcpServers": {"tickets": {"command": "tickets"}}}
                ),
            }
        )
    )

    assert [(need.name, need.url) for need in bundle.needs] == [
        ("docs", "https://docs.test/mcp"),
        ("tickets", None),
        ("wiki", "https://wiki.test/sse"),
    ]
    assert bundle.warnings == [
        "The MCP server 'docs' is defined twice. Onyx uses the first one."
    ]


@pytest.mark.parametrize(
    ("files", "detail"),
    [
        (
            {"plugin.json": json.dumps({"name": "empty"}), "README.md": "Hi."},
            "This plugin has no skill and no MCP server. Onyx uses only skills in "
            "skills/<name>/SKILL.md and MCP servers in .mcp.json or plugin.json.",
        ),
        (
            {"SKILL.md": _skill_md("just-a-skill")},
            "The plugin has no .claude-plugin/plugin.json, "
            ".codex-plugin/plugin.json or plugin.json at the zip root or directly "
            "inside one top-level folder.",
        ),
        (
            {"plugin.json": "{not json"},
            "plugin.json is not valid JSON: Expecting property name enclosed in "
            "double quotes: line 1 column 2 (char 1)",
        ),
        (
            {"plugin.json": json.dumps({"name": "Bad Name"})},
            "The plugin name 'Bad Name' in plugin.json must use only lowercase "
            "letters, numbers and single hyphens, and at most 64 characters.",
        ),
        (
            {
                "plugin.json": json.dumps({"name": "kit"}),
                "skills/a/SKILL.md": "no frontmatter",
            },
            "skills/a/SKILL.md: SKILL.md must start with YAML frontmatter "
            "delimited by two --- lines",
        ),
        (
            {
                "plugin.json": json.dumps({"name": "kit"}),
                "skills/a/SKILL.md": _skill_md("same"),
                "skills/b/SKILL.md": _skill_md("same"),
            },
            "skills/a and skills/b both hold the skill 'same'.",
        ),
        (
            {"plugin.json": json.dumps({"name": "kit", "mcpServers": [["nested"]]})},
            "The MCP servers in plugin.json must be a JSON object.",
        ),
        (
            {
                "plugin.json": json.dumps({"name": "kit", "description": "a\x00b"}),
                "skills/a/SKILL.md": _skill_md("a"),
            },
            "plugin.json cannot contain a NUL character.",
        ),
        (
            {
                "plugin.json": '{"name": "kit", "x": '
                + "[" * 600
                + '"a\\u0000b"'
                + "]" * 600
                + "}",
                "skills/a/SKILL.md": _skill_md("a"),
            },
            "plugin.json cannot contain a NUL character.",
        ),
        (
            {
                "plugin.json": json.dumps({"name": "kit"}),
                ".mcp.json": json.dumps(
                    {"mcpServers": {"do\x00cs": {"command": "docs"}}}
                ),
            },
            ".mcp.json cannot contain a NUL character.",
        ),
        (
            {
                "plugin.json": json.dumps({"name": "kit"}),
                "skills/a/SKILL.md": _skill_md("a", '"Does\\0 a thing."'),
            },
            "skills/a/SKILL.md: SKILL.md frontmatter field 'description' must not "
            "contain a NUL character",
        ),
    ],
)
def test_refuses_an_invalid_plugin_with_the_reason(
    files: dict[str, str], detail: str
) -> None:
    with pytest.raises(OnyxError) as error:
        read_plugin_bundle(_zip(files))

    assert error.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert error.value.detail == detail


def test_reads_skill_fields_that_claude_code_accepts() -> None:
    skill_md = (
        "---\nname: access\ndescription: Does a thing.\n"
        "allowed-tools:\n  - Read\n  - Bash(ls *)\n"
        "metadata:\n  tags: [design, 3]\nlicense: [MIT]\n---\n\nSteps.\n"
    )
    bundle = read_plugin_bundle(
        _zip(
            {
                ".claude-plugin/plugin.json": json.dumps({"name": "chat-kit"}),
                "skills/access/SKILL.md": skill_md,
            }
        )
    )
    [skill] = bundle.skills
    assert skill.content.name == "access"
    assert skill.content.frontmatter["allowed-tools"] == ["Read", "Bash(ls *)"]
    assert skill.content.frontmatter["license"] == ["MIT"]


def test_a_bad_skill_field_gives_a_plain_message() -> None:
    with pytest.raises(OnyxError) as exc_info:
        read_plugin_bundle(
            _zip(
                {
                    ".claude-plugin/plugin.json": json.dumps({"name": "chat-kit"}),
                    "skills/access/SKILL.md": "---\nname: access\ndescription: 3\n---\n",
                }
            )
        )
    assert exc_info.value.detail == (
        "skills/access/SKILL.md: SKILL.md frontmatter field 'description' must be text"
    )


def test_removes_bidi_controls_from_shown_text() -> None:
    bundle = read_plugin_bundle(
        _zip(
            {
                ".claude-plugin/plugin.json": json.dumps(
                    {
                        "name": "chat-kit",
                        "description": "\u202egnp.exe safe",
                        "author": {"name": "\u202eNIMDA"},
                        "keywords": ["\u2066x\u2069"],
                    }
                ),
                "skills/access/SKILL.md": _skill_md("access", "\u202etxt.exe"),
            }
        )
    )
    assert bundle.manifest.description == "gnp.exe safe"
    assert bundle.manifest.author == PluginAuthor(name="NIMDA")
    assert bundle.manifest.keywords == ["x"]
    assert bundle.skills[0].content.description == "txt.exe"
