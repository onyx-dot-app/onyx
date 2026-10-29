#!/usr/bin/env python3
"""Tells an agent which parts of the feature map describe the code it changed.

Given the files a turn changed, this prints a short editing brief. For each map
document that cites a changed file, and that the turn did not change, it names the
sections and contract or recipe keys that cite the changed code. A document cites a
file through a backticked path, or through a path or `path:symbol` token inside a
fenced block such as a diagram. A `path:symbol` citation matches only when the
change touches that symbol: a changed line sits in it, by the `def` and `class`
names (Python) or the function, class and top-level declaration names (TypeScript)
around the line. A bare path matches any change to the file, and so does every
citation of a new, deleted or other file.

A component that owns a changed file through PATHS.md (longest prefix wins) but
cites none of the changed code does not cause a brief. When a brief is shown, it
lists those components on one line. The brief also names changed files that no
PATHS.md row covers, and gives the reason of the `## Not mapped` row that covers a
changed file; such a reason alone prints nothing. The brief asks the questions in
README.md "Editing judgment"; no update is a normal answer. The agent Stop hook
(`.agents/hooks/pre_commit_on_stop.py`) runs this; with `--session`, each section
or key of a document, and each file, is named at most once per session.

`--cited` prints the documents and keys that cite the given files, for step 4 of
VERIFYING.md. `--queue` lists the components by how much of their cited code
changed since their Verified-against commit, as a queue for verify passes.

Usage: stale_docs.py [--session ID] FILE [FILE ...]
       stale_docs.py --cited FILE [FILE ...]
       stale_docs.py --queue
"""

import argparse
import fnmatch
import json
import re
import subprocess
import tempfile
from collections.abc import Iterable
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

_MAX_SHOWN = 6
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
_TS_METHOD = re.compile(
    r"^(\s+)(?:(?:public|private|protected|static|readonly|async|override|get|set)"
    r"\s+)*([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\(.*\)\s*(?::[^{]*)?\{\s*$"
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
_FENCE_TOKEN = re.compile(r"[\w./:-]+")
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
        if match and match.group(1) and line.split()[0] in ("const", "let", "var"):
            match = None  # A local variable.
        if match is None and parent == "class":
            match = _TS_METHOD.match(line)
            if match and match.group(2) in _TS_KEYWORDS:
                match = None
    return (len(match.group(1)), match.group(2)) if match else None


def enclosing_names(text: str, wanted: set[int], language: str) -> set[str]:
    """The qualified names of the definitions that hold the wanted lines.

    The definitions on a line's stack all count: a change in `ToolRunner.run`
    gives `ToolRunner` and `ToolRunner.run`.
    """
    comment = "#" if language == "python" else "//"
    stack: list[tuple[int, str, str]] = []  # (indent, name, kind)
    found: set[str] = set()
    decorated = False
    for number, line in enumerate(text.splitlines(), start=1):
        body = line.lstrip()
        if body and not body.startswith((comment, "*", "/*")):
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
        if body and number in wanted:
            found.update(_prefixes(stack))
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


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True)


def branch_base(repo_root: Path) -> str | None:
    """The commit this branch forked from main."""
    for upstream in ("origin/main", "main"):
        result = _run_git(repo_root, "merge-base", "HEAD", upstream)
        if result.returncode == 0:
            return result.stdout.strip()
    return None


def changed_symbols(repo_root: Path, base: str | None, path: str) -> set[str] | None:
    """The names the change to a file touches, or None when the whole file counts.

    Uncommitted edits are compared with HEAD, so earlier commits on the branch do
    not count. A file with no uncommitted edits, such as one the turn committed,
    is compared with the branch base.
    """
    language = _LANGUAGES.get(Path(path).suffix)
    current = repo_root / path
    if language is None or not current.is_file():
        return None
    dirty = _run_git(repo_root, "diff", "--quiet", "HEAD", "--", path).returncode
    ref = "HEAD" if dirty == 1 else base
    if ref is None:
        return None
    old = _run_git(repo_root, "show", f"{ref}:{path}")
    if old.returncode != 0:
        return None  # A new file.
    diff = _run_git(repo_root, "diff", "-U0", ref, "--", path)
    if diff.returncode != 0:
        return None
    old_lines, new_lines = _hunk_lines(diff.stdout)
    new_text = current.read_text(errors="ignore")
    return enclosing_names(old.stdout, old_lines, language) | enclosing_names(
        new_text, new_lines, language
    )


