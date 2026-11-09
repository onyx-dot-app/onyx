#!/usr/bin/env python3
"""Tells an agent which parts of the feature map describe the code it changed.

Given the files a turn changed, this prints a short editing brief. For each map
document that cites a changed file, and that the turn did not change, it names the
sections and contract or recipe keys that cite the changed code. A document cites a
file through a backticked path, or through a path or `path:symbol` token inside a
fenced block such as a diagram. A `path:symbol` citation is skipped only when
the parser finds the symbol's definition in the old or new file and no changed
line sits in it. Definitions are the `def`, `class` and module- or class-level
assignment names (Python, from `ast`; a definition starts at its first decorator)
and the function, class, method, declaration and function-valued `const` or `let`
names (TypeScript). Python text that does not parse uses indentation and line
patterns. A symbol the parser cannot find, such as an interface member,
matches any change to the file, as does a bare path and every citation of a new,
deleted or other file. The change is the diff from `--base` (the commit at the
start of the agent's turn) to the working tree. Without `--base`, it is the
uncommitted diff, or the branch diff for a file with no uncommitted edits. A
file with a `--start-blob` (its content at the start of the turn, when it was
already dirty then) is measured from that content instead, so edits made before
the turn do not count.

A component that owns a changed file through PATHS.md (longest prefix wins) but
cites none of the changed code does not cause a brief. When a brief is shown, it
lists those components on one line. The brief also names changed files that no
PATHS.md row covers, and gives the reason of the `## Not mapped` row that covers a
changed file; such a reason alone prints nothing. The brief asks the questions in
README.md "Editing judgment"; no update is a normal answer. The brief names every
match. The agent Stop hook (`.agents/hooks/pre_commit_on_stop.py`) runs this; with
`--session`, each section or key of a document, and each file, is named at most
once per session.

`--cited` prints the documents and keys that cite the given files, for step 4 of
VERIFYING.md. `--queue` lists the components by how much of their cited code
changed since their Verified-against commit, as a queue for verify passes.

Usage: stale_docs.py [--session ID] [--base COMMIT] [--start-blob PATH=BLOB ...]
                      FILE [FILE ...]
       stale_docs.py --cited FILE [FILE ...]
       stale_docs.py --queue
"""

import argparse
import ast
import difflib
import fnmatch
import json
import re
import subprocess
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from check_feature_map import (
    CODE_SPAN,
    MAP_DIR,
    REPO_ROOT,
    SYMBOL_REFERENCE,
    VERIFIED_LINE,
    Doc,
    Line,
    Repo,
    cited_files,
    load_components,
    load_top_level,
    parent_dirs,
    paths_rows,
    repo_paths,
    resolve_token,
)

# Changes here never alter what a map document states.
_IGNORED_PREFIXES = (".agents/", "backend/tests/", "web/tests/", "mobile/e2e/")
_IGNORED_MARKERS = ("/tests/", "/__tests__/", ".test.", ".spec.")
# Files with no behaviour of their own.
_NO_BEHAVIOUR = re.compile(
    r"(^|/)(py\.typed|\.gitkeep|\.keep|(LICEN[CS]E|NOTICE|COPYING)[^/]*)$"
)
_JUDGMENT = ".agents/feature-map/README.md#editing-judgment"


@dataclass(frozen=True)
class Owner:
    """A PATHS.md prefix with its components, or the reason of a `## Not mapped` row."""

    prefix: str
    components: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class Citation:
    doc: Doc
    section: str | None
    key: str | None
    """The contract or recipe key, when the citation sits in one."""
    symbol: str | None
    """The symbol of a `path:symbol` citation."""

    @property
    def place(self) -> str:
        return f"`{self.key}`" if self.key else self.section or "header"


@dataclass(frozen=True)
class Reminder:
    """What one document owns or cites among the changed files."""

    doc: Doc
    owned: tuple[str, ...] = ()
    places: tuple[tuple[str, str | None, bool], ...] = ()
    """(place, section, matched by symbol) for each cited section or key."""


