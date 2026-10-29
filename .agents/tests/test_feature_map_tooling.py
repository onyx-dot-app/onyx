"""Unit tests for the feature map tooling (`.agents/feature-map/`).

Each test builds a small git repo with a fixture map in `tmp_path`, so the tests
never read the real map.
"""

import importlib.util
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

_MAP_DIR = Path(__file__).resolve().parents[2] / ".agents/feature-map"


def _load(name: str) -> ModuleType:
    # `stale_docs` imports its sibling `check_feature_map`, as it does when run as a script.
    if str(_MAP_DIR) not in sys.path:
        sys.path.insert(0, str(_MAP_DIR))
    spec = importlib.util.spec_from_file_location(name, _MAP_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


check_feature_map = _load("check_feature_map")
stale_docs = _load("stale_docs")

_CODE = {
    "backend/onyx/chat/citation_utils.py": "def update_mapping():\n    pass\n",
    "backend/onyx/tools/tool_runner.py": "class ToolRunner:\n    def run(self):\n        pass\n",
    "backend/ee/onyx/tools/tool_runner.py": "class ToolRunner:\n    pass\n",
    "backend/onyx/server/new_api.py": "",
    "backend/scripts/dev.py": "",
    "backend/tests/unit/test_x.py": "",
}

_CITATIONS = """# Citations

> Turns retrieved documents into numbered markers.

**Verified against:** `{sha}` (2026-10-28)
**Edition:** CE

---

## User experience

A user sees numbered markers that open sources.

## Scope

Citations owns the number mapping. [[tools-framework]] owns number allocation.

## Architecture

The processor maps numbers to documents.

## Contracts and traps

1. `unresolved-silent` **An unresolved citation renders as nothing.**
   `backend/onyx/chat/citation_utils.py:update_mapping` registers each number.
2. `first-wins` **The first mapping wins.** See [[#unresolved-silent]].

## Dependencies

- [[tools-framework]]: allocates number ranges.

## Recipes

- `citeable-tool` **A new citeable tool.** Follow [[tools-framework#tool-key]].
"""

_TOOLS = """# Tools framework

> Runs tools for the chat loop.

**Verified against:** `{sha}` (2026-10-28)
**Edition:** CE. EE adds
more tools.

## Callers

The chat loop runs tools and gets results. [[citations]] reads tool results.

## Scope

The tool interface and the runner.

## Architecture

`backend/onyx/tools/tool_runner.py:ToolRunner.run` runs each tool.

## Contracts and traps

1. `tool-key` **Each tool has a unique key.** It keeps
   [[citations#first-wins]] true.

## Dependencies

- [[citations]]: registers tool results.
"""

_INDEX = """# Index

## Domain: Core

| Component | What it covers |
|---|---|
| [citations](components/citations.md) | Turns retrieved documents into numbered markers. |
| [tools-framework](components/tools-framework.md) | Runs tools for the chat loop. |

## Common tasks

| Task | Read, in order |
|---|---|
| A new citeable tool | [[tools-framework#tool-key]], [[citations#citeable-tool]] |
"""

_PATHS = """# Paths

## Backend

| Path | Component(s) |
|---|---|
| `backend/onyx/chat/citation_utils.py` | citations |
| `backend/onyx/tools/`, `backend/ee/onyx/tools/` | tools-framework |

## Not mapped

| Path | Reason |
|---|---|
| `backend/scripts/` | Developer tooling. |
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


class FixtureMap:
    def __init__(self, root: Path, sha: str) -> None:
        self.root = root
        self.map_dir = root / ".agents/feature-map"
        self.sha = sha

    def doc(self, rel: str) -> Path:
        return self.map_dir / rel

    def edit(self, rel: str, old: str, new: str) -> None:
        path = self.doc(rel)
        text = path.read_text()
        assert old in text, old
        path.write_text(text.replace(old, new))

    def check(self) -> tuple[list[str], list[str]]:
        return check_feature_map.check(self.map_dir, self.root)


@pytest.fixture
def fmap(tmp_path: Path) -> FixtureMap:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    for rel, content in _CODE.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "code")
    sha = _git(tmp_path, "rev-parse", "--short=10", "HEAD")
    fixture = FixtureMap(tmp_path, sha)
    files = {
        "components/citations.md": _CITATIONS.format(sha=sha),
        "components/tools-framework.md": _TOOLS.format(sha=sha),
        "INDEX.md": _INDEX,
        "PATHS.md": _PATHS,
    }
    for rel, content in files.items():
        path = fixture.doc(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return fixture


def test_valid_map_passes(fmap: FixtureMap) -> None:
    assert fmap.check() == ([], [])


_Edit = Callable[[FixtureMap], None]
_CIT = "components/citations.md"
_TOOL = "components/tools-framework.md"


def _swap(rel: str, old: str, new: str) -> _Edit:
    return lambda f: f.edit(rel, old, new)


@pytest.mark.parametrize(
    ("edit", "expected"),
    [
        (_swap(_CIT, "1. `unresolved-silent` ", "1. "), "the contract has no key"),
        (
            _swap(_CIT, "`first-wins`", "`unresolved-silent`"),
            "duplicate key `unresolved-silent`",
        ),
        (
            _swap(_TOOL, "[[citations#first-wins]]", "[[citations#gone]]"),
            "`citations` has no contract or recipe with the key `gone`",
        ),
        (
            _swap(_CIT, "[[#unresolved-silent]]", "[[#missing]]"),
            "`citations` has no contract or recipe with the key `missing`",
        ),
        (
            _swap(_CIT, "See [[#unresolved-silent]]", "See contract 1"),
            "`contract 1` cites a contract by number",
        ),
        (
            _swap(_CIT, "2. `first-wins`", "- `first-wins`"),
            "Contracts and traps holds contract items",
        ),
        (
            _swap(_CIT, "See [[#unresolved-silent]]", "See [[Citations]]"),
            "`[[Citations]]` is not a link",
        ),
        (
            _swap(_CIT, "**Edition:** CE\n", "**Domain:** core\n**Edition:** CE\n"),
            "remove `**Domain:**`",
        ),
        (
            _swap(_CIT, "**Edition:** CE\n", "**Kind:** product\n**Edition:** CE\n"),
            "remove `**Kind:**`",
        ),
        (
            _swap(_CIT, "## User experience", "## Notes"),
            "exactly one of `## User experience`",
        ),
        (
            _swap(_TOOL, "## Callers", "## User experience\n\nA view.\n\n## Callers"),
            "exactly one of `## User experience`",
        ),
        (
            _swap(_CIT, "- `citeable-tool` **A new", "- **A new"),
            "the recipe has no key",
        ),
        (
            _swap(_CIT, "- `citeable-tool` **A new", "- `first-wins` **A new"),
            "duplicate key `first-wins`",
        ),
        (
            _swap(_CIT, "- `citeable-tool` **A new", "**A new"),
            "Recipes holds recipe items",
        ),
        (
            _swap(_CIT, "> Turns retrieved", "> Turns all retrieved"),
            "must repeat the summary in components/citations.md word for word. "
            "Run `python3 .agents/feature-map/check_feature_map.py --fix`.",
        ),
        (
            _swap(
                _CIT, "the number mapping.", "`backend/onyx/chat/citation_utils.py`."
            ),
            "Scope lists the path",
        ),
        (
            _swap(
                _CIT,
                "- [[tools-framework]]: allocates",
                "**Depended on by**\n- [[tools-framework]]: allocates",
            ),
            "Dependencies lists only",
        ),
        (_swap(_CIT, "## Recipes", "## How to add"), "unknown section `## How to add`"),
        (
            _swap("PATHS.md", "| citations |", "| the component that cites |"),
            "is not a list of component slugs",
        ),
        (
            _swap("PATHS.md", "| Developer tooling. |", "| Developer tooling. | x |"),
            "a PATHS.md row has two columns",
        ),
        (
            _swap("PATHS.md", "| `backend/scripts/` |", "| Scripts |"),
            "the row names no backticked path",
        ),
        (
            _swap(
                _TOOL,
                "`backend/onyx/tools/tool_runner.py:ToolRunner.run`",
                "`tools/tool_runner.py:ToolRunner.run`",
            ),
            "matches more than one file: backend/onyx/tools/tool_runner.py, backend/ee/onyx/tools/tool_runner.py",
        ),
        (
            _swap(_TOOL, "ToolRunner.run`", "ToolRunner.stop`"),
            "`stop` is not in backend/onyx/tools/tool_runner.py",
        ),
        (
            _swap(
                _CIT,
                "`backend/onyx/chat/citation_utils.py:update_mapping`",
                "`citation_utils.py:update_mapping`",
            ),
            "`citation_utils.py:update_mapping` does not exist in the repo",
        ),
        (
            _swap(
                "INDEX.md",
                "Runs tools for the chat loop. |",
                "Runs tools for the chat loop. |\n\nTools ship in #12345.",
            ),
            "INDEX.md:10: `#12345` cites a PR",
        ),
        (
            _swap("INDEX.md", "## Common tasks", "## Tasks"),
            "missing the `## Common tasks` table",
        ),
    ],
)
def test_check_reports(fmap: FixtureMap, edit: _Edit, expected: str) -> None:
    edit(fmap)
    errors, _ = fmap.check()
    assert any(expected in error for error in errors), errors


def test_judgment_is_left_to_the_editor(fmap: FixtureMap) -> None:
    fmap.edit(_TOOL, "[[citations]] reads", "The search tool now reads")
    fmap.edit(_CIT, "\n## Scope", "\n" + "Detail.\n" * 400 + "\n## Scope")
    fmap.edit(
        _CIT,
        "The processor maps numbers to documents.",
        "The processor maps numbers to documents.\n\n```\n"
        "loop --> chat/citation_utils.py:update_mapping --> gone/missing.py\n```",
    )
    assert fmap.check() == ([], [])


def test_not_mapped_row_needs_only_a_reason(fmap: FixtureMap) -> None:
    fmap.edit("PATHS.md", "| Developer tooling. |", "| |")
    errors, _ = fmap.check()
    assert errors == ["PATHS.md:14: a `## Not mapped` row needs a reason"]


def test_resolved_short_path_and_plain_ambiguous_path_pass(fmap: FixtureMap) -> None:
    fmap.edit(
        _TOOL,
        "The tool interface and the runner.",
        "The tool interface and the runner. See `chat/citation_utils.py:update_mapping`.",
    )
    fmap.edit(
        _TOOL, "runs each tool.", "runs each tool. Both `tools/tool_runner.py` match."
    )
    assert fmap.check() == ([], [])


def test_verified_commit_off_main_warns(fmap: FixtureMap) -> None:
    _git(fmap.root, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert fmap.check() == ([], [])

    _git(fmap.root, "checkout", "-qb", "topic")
    (fmap.root / "backend/onyx/server/new_api.py").write_text("x = 1\n")
    _git(fmap.root, "commit", "-qam", "topic")
    topic = _git(fmap.root, "rev-parse", "--short=10", "HEAD")
    fmap.edit(_CIT, fmap.sha, topic)
    _, warnings = fmap.check()
    assert len(warnings) == 1
    assert f"`{topic}` is not a commit on origin/main" in warnings[0]


def test_prose_after_the_last_item_belongs_to_no_item() -> None:
    lines = check_feature_map.parse_lines(
        "## Contracts and traps\n\n"
        "1. `a-rule` **A rule.**\n"
        "lazy continuation\n\n"
        "   indented paragraph\n\n"
        "Closing prose.\n\n"
        "## Recipes\n\n"
        "- `a-task` **A task.**\n\n"
        "  1. a step\n\n"
        "Recipe prose.\n"
    )
    keys = {line.text.strip(): line.key for line in lines if line.text.strip()}
    assert keys["lazy continuation"] == "a-rule"
    assert keys["indented paragraph"] == "a-rule"
    assert keys["Closing prose."] is None
    assert keys["1. a step"] == "a-task"
    assert keys["Recipe prose."] is None


def test_fix_writes_index_summaries(fmap: FixtureMap) -> None:
    fmap.edit("INDEX.md", "Runs tools for the chat loop. |", "Old words. |")
    assert check_feature_map.fix(fmap.map_dir)
    assert "| Runs tools for the chat loop. |" in fmap.doc("INDEX.md").read_text()
    assert fmap.check() == ([], [])
    assert not check_feature_map.fix(fmap.map_dir)


def _reminder(fmap: FixtureMap, changed: list[str]) -> str:
    return stale_docs.reminder_text(changed, None, fmap.map_dir, fmap.root)


def _entry(text: str, name: str) -> str:
    """The lines of the brief for one document."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"- {name} "))
    end = next(
        (i for i in range(start + 1, len(lines)) if not lines[i].startswith("  ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def test_brief_names_owned_files_and_asks_the_questions(fmap: FixtureMap) -> None:
    (fmap.root / "backend/onyx/tools/tool_runner.py").write_text(
        "class ToolRunner:\n    def run(self):\n        return 1\n"
    )
    text = _reminder(fmap, ["backend/onyx/tools/tool_runner.py"])
    tools = _entry(text, "tools-framework")
    assert "Owns: backend/onyx/tools/tool_runner.py" in tools
    assert "Read: Architecture" in tools
    assert "1. Is anything there now wrong?" in text
    assert "4. If you add text, what does it replace?" in text
    assert "No update is a normal answer:" in text
    assert "README.md#editing-judgment" in text


def test_symbol_citation_matches_only_a_change_to_that_symbol(
    fmap: FixtureMap,
) -> None:
    runner = fmap.root / "backend/onyx/tools/tool_runner.py"
    fmap.edit(
        _CIT,
        "**The first mapping wins.**",
        "**The first mapping wins.** `backend/onyx/tools/tool_runner.py:ToolRunner.run`",
    )
    runner.write_text(
        "import os\n\nclass ToolRunner:\n    def run(self):\n        pass\n"
    )
    assert "- citations " not in _reminder(fmap, [str(runner.relative_to(fmap.root))])

    runner.write_text("class ToolRunner:\n    def run(self):\n        return 1\n")
    text = _reminder(fmap, ["backend/onyx/tools/tool_runner.py"])
    assert "Read: Contracts and traps: `first-wins`" in _entry(text, "citations")
    # Documents with a symbol match come first.
    assert text.index("- citations ") < text.index("- tools-framework ")


def test_bare_path_citation_matches_any_change(fmap: FixtureMap) -> None:
    fmap.edit(
        _CIT,
        "The processor maps numbers to documents.",
        "The processor maps numbers to documents in `tools/tool_runner.py`.",
    )
    (fmap.root / "backend/onyx/tools/tool_runner.py").write_text(
        "import os\n\nclass ToolRunner:\n    def run(self):\n        pass\n"
    )
    text = _reminder(fmap, ["backend/onyx/tools/tool_runner.py"])
    assert "Read: Architecture" in _entry(text, "citations")


def test_prose_after_contracts_is_not_named_as_a_contract(fmap: FixtureMap) -> None:
    fmap.edit(
        _CIT,
        "See [[#unresolved-silent]].\n",
        "See [[#unresolved-silent]].\n\nTraps in `backend/onyx/server/new_api.py`.\n",
    )
    text = _reminder(fmap, ["backend/onyx/server/new_api.py"])
    entry = _entry(text, "citations")
    assert "Read: Contracts and traps" in entry
    assert "`first-wins`" not in entry


def test_recipe_citation_names_the_recipe_key(fmap: FixtureMap) -> None:
    fmap.edit(
        _CIT, "Follow [[tools-framework#tool-key]].", "Edit `chat/citation_utils.py`."
    )
    text = _reminder(fmap, ["backend/onyx/chat/citation_utils.py"])
    assert "Recipes: `citeable-tool`" in _entry(text, "citations")


def test_brief_skips_documents_the_turn_changed(fmap: FixtureMap) -> None:
    text = _reminder(
        fmap,
        [
            "backend/onyx/chat/citation_utils.py",
            ".agents/feature-map/components/citations.md",
        ],
    )
    assert text == ""


_RUN_CHANGED = "class ToolRunner:\n    def run(self):\n        return 1\n"


@pytest.mark.parametrize("renamed", [False, True])
def test_brief_gives_size_and_branch_growth(fmap: FixtureMap, renamed: bool) -> None:
    _git(fmap.root, "add", ".")
    _git(fmap.root, "commit", "-qm", "map")
    _git(fmap.root, "checkout", "-qb", "topic")
    rel = _TOOL
    if renamed:
        rel = "components/tools/tools-framework.md"
        fmap.doc(rel).parent.mkdir()
        _git(
            fmap.root,
            "mv",
            f".agents/feature-map/{_TOOL}",
            f".agents/feature-map/{rel}",
        )
    fmap.edit(rel, "runs each tool.", "runs each tool.\n\nOne.\nTwo.")
    (fmap.root / "backend/onyx/tools/tool_runner.py").write_text(_RUN_CHANGED)
    text = _reminder(fmap, ["backend/onyx/tools/tool_runner.py"])
    size = fmap.doc(rel).read_text().count("\n")
    assert f"; {size} lines, +3 on this branch)" in _entry(text, "tools-framework")


def test_ownership_alone_does_not_brief(fmap: FixtureMap) -> None:
    runner = fmap.root / "backend/onyx/tools/tool_runner.py"
    # A change outside the cited `ToolRunner.run`.
    runner.write_text("import os\n\n" + _CODE["backend/onyx/tools/tool_runner.py"])
    assert _reminder(fmap, ["backend/onyx/tools/tool_runner.py"]) == ""
    text = _reminder(
        fmap,
        ["backend/onyx/tools/tool_runner.py", "backend/onyx/server/new_api.py"],
    )
    assert "- tools-framework " not in text
    assert "also own changed code, but no part cites it: tools-framework." in text
    assert "Read only" not in text


def test_diagram_in_a_fence_cites_its_section(fmap: FixtureMap) -> None:
    fmap.edit(
        _TOOL,
        "`backend/onyx/tools/tool_runner.py:ToolRunner.run` runs each tool.",
        "```\nloop --> tools/tool_runner.py:ToolRunner.run --> gone/missing.py\n```",
    )
    runner = fmap.root / "backend/onyx/tools/tool_runner.py"
    runner.write_text("import os\n\n" + _CODE["backend/onyx/tools/tool_runner.py"])
    assert _reminder(fmap, ["backend/onyx/tools/tool_runner.py"]) == ""
    runner.write_text(_RUN_CHANGED)
    text = _reminder(fmap, ["backend/onyx/tools/tool_runner.py"])
    assert "Read: Architecture" in _entry(text, "tools-framework")


def test_brief_names_unmapped_files_and_not_mapped_reasons(fmap: FixtureMap) -> None:
    text = _reminder(
        fmap,
        [
            "backend/onyx/server/new_api.py",
            "backend/scripts/dev.py",
            "backend/tests/unit/test_x.py",
        ],
    )
    assert "No PATHS.md row covers backend/onyx/server/new_api.py." in text
    assert (
        "`backend/scripts` is under `## Not mapped`. Reason: Developer tooling." in text
    )
    assert "test_x.py" not in text


def test_brief_skips_files_with_no_behaviour(fmap: FixtureMap) -> None:
    (fmap.root / "backend/onyx/server/__init__.py").write_text("# package\n")
    (fmap.root / "backend/onyx/server/LICENSE").write_text("MIT\n")
    changed = ["backend/onyx/server/__init__.py", "backend/onyx/server/LICENSE"]
    assert _reminder(fmap, changed) == ""
    (fmap.root / "backend/onyx/server/__init__.py").write_text("import os\n")
    assert "__init__.py" in _reminder(fmap, changed)


def test_brief_names_a_new_untracked_file(fmap: FixtureMap) -> None:
    (fmap.root / "backend/onyx/server/brand_new.py").write_text("")
    text = _reminder(fmap, ["backend/onyx/server/brand_new.py"])
    assert "No PATHS.md row covers backend/onyx/server/brand_new.py." in text


def test_brief_skips_a_deleted_unmapped_file(fmap: FixtureMap) -> None:
    _git(fmap.root, "rm", "-q", "backend/onyx/server/new_api.py")
    assert _reminder(fmap, ["backend/onyx/server/new_api.py"]) == ""


def test_longer_not_mapped_row_wins(fmap: FixtureMap) -> None:
    fmap.edit(
        "PATHS.md",
        "| `backend/scripts/` | Developer tooling. |",
        "| `backend/scripts/` | Developer tooling. |\n"
        "| `backend/onyx/tools/tool_runner.py` | Generated. |",
    )
    assert _reminder(fmap, ["backend/onyx/tools/tool_runner.py"]) == ""
    (fmap.root / "backend/onyx/chat/citation_utils.py").write_text(
        "def update_mapping():\n    return 0\n"
    )
    text = _reminder(
        fmap,
        ["backend/onyx/tools/tool_runner.py", "backend/onyx/chat/citation_utils.py"],
    )
    assert "tools-framework" not in text
    assert "under `## Not mapped`. Reason: Generated." in text
    assert text.count("no longer holds") == 1


def test_not_mapped_reason_alone_prints_nothing(fmap: FixtureMap) -> None:
    assert _reminder(fmap, ["backend/scripts/dev.py"]) == ""


def test_symbols_come_from_uncommitted_edits_before_branch_commits(
    fmap: FixtureMap,
) -> None:
    runner = "backend/onyx/tools/tool_runner.py"
    fmap.edit(
        _CIT,
        "**The first mapping wins.**",
        f"**The first mapping wins.** `{runner}:ToolRunner.run`",
    )
    _git(fmap.root, "add", ".")
    _git(fmap.root, "commit", "-qm", "map")
    _git(fmap.root, "checkout", "-qb", "topic")
    (fmap.root / runner).write_text(
        "class ToolRunner:\n    def run(self):\n        return 1\n"
    )
    _git(fmap.root, "commit", "-qam", "change run")
    # Committed on the branch: compared with the branch base.
    assert "`first-wins`" in _reminder(fmap, [runner])
    (fmap.root / runner).write_text(
        "import os\n\nclass ToolRunner:\n    def run(self):\n        return 1\n"
    )
    # Uncommitted: only this edit counts, and it is outside `run`.
    assert "- citations " not in _reminder(fmap, [runner])


def test_brief_names_each_key_once_per_session(
    fmap: FixtureMap, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(stale_docs.tempfile, "gettempdir", lambda: str(tmp_path))
    fmap.edit(
        _TOOL,
        "It keeps",
        "`backend/onyx/tools/tool_runner.py:ToolRunner.stop` keeps it, and it keeps",
    )
    runner = fmap.root / "backend/onyx/tools/tool_runner.py"
    stop = "\n    def stop(self):\n        pass\n"
    runner.write_text(_CODE["backend/onyx/tools/tool_runner.py"] + stop)
    _git(fmap.root, "commit", "-qam", "add stop")
    runner.write_text(_RUN_CHANGED + stop)
    changed = ["backend/onyx/tools/tool_runner.py", "backend/scripts/dev.py"]
    first = stale_docs.reminder_text(changed, "s1", fmap.map_dir, fmap.root)
    assert "Read: Architecture" in _entry(first, "tools-framework")
    assert "Not mapped" in first
    assert stale_docs.reminder_text(changed, "s1", fmap.map_dir, fmap.root) == ""

    # A later change to another contract of the same document is still briefed.
    runner.write_text(_RUN_CHANGED + stop.replace("pass", "return 2"))
    second = stale_docs.reminder_text(changed, "s1", fmap.map_dir, fmap.root)
    entry = _entry(second, "tools-framework")
    assert "Read: Contracts and traps: `tool-key`" in entry
    assert "Architecture" not in entry
    assert "Not mapped" not in second


def test_enclosing_names() -> None:
    python = (
        "LIMIT = 3\n\n"
        "class Model:\n"
        "    column: int = field(\n"
        "        default=1,\n"
        "    )\n\n"
        "    @property\n"
        "    def run(self):\n"
        "        return 1\n"
    )
    names = stale_docs.enclosing_names
    assert names(python, {1}, "python") == {"LIMIT"}
    assert names(python, {5}, "python") == {"Model", "Model.column"}
    assert names(python, {8}, "python") == {"Model", "Model.run"}
    assert names(python, {2}, "python") == set()
    # An attribute target binds no name; unpacking binds each name.
    assert names("settings.LIMIT = 1\nA, *B = 1, 2\n", {1, 2}, "python") == {"A", "B"}
    typescript = (
        "export class Store {\n"
        "  async load(id: string): Promise<void> {\n"
        "    if (id) {\n"
        "      go();\n"
        "    }\n"
        "  }\n"
        "}\n\n"
        "export function useThing() {\n"
        "  const local = () => {\n"
        "    run();\n"
        "  };\n"
        "}\n"
    )
    assert names(typescript, {4}, "typescript") == {"Store", "Store.load"}
    # A function-valued local is a definition; a multiline signature opens one.
    assert names(typescript, {11}, "typescript") == {"useThing", "useThing.local"}
    multiline = "class A {\n  run(\n    id: string,\n  ): void {\n    go();\n  }\n}\n"
    assert names(multiline, {5}, "typescript") == {"A", "A.run"}
    assert stale_docs.symbol_matches("run", {"Model", "Model.run"})
    assert not stale_docs.symbol_matches("Model.column", {"Model", "Model.run"})


def test_cited_prints_contract_and_recipe_keys(fmap: FixtureMap) -> None:
    fmap.edit(_CIT, "Follow [[tools-framework#tool-key]].", "Edit `scripts/dev.py`.")
    output = stale_docs.format_cited(
        [
            "backend/onyx/chat/citation_utils.py",
            "backend/onyx/tools/tool_runner.py",
            "backend/scripts/dev.py",
            "backend/onyx/server/new_api.py",
        ],
        fmap.map_dir,
        fmap.root,
    )
    assert output.splitlines() == [
        "backend/onyx/chat/citation_utils.py: [[citations#unresolved-silent]]",
        "backend/onyx/tools/tool_runner.py: [[tools-framework]]",
        "backend/scripts/dev.py: [[citations#citeable-tool]]",
        "backend/onyx/server/new_api.py: not cited",
    ]


def test_queue_orders_by_cited_code_churn(fmap: FixtureMap) -> None:
    (fmap.root / "backend/onyx/tools/tool_runner.py").write_text(
        "class ToolRunner:\n    def run(self):\n        return 1\n\n\nX = 2\n"
    )
    (fmap.root / "backend/onyx/chat/citation_utils.py").write_text(
        "def update_mapping():\n    return 0\n"
    )
    _git(fmap.root, "commit", "-qam", "churn")
    rows = stale_docs.queue(fmap.map_dir, fmap.root)
    assert [row.split()[1] for row in rows] == ["tools-framework", "citations"]
    assert "1 of 1 cited files changed since" in rows[0]


def test_brief_shows_every_key_and_file_and_records_only_those(
    fmap: FixtureMap, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(stale_docs.tempfile, "gettempdir", lambda: str(tmp_path))
    extra = "".join(
        f"{n}. `rule-{n}` **Rule {n}.** `chat/citation_utils.py` holds it.\n"
        for n in range(3, 11)
    )
    fmap.edit(
        _CIT, "See [[#unresolved-silent]].\n", "See [[#unresolved-silent]].\n" + extra
    )
    (fmap.root / "backend/onyx/chat/citation_utils.py").write_text(
        "def update_mapping():\n    return 0\n"
    )
    new_files = [f"backend/onyx/server/new_{n}.py" for n in range(5)]
    for path in new_files:
        (fmap.root / path).write_text("")
    changed = ["backend/onyx/chat/citation_utils.py", *new_files]
    first = stale_docs.reminder_text(changed, "s1", fmap.map_dir, fmap.root)
    entry = _entry(first, "citations")
    assert all(f"`rule-{n}`" in entry for n in range(3, 11)), entry
    assert "more)" not in first
    assert all(path in first for path in new_files)
    # Everything was printed, so nothing is left to name again.
    assert stale_docs.reminder_text(changed, "s1", fmap.map_dir, fmap.root) == ""


_HOOK_TS = (
    "export function useChatController() {\n"
    "  const stop = useCallback(() => {\n"
    "    abort();\n"
    "  }, []);\n"
    "  const limit = 1;\n"
    "}\n\n"
    "export interface LogoProps {\n"
    "  onyxBranded?: boolean;\n"
    "  size: number;\n"
    "}\n\n"
    "export class Store {\n"
    "  async load(\n"
    "    id: string,\n"
    "  ): Promise<void> {\n"
    "    go(id);\n"
    "  }\n"
    "}\n"
)


@pytest.mark.parametrize(
    ("symbol", "old", "new", "matched"),
    [
        ("stop", "abort();", "abort(1);", True),
        ("stop", "limit = 1", "limit = 2", False),
        ("Store.load", "go(id);", "go(id, 1);", True),
        ("Store.load", "limit = 1", "limit = 2", False),
        # The parser cannot locate an interface member, so any change counts.
        ("LogoProps.onyxBranded", "size: number", "size: string", True),
        ("LogoProps.onyxBranded", "limit = 1", "limit = 2", True),
    ],
)
def test_symbol_citation_falls_back_to_the_file_when_not_located(
    fmap: FixtureMap, symbol: str, old: str, new: str, matched: bool
) -> None:
    rel = "web/src/hooks/useChatController.ts"
    source = fmap.root / rel
    source.parent.mkdir(parents=True)
    source.write_text(_HOOK_TS)
    _git(fmap.root, "add", rel)
    _git(fmap.root, "commit", "-qm", "hook")
    fmap.edit(
        _CIT,
        "**The first mapping wins.**",
        f"**The first mapping wins.** `{rel}:{symbol}`",
    )
    source.write_text(_HOOK_TS.replace(old, new))
    text = _reminder(fmap, [rel])
    assert ("`first-wins`" in text) is matched, text


def test_symbols_compare_with_the_turn_base(fmap: FixtureMap) -> None:
    runner = "backend/onyx/tools/tool_runner.py"
    fmap.edit(
        _CIT,
        "**The first mapping wins.**",
        f"**The first mapping wins.** `{runner}:ToolRunner.run`",
    )
    _git(fmap.root, "add", ".")
    _git(fmap.root, "commit", "-qm", "map")
    turn_base = _git(fmap.root, "rev-parse", "HEAD")
    (fmap.root / runner).write_text(_RUN_CHANGED)
    _git(fmap.root, "commit", "-qam", "change run")
    (fmap.root / runner).write_text("import os\n\n" + _RUN_CHANGED)
    # Without the turn base, only the uncommitted edit outside `run` counts.
    assert "- citations " not in _reminder(fmap, [runner])
    text = stale_docs.reminder_text(
        [runner], None, fmap.map_dir, fmap.root, base=turn_base
    )
    assert "`first-wins`" in _entry(text, "citations")


@pytest.mark.parametrize("new", [None, ""])
def test_package_marker_that_had_code_is_relevant(
    fmap: FixtureMap, new: str | None
) -> None:
    rel = "backend/onyx/server/__init__.py"
    (fmap.root / rel).write_text("from .app import create\n")
    fmap.edit(
        _CIT, "**The first mapping wins.**", f"**The first mapping wins.** `{rel}`"
    )
    _git(fmap.root, "add", ".")
    _git(fmap.root, "commit", "-qm", "package")
    if new is None:
        (fmap.root / rel).unlink()
    else:
        (fmap.root / rel).write_text(new)
    assert "`first-wins`" in _reminder(fmap, [rel])


def test_queue_reads_citations_in_fenced_diagrams(fmap: FixtureMap) -> None:
    fmap.edit(
        _CIT,
        "The processor maps numbers to documents.",
        "The processor maps numbers to documents.\n\n```\n"
        "loop --> server/new_api.py --> done\n```",
    )
    (fmap.root / "backend/onyx/server/new_api.py").write_text("X = 1\n")
    _git(fmap.root, "commit", "-qam", "churn")
    rows = stale_docs.queue(fmap.map_dir, fmap.root)
    assert any("citations (1 of 2 cited files" in row for row in rows), rows


def test_component_link_must_name_the_documents_path(fmap: FixtureMap) -> None:
    fmap.edit("INDEX.md", "(components/citations.md)", "(components/old/citations.md)")
    errors, _ = fmap.check()
    assert any("components/old/citations.md" in error for error in errors), errors

    fmap.edit("INDEX.md", "(components/old/citations.md)", "(components/citations.md)")
    moved = fmap.doc("components/tools/tools-framework.md")
    moved.parent.mkdir()
    fmap.doc(_TOOL).rename(moved)
    fmap.edit(
        "INDEX.md",
        "(components/tools-framework.md)",
        "(components/tools/tools-framework.md)",
    )
    assert fmap.check() == ([], [])


def test_legacy_map_does_not_ask_for_paths_rows(fmap: FixtureMap) -> None:
    (fmap.map_dir / "legacy-schema.txt").write_text("# Old format.\ncitations\n")
    assert _reminder(fmap, ["backend/onyx/server/new_api.py"]) == ""


_ROUTE = (
    "router = APIRouter()\n\n\n"
    "@router.post(\n"
    '    "/search",\n'
    "    dependencies=[Depends(check_token_rate_limits)],\n"
    "    response_model=SearchResponse,\n"
    ")\n"
    "def search() -> None:\n"
    "    pass\n\n\n"
    'IMAGE_GEN_REMINDER = """\n'
    "Use the image tool.\n"
    '""".strip()\n'
)


def _brief_for_symbol(fmap: FixtureMap, symbol: str, old: str, new: str) -> str:
    """The brief after replacing `old` with `new` in a file that a key cites by symbol."""
    rel = "backend/onyx/tools/api.py"
    source = fmap.root / rel
    source.write_text(_ROUTE)
    _git(fmap.root, "add", rel)
    _git(fmap.root, "commit", "-qm", "route")
    fmap.edit(
        _CIT,
        "**The first mapping wins.**",
        f"**The first mapping wins.** `{rel}:{symbol}`",
    )
    assert old in _ROUTE
    source.write_text(_ROUTE.replace(old, new))
    return _reminder(fmap, [rel])


def test_multiline_decorator_change_matches_the_decorated_function(
    fmap: FixtureMap,
) -> None:
    removed = "    dependencies=[Depends(check_token_rate_limits)],\n"
    assert "`first-wins`" in _brief_for_symbol(fmap, "search", removed, "")


def test_decorator_continuation_is_not_an_assignment() -> None:
    line = _ROUTE.splitlines().index("    response_model=SearchResponse,") + 1
    assert stale_docs.enclosing_names(_ROUTE, {line}, "python") == {"search"}


def test_change_in_a_column_zero_string_matches_its_assignment(
    fmap: FixtureMap,
) -> None:
    text = _brief_for_symbol(
        fmap, "IMAGE_GEN_REMINDER", "Use the image tool.", "Never use the image tool."
    )
    assert "`first-wins`" in text


@pytest.mark.parametrize("symbol", ["search", "gone"])
def test_file_that_fails_to_parse_still_briefs(fmap: FixtureMap, symbol: str) -> None:
    text = _brief_for_symbol(fmap, symbol, "    pass\n", "    return (\n")
    assert "`first-wins`" in text


def test_branch_emptied_package_marker_is_relevant_without_a_base(
    fmap: FixtureMap,
) -> None:
    rel = "backend/onyx/server/__init__.py"
    (fmap.root / rel).write_text("from .app import create\n")
    fmap.edit(
        _CIT, "**The first mapping wins.**", f"**The first mapping wins.** `{rel}`"
    )
    _git(fmap.root, "add", ".")
    _git(fmap.root, "commit", "-qm", "package")
    _git(fmap.root, "checkout", "-qb", "topic")
    (fmap.root / rel).write_text("")
    _git(fmap.root, "commit", "-qam", "empty the package marker")
    assert "`first-wins`" in _reminder(fmap, [rel])