def symbol_matches(symbol: str, changed: set[str]) -> bool:
    """`ToolRunner.run` and `run` both match a change inside `ToolRunner.run`."""
    return any(name == symbol or name.endswith("." + symbol) for name in changed)


# --- ownership and citations -----------------------------------------------


def is_ignored(path: str, repo_root: Path) -> bool:
    if path.startswith(_IGNORED_PREFIXES) or any(m in path for m in _IGNORED_MARKERS):
        return True
    if _NO_BEHAVIOUR.search(path):
        return True
    # A package marker: an `__init__.py` with no code.
    if Path(path).name == "__init__.py":
        file = repo_root / path
        text = file.read_text(errors="ignore") if file.is_file() else ""
        return all(
            not line.strip() or line.lstrip().startswith("#")
            for line in text.splitlines()
        )
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
    return [token.rstrip(".:-") for token in _FENCE_TOKEN.findall(line.text)]


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
    changed: list[str], map_dir: Path = MAP_DIR, repo_root: Path = REPO_ROOT
) -> Findings:
    """The documents the changed files touch, except documents in `changed`."""
    components, top_level = _docs(map_dir)
    repo = _with_changed(repo_paths(repo_root), changed)
    owned = ownership(map_dir, {doc.name for doc in components}, repo)
    cited = citations(components + top_level, repo)
    map_prefix = map_dir.relative_to(repo_root).as_posix() + "/"
    updated = {p.removeprefix(map_prefix) for p in changed if p.startswith(map_prefix)}
    by_name = {doc.name: doc for doc in components}
    base = branch_base(repo_root)

    found: dict[str, Reminder] = {}
    result = Findings()
    for path in changed:
        if is_ignored(path, repo_root):
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
        symbols = changed_symbols(repo_root, base, path)
        for citation in cited[path]:
            by_symbol = citation.symbol is not None and symbols is not None
            if by_symbol and not symbol_matches(
                citation.symbol or "", symbols or set()
            ):
                continue
            current = found.get(citation.doc.rel, Reminder(citation.doc))
            found[citation.doc.rel] = _add_place(current, citation, by_symbol)
    kept = [r for rel, r in sorted(found.items()) if rel not in updated]
    # Documents with symbol matches first: they are the most likely to need an edit.
    result.reminders.extend(
        sorted(kept, key=lambda r: not any(by_symbol for _, _, by_symbol in r.places))
    )
    return result


# --- output ----------------------------------------------------------------


def _shown(items: list[str], limit: int = _MAX_SHOWN) -> str:
    more = len(items) - limit
    return ", ".join(items[:limit]) + (f" (+{more} more)" if more > 0 else "")


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
    # Symbol matches first, so truncation keeps the most relevant places.
    places = sorted(reminder.places, key=lambda p: not p[2])
    by_section: dict[str, list[str]] = {}
    for place, section, _ in places:
        label = section or "header"
        entries = by_section.setdefault(label, [])
        if place != label:
            entries.append(place)
    parts = [
        f"{section}: {_shown(keys)}" if keys else section
        for section, keys in by_section.items()
    ]
    lines = [head]
    if parts:
        lines.append(f"  Read: {'; '.join(parts[:_MAX_SHOWN])}")
    if reminder.owned:
        lines.append(f"  Owns: {_shown(list(reminder.owned), 3)}")
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
) -> str:
    """The editing brief for the changed files; empty when nothing applies."""
    findings = find(changed, map_dir, repo_root)
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
            f"{_shown(owners)}."
        )
    if findings.unmapped:
        lines.append(
            f"No PATHS.md row covers {_shown(findings.unmapped, 3)}. Add a row for "
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
    rows: list[tuple[int, str]] = []
    for doc in components:
        match = VERIFIED_LINE.search(doc.text)
        files = sorted(
            {
                path
                for token in CODE_SPAN.findall(doc.text)
                for path in cited_files(token, repo)
            }
        )
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
    text = reminder_text(args.files, args.session)
    if text:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