# --- changed symbols -------------------------------------------------------

_PY_DEF = re.compile(r"^(\s*)(?:async\s+def|def|class)\s+([A-Za-z_]\w*)")
_PY_ASSIGN = re.compile(r"^(\s*)([A-Za-z_]\w*)\s*(?::[^=]*)?=(?!=)")
_TS_DEF = re.compile(
    r"^(\s*)(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?"
    r"(?:async\s+)?(?:function\*?|class|interface|type|enum|const|let|var)\s+"
    r"([A-Za-z_$][\w$]*)"
)
# A method whose signature ends on this line with `{`, or continues on later lines.
_TS_METHOD = re.compile(
    r"^(\s+)(?:(?:public|private|protected|static|readonly|async|override|get|set)"
    r"\s+)*([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\((?:.*\)\s*(?::[^{]*)?\{|[^)]*)\s*$"
)
# The value of a local `const` or `let` that names a function.
_TS_FUNCTION_VALUE = re.compile(
    r"=\s*(?:async\s+)?(?:function\b|\(|[A-Za-z_$][\w$]*\s*=>|useCallback\s*\()"
)
_TS_KEYWORDS = frozenset(
    {"if", "for", "while", "switch", "catch", "return", "function", "with", "do"}
)
_LANGUAGES = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "typescript",
    ".jsx": "typescript",
    ".mjs": "typescript",
}
# A path or `path:symbol` token in a fenced block, such as a diagram.
# Parentheses stay in a token so a route group such as `(app)/` survives; the
# path reader drops unbalanced ones. The words between parentheses count too.
_FENCE_TOKEN = re.compile(r"[\w./():-]+")
_FENCE_WORD = re.compile(r"[\w./:-]+")
_BACKTICK = re.compile(r"(?<!\\)`")
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


def _definition(line: str, language: str, parent: str | None) -> tuple[int, str] | None:
    """(indent, name) when the line opens a definition."""
    if language == "python":
        match = _PY_DEF.match(line)
        # A module constant or a class attribute, such as a model column.
        if match is None and parent in (None, "class"):
            match = _PY_ASSIGN.match(line)
    else:
        match = _TS_DEF.match(line)
        if (
            match
            and match.group(1)
            and line.split()[0] in ("const", "let", "var")
            and not _TS_FUNCTION_VALUE.search(line, match.end())
        ):
            match = None  # A local variable that is not a function.
        if match is None and parent == "class":
            match = _TS_METHOD.match(line)
            if match and match.group(2) in _TS_KEYWORDS:
                match = None
    return (len(match.group(1)), match.group(2)) if match else None


def _statements(node: ast.AST) -> Iterator[ast.stmt]:
    """The statements directly inside a node, through `except` and `case` clauses."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.stmt):
            yield child
        elif isinstance(child, (ast.excepthandler, ast.match_case)):
            yield from _statements(child)


def _target_names(target: ast.expr) -> list[str]:
    """The names a target binds; `a, *b` binds both, `obj.attr` binds none."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for item in target.elts for name in _target_names(item)]
    return []


def _assigned_names(node: ast.stmt) -> list[str]:
    if isinstance(node, ast.Assign):
        return [name for target in node.targets for name in _target_names(target)]
    if isinstance(node, ast.AnnAssign):
        return _target_names(node.target)
    return []


def _python_spans(
    node: ast.AST, prefix: str, in_function: bool
) -> Iterator[tuple[str, int, int]]:
    """(qualified name, first line, last line) of each definition under a node.

    A definition starts at its first decorator. Assignments count at module and
    class level only.
    """
    for child in _statements(node):
        end = child.end_lineno or child.lineno
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = prefix + child.name
            start = min([d.lineno for d in child.decorator_list] + [child.lineno])
            yield name, start, end
            is_function = not isinstance(child, ast.ClassDef)
            yield from _python_spans(child, name + ".", is_function)
        elif not in_function and (names := _assigned_names(child)):
            yield from ((prefix + name, child.lineno, end) for name in names)
        else:
            # A block such as `if` or `try`: its definitions keep the scope.
            yield from _python_spans(child, prefix, in_function)


def enclosing_names(text: str, wanted: set[int], language: str) -> set[str]:
    """The qualified names of the definitions that hold the wanted lines.

    Nested definitions all count: a change in `ToolRunner.run` gives `ToolRunner`
    and `ToolRunner.run`. Blank lines count for no definition.
    """
    lines = text.splitlines()
    wanted = {n for n in wanted if 0 < n <= len(lines) and lines[n - 1].strip()}
    if language == "python":
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            pass  # Text that does not parse uses the line patterns below.
        else:
            return {
                name
                for name, start, end in _python_spans(tree, "", False)
                if any(start <= n <= end for n in wanted)
            }
    return _names_by_indent(lines, wanted, language)


def _names_by_indent(lines: list[str], wanted: set[int], language: str) -> set[str]:
    """`enclosing_names` from line patterns and indentation."""
    comment = "#" if language == "python" else "//"
    stack: list[tuple[int, str, str]] = []  # (indent, name, kind)
    found: set[str] = set()
    decorated = False
    # A line inside a multiline template literal is text, not code: it keeps the
    # enclosing definition open whatever its indent.
    in_template = False
    for number, line in enumerate(lines, start=1):
        body = line.lstrip()
        if in_template:
            pass
        elif body and not body.startswith((comment, "*", "/*")):
            indent = len(line) - len(body)
            # A closing bracket at the indent of its opener stays inside it.
            closing = body[0] in ")]}"
            while stack and (
                stack[-1][0] > indent or (stack[-1][0] == indent and not closing)
            ):
                stack.pop()
            parent = stack[-1][2] if stack else None
            definition = _definition(line, language, parent)
            if definition:
                kind = "class" if re.search(r"\bclass\s", line) else "def"
                stack.append((definition[0], definition[1], kind))
                if decorated:
                    found.update(_prefixes(stack))
                decorated = False
            elif body.startswith("@") and number in wanted:
                decorated = True
        if number in wanted:
            found.update(_prefixes(stack))
        if language != "python" and len(_BACKTICK.findall(line)) % 2:
            in_template = not in_template
    return found


def _prefixes(stack: list[tuple[int, str, str]]) -> set[str]:
    names = [name for _, name, _ in stack]
    return {".".join(names[: i + 1]) for i in range(len(names))}


def _hunk_lines(diff: str) -> tuple[set[int], set[int]]:
    """(old lines, new lines) that the hunks of a `-U0` diff touch."""
    old: set[int] = set()
    new: set[int] = set()
    for match in _HUNK.finditer(diff):
        for start, count, lines in (
            (match.group(1), match.group(2), old),
            (match.group(3), match.group(4), new),
        ):
            # An empty side (a pure insertion or deletion) touches no line there.
            first, size = int(start), int(1 if count is None else count)
            lines.update(range(first, first + size))
    return old, new


def _diff_lines(old_text: str, new_text: str) -> tuple[set[int], set[int]]:
    """`_hunk_lines` for two texts: the old and new lines a line diff changes."""
    old: set[int] = set()
    new: set[int] = set()
    matcher = difflib.SequenceMatcher(
        None, old_text.splitlines(), new_text.splitlines(), autojunk=False
    )
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag != "equal":
            old.update(range(old_start + 1, old_end + 1))
            new.update(range(new_start + 1, new_end + 1))
    return old, new


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True)


def branch_base(repo_root: Path) -> str | None:
    """The commit this branch forked from main."""
    for upstream in ("origin/main", "main"):
        result = _run_git(repo_root, "merge-base", "HEAD", upstream)
        if result.returncode == 0:
            return result.stdout.strip()
    return None


@dataclass(frozen=True)
class SymbolChange:
    changed: frozenset[str]
    """The names whose definitions hold a changed line."""
    defined: frozenset[str]
    """Every name the parser found in the old or new file."""


def _all_names(text: str, language: str) -> set[str]:
    return enclosing_names(text, set(range(1, text.count("\n") + 2)), language)


def _old_text(repo_root: Path, ref: str, path: str) -> str | None:
    """The file at `ref`; None when it is not there."""
    old = _run_git(repo_root, "show", f"{ref}:{path}")
    return old.stdout if old.returncode == 0 else None


def _blob_text(repo_root: Path, blob: str) -> str | None:
    """The text of a start blob; empty for a file that did not exist; None if lost."""
    if not blob:
        return ""
    old = _run_git(repo_root, "cat-file", "blob", blob)
    return old.stdout if old.returncode == 0 else None


def changed_symbols(
    repo_root: Path, ref: str | None, path: str, start_blob: str | None = None
) -> SymbolChange | None:
    """The names the change to a file touches, or None when the whole file counts.

    With a start blob (the file's content at the turn's start, or "" when the file
    did not exist), the change is measured from that content instead of `ref`.
    """
    language = _LANGUAGES.get(Path(path).suffix)
    current = repo_root / path
    if language is None or not current.is_file():
        return None
    new_text = current.read_text(errors="ignore")
    if start_blob is not None:
        old_text = _blob_text(repo_root, start_blob)
        if old_text is None:
            return None
        old_lines, new_lines = _diff_lines(old_text, new_text)
    else:
        if ref is None:
            return None
        old_text = _old_text(repo_root, ref, path)
        if old_text is None:
            return None  # A new file.
        diff = _run_git(repo_root, "diff", "-U0", ref, "--", path)
        if diff.returncode != 0:
            return None
        old_lines, new_lines = _hunk_lines(diff.stdout)
    return SymbolChange(
        frozenset(
            enclosing_names(old_text, old_lines, language)
            | enclosing_names(new_text, new_lines, language)
        ),
        frozenset(_all_names(old_text, language) | _all_names(new_text, language)),
    )


def diff_ref(
    repo_root: Path, path: str, base: str | None, fork: str | None
) -> str | None:
    """The commit a file's change is measured from.

    With a turn base, that base. Otherwise HEAD for a file with uncommitted edits,
    so earlier commits on the branch do not count, and the branch fork point for a
    file with none.
    """
    if base is not None:
        return base
    dirty = _run_git(repo_root, "diff", "--quiet", "HEAD", "--", path).returncode
    return "HEAD" if dirty == 1 else fork


def symbol_matches(symbol: str, names: Iterable[str]) -> bool:
    """`ToolRunner.run` and `run` both match the name `ToolRunner.run`."""
    return any(name == symbol or name.endswith("." + symbol) for name in names)


# --- ownership and citations -----------------------------------------------


def _has_code(text: str) -> bool:
    return any(
        line.strip() and not line.lstrip().startswith("#") for line in text.splitlines()
    )


def is_ignored(
    path: str, repo_root: Path, ref: str | None, start_blob: str | None = None
) -> bool:
    """True when the change cannot alter what the map states.

    `ref` is the commit the change is measured from, as `diff_ref` gives it; a
    start blob, as `changed_symbols` takes it, replaces it.
    """
    if path.startswith(_IGNORED_PREFIXES) or any(m in path for m in _IGNORED_MARKERS):
        return True
    if _NO_BEHAVIOUR.search(path):
        return True
    # A package marker: an `__init__.py` with no code before or after the change.
    if Path(path).name == "__init__.py":
        file = repo_root / path
        new = file.read_text(errors="ignore") if file.is_file() else ""
        if start_blob is not None:
            old = _blob_text(repo_root, start_blob) or ""
        else:
            old = (_old_text(repo_root, ref, path) if ref else None) or ""
        return not _has_code(old) and not _has_code(new)
    return False


def _with_changed(repo: Repo, changed: list[str]) -> Repo:
    """The repo with deleted files kept, so their rows and citations still match."""
    return Repo(repo.root, repo.files | set(changed), repo.dirs | parent_dirs(changed))


def ownership(map_dir: Path, names: set[str], repo: Repo) -> tuple[Owner, ...]:
    rows: list[Owner] = []
    for row in paths_rows((map_dir / "PATHS.md").read_text()):
        if row.columns != 2:
            continue
        components: tuple[str, ...] = ()
        reason = ""
        if row.not_mapped:
            reason = row.owner
        else:
            components = tuple(part.strip() for part in row.owner.split(","))
            if not all(part in names for part in components):
                continue
        rows.extend(
            Owner(path, components, reason)
            for token in row.tokens
            for path in resolve_token(token, repo)
        )
    return tuple(rows)


def _matches(path: str, prefix: str) -> bool:
    if "*" in prefix:
        return fnmatch.fnmatch(path, prefix) or fnmatch.fnmatch(path, prefix + "/*")
    return path == prefix or path.startswith(prefix + "/")


def owner_of(path: str, owned: Iterable[Owner]) -> Owner | None:
    """The longest PATHS.md prefix that matches the path, with every owner it names.

    A `## Not mapped` match has no components. None when no row covers the path.
    """
    best: Owner | None = None
    for row in owned:
        if not _matches(path, row.prefix):
            continue
        if best is None or len(row.prefix) > len(best.prefix):
            best = row
        elif len(row.prefix) == len(best.prefix):
            extra = tuple(c for c in row.components if c not in best.components)
            best = replace(best, components=best.components + extra)
    return best


def _tokens(line: Line) -> list[str]:
    """Code spans; inside a fenced block, every word that could be a path too."""
    if not line.in_fence:
        return CODE_SPAN.findall(line.text)
    tokens = _FENCE_TOKEN.findall(line.text) + _FENCE_WORD.findall(line.text)
    return list(dict.fromkeys(token.rstrip(".:-") for token in tokens))


def citations(docs: list[Doc], repo: Repo) -> dict[str, list[Citation]]:
    """Each tracked file to the citations of it, in document order."""
    cited: dict[str, list[Citation]] = {}
    for doc in docs:
        for line in doc.lines:
            for token in _tokens(line):
                symbol_ref = SYMBOL_REFERENCE.match(token)
                symbol = symbol_ref.group(2).strip(".") if symbol_ref else None
                for path in cited_files(token, repo):
                    entry = Citation(doc, line.section, line.key, symbol or None)
                    if entry not in cited.setdefault(path, []):
                        cited[path].append(entry)
    return cited


def _docs(map_dir: Path) -> tuple[list[Doc], list[Doc]]:
    return load_components(map_dir), load_top_level(map_dir)


@dataclass(frozen=True)
class Findings:
    reminders: list[Reminder] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)
    not_mapped: dict[str, str] = field(default_factory=dict)
    """Not-mapped prefix to its reason, for the changed files under it."""


def _add_place(reminder: Reminder, citation: Citation, by_symbol: bool) -> Reminder:
    place = (citation.place, citation.section, by_symbol)
    known = {p for p, _, _ in reminder.places}
    if citation.place in known:
        if not by_symbol:
            return reminder
        # A symbol match outranks an earlier file match of the same place.
        kept = tuple(p for p in reminder.places if p[0] != citation.place)
        return replace(reminder, places=kept + (place,))
    return replace(reminder, places=reminder.places + (place,))


def find(
    changed: list[str],
    map_dir: Path = MAP_DIR,
    repo_root: Path = REPO_ROOT,
    base: str | None = None,
    start_blobs: Mapping[str, str] | None = None,
) -> Findings:
    """The documents the changed files touch, except documents in `changed`.

    `base` is the commit the change is measured from, such as the turn's start.
    `start_blobs` maps a file that was dirty at the turn's start to the blob of
    its content then ("" when it did not exist); its change is measured from that
    content, so edits made before the turn do not count.
    """
    start_blobs = start_blobs or {}
    components, top_level = _docs(map_dir)
    repo = _with_changed(repo_paths(repo_root), changed)
    owned = ownership(map_dir, {doc.name for doc in components}, repo)
    cited = citations(components + top_level, repo)
    map_prefix = map_dir.relative_to(repo_root).as_posix() + "/"
    updated = {p.removeprefix(map_prefix) for p in changed if p.startswith(map_prefix)}
    by_name = {doc.name: doc for doc in components}
    fork = None if base else branch_base(repo_root)

    found: dict[str, Reminder] = {}
    result = Findings()
    for path in changed:
        ref = diff_ref(repo_root, path, base, fork)
        start_blob = start_blobs.get(path)
        if is_ignored(path, repo_root, ref, start_blob):
            continue
        owner = owner_of(path, owned)
        # A deleted file needs no row.
        if owner is None and (repo_root / path).is_file():
            result.unmapped.append(path)
        elif owner is not None and not owner.components:
            result.not_mapped[owner.prefix] = owner.reason
        for name in owner.components if owner else ():
            doc = by_name[name]
            current = found.get(doc.rel, Reminder(doc))
            found[doc.rel] = replace(current, owned=current.owned + (path,))
        if not cited.get(path):
            continue
        symbols = changed_symbols(repo_root, ref, path, start_blob)
        for citation in cited[path]:
            by_symbol = False
            if citation.symbol and symbols is not None:
                if symbol_matches(citation.symbol, symbols.changed):
                    by_symbol = True
                elif symbol_matches(citation.symbol, symbols.defined):
                    continue  # The parser found the symbol; the change is outside it.
            current = found.get(citation.doc.rel, Reminder(citation.doc))
            found[citation.doc.rel] = _add_place(current, citation, by_symbol)
    kept = [r for rel, r in sorted(found.items()) if rel not in updated]
    # Documents with symbol matches first: they are the most likely to need an edit.
    result.reminders.extend(
        sorted(kept, key=lambda r: not any(by_symbol for _, _, by_symbol in r.places))
    )
    return result


# --- output ----------------------------------------------------------------


def branch_growth(repo_root: Path, base: str | None, scope: str) -> dict[str, int]:
    """Net lines each file under `scope` gained on the branch; a rename counts its edits only."""
    if base is None:
        return {}
    result = _run_git(repo_root, "diff", "-M", "--numstat", "-z", base, "--", scope)
    # -z gives `added\tdeleted\tpath`, or `added\tdeleted\t` then old and new path.
    entries = iter(result.stdout.split("\0"))
    growth: dict[str, int] = {}
    for entry in entries:
        parts = entry.split("\t")
        if len(parts) != 3:
            continue
        path = parts[2]
        if not path:
            next(entries, "")
            path = next(entries, "")
        if parts[0].isdigit() and parts[1].isdigit():
            growth[path] = int(parts[0]) - int(parts[1])
    return growth


def format_reminder(reminder: Reminder, repo_rel: str, growth: int) -> str:
    size = reminder.doc.text.count("\n")
    head = f"- {reminder.doc.name} ({repo_rel}; {size} lines"
    head += f", {growth:+d} on this branch)" if growth else ")"
    # Symbol matches first: they are the most likely to need an edit.
    places = sorted(reminder.places, key=lambda p: not p[2])
    by_section: dict[str, list[str]] = {}
    for place, section, _ in places:
        label = section or "header"
        entries = by_section.setdefault(label, [])
        if place != label:
            entries.append(place)
    parts = [
        f"{section}: {', '.join(keys)}" if keys else section
        for section, keys in by_section.items()
    ]
    lines = [head]
    if parts:
        lines.append(f"  Read: {'; '.join(parts)}")
    if reminder.owned:
        lines.append(f"  Owns: {', '.join(reminder.owned)}")
    return "\n".join(lines)


def format_cited(files: list[str], map_dir: Path, repo_root: Path) -> str:
    """Each file with the `[[slug#key]]` items and documents that cite it."""
    components, top_level = _docs(map_dir)
    repo = _with_changed(repo_paths(repo_root), files)
    cited = citations(components + top_level, repo)
    lines: list[str] = []
    for path in files:
        refs = [
            (
                f"[[{c.doc.name}#{c.key}]]"
                if c.key
                else f"[[{c.doc.name}]]"
                if c.doc.is_component
                else c.doc.rel
            )
            for c in cited.get(path, [])
        ]
        lines.append(f"{path}: {', '.join(dict.fromkeys(refs)) or 'not cited'}")
    return "\n".join(lines)


def _already_reminded(session: str) -> tuple[Path, set[str]]:
    record = Path(tempfile.gettempdir()) / f"onyx-feature-map-reminders-{session}.json"
    try:
        return record, set(json.loads(record.read_text()))
    except (OSError, ValueError):
        return record, set()


def _place_key(reminder: Reminder, place: str) -> str:
    return f"place:{reminder.doc.rel}#{place}"


def _owns_key(reminder: Reminder) -> str:
    return f"owns:{reminder.doc.rel}"


def _unseen(reminder: Reminder, reminded: set[str]) -> Reminder:
    """The reminder without the places and ownership the session already named."""
    return replace(
        reminder,
        owned=() if _owns_key(reminder) in reminded else reminder.owned,
        places=tuple(
            p for p in reminder.places if _place_key(reminder, p[0]) not in reminded
        ),
    )


def _filter_session(findings: Findings, reminded: set[str]) -> Findings:
    unseen = (_unseen(r, reminded) for r in findings.reminders)
    return Findings(
        [r for r in unseen if r.places or r.owned],
        [p for p in findings.unmapped if f"unmapped:{p}" not in reminded],
        {
            p: reason
            for p, reason in findings.not_mapped.items()
            if f"not-mapped:{p}" not in reminded
        },
    )


def _record_session(findings: Findings, session: str) -> None:
    """Record what the brief named. The brief prints every entry of `findings`."""
    record, reminded = _already_reminded(session)
    named = (
        {_place_key(r, p[0]) for r in findings.reminders for p in r.places}
        | {_owns_key(r) for r in findings.reminders if r.owned}
        | {f"unmapped:{p}" for p in findings.unmapped}
        | {f"not-mapped:{p}" for p in findings.not_mapped}
    )
    if named - reminded:
        record.write_text(json.dumps(sorted(reminded | named)))


def reminder_text(
    changed: list[str],
    session: str | None,
    map_dir: Path = MAP_DIR,
    repo_root: Path = REPO_ROOT,
    base: str | None = None,
    start_blobs: Mapping[str, str] | None = None,
) -> str:
    """The editing brief for the changed files; empty when nothing applies."""
    findings = find(changed, map_dir, repo_root, base, start_blobs)
    if session:
        findings = _filter_session(findings, _already_reminded(session)[1])
    cited = [r for r in findings.reminders if r.places]
    if not cited and not findings.unmapped:
        # Ownership or a Not-mapped reason is context for a brief, not a reason to
        # stop the agent.
        return ""
    if session:
        _record_session(findings, session)
    lines: list[str] = []
    map_rel = map_dir.relative_to(repo_root).as_posix()
    if cited:
        growth = branch_growth(repo_root, branch_base(repo_root), map_rel)
        lines.append("Feature map: these documents cite code that you changed.")
        lines.extend(
            format_reminder(
                r,
                f"{map_rel}/{r.doc.rel}",
                growth.get(f"{map_rel}/{r.doc.rel}", 0),
            )
            for r in cited
        )
        lines.append(
            "Read only the sections and keys after `Read:`, and the summary. "
            "Then decide:\n"
            "1. Is anything there now wrong?\n"
            "2. Did the change create a rule, trap or decision that a future agent "
            "needs and that the code does not show quickly?\n"
            "3. Does anything there no longer earn its place?\n"
            "4. If you add text, what does it replace?\n"
            "No update is a normal answer: if nothing needs an edit, say so in one "
            "line and finish. Do not rewrite parts the change does not touch. "
            "State what is true; leave history to git. "
            f"See {_JUDGMENT}."
        )
    owners = [r.doc.name for r in findings.reminders if not r.places]
    if owners:
        lines.append(
            "These components also own changed code, but no part cites it: "
            f"{', '.join(owners)}."
        )
    if findings.unmapped:
        lines.append(
            f"No PATHS.md row covers {', '.join(findings.unmapped)}. Add a row for "
            "the component that owns it, or a `## Not mapped` row with the reason."
        )
    lines.extend(
        f"`{prefix}` is under `## Not mapped`. Reason: {reason}"
        for prefix, reason in findings.not_mapped.items()
    )
    if findings.not_mapped:
        lines.append("If a Not-mapped reason no longer holds, map the path.")
    return "\n".join(lines)


def queue(map_dir: Path = MAP_DIR, repo_root: Path = REPO_ROOT) -> list[str]:
    """Components by lines of cited code changed since their Verified-against commit."""
    components, _ = _docs(map_dir)
    repo = repo_paths(repo_root)
    target = (
        "origin/main"
        if _run_git(repo_root, "rev-parse", "-q", "--verify", "origin/main").returncode
        == 0
        else "HEAD"
    )
    cited_by: dict[str, set[str]] = {}
    for path, entries in citations(components, repo).items():
        for entry in entries:
            cited_by.setdefault(entry.doc.rel, set()).add(path)
    rows: list[tuple[int, str]] = []
    for doc in components:
        match = VERIFIED_LINE.search(doc.text)
        files = sorted(cited_by.get(doc.rel, set()))
        if not match or not files:
            continue
        sha = match.group(1)
        result = _run_git(repo_root, "diff", "--numstat", sha, target, "--", *files)
        if result.returncode != 0:
            rows.append((-1, f"{doc.name}: cannot diff from `{sha}`"))
            continue
        stats = [line.split("\t") for line in result.stdout.splitlines()]
        churn = sum(int(a) + int(d) for a, d, _ in stats if a.isdigit() and d.isdigit())
        rows.append(
            (
                churn,
                f"{churn:>6}  {doc.name} ({len(stats)} of {len(files)} cited files "
                f"changed since {sha})",
            )
        )
    return [text for _, text in sorted(rows, key=lambda row: -row[0])]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session")
    parser.add_argument(
        "--base", help="measure the change from this commit, such as the turn's start"
    )
    parser.add_argument(
        "--start-blob",
        action="append",
        default=[],
        metavar="PATH=BLOB",
        help="measure the file's change from this blob, its content at the turn's "
        "start; an empty BLOB means the file did not exist",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--cited",
        action="store_true",
        help="print the documents and keys that cite each file",
    )
    mode.add_argument(
        "--queue",
        action="store_true",
        help="list components by cited-code churn since their Verified-against commit",
    )
    parser.add_argument("files", nargs="*")
    args = parser.parse_args()

    if args.cited:
        print(format_cited(args.files, MAP_DIR, REPO_ROOT))
        return 0
    if args.queue:
        print("\n".join(queue()))
        return 0
    start_blobs = {
        path: blob
        for path, _, blob in (entry.rpartition("=") for entry in args.start_blob)
    }
    text = reminder_text(
        args.files, args.session, base=args.base, start_blobs=start_blobs
    )
    if text:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
