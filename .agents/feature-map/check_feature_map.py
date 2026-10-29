#!/usr/bin/env python3
"""Checks that the feature map is well formed and that every repo path it cites exists.

Runs as a pre-commit hook on every commit, so a PR that renames or deletes a file a
map document cites fails until the document is updated in the same PR.
Intentional non-paths (build outputs, runtime paths, statements that a file does
not exist) go in `path-allowlist.txt`.

It also keeps component documents linkable: a fixed header and fixed sections,
keyed contracts and recipes, no PR numbers or line numbers, and `path:symbol`
references whose symbol exists in the one file they name. Judgment about what a
document should hold lives in README.md, not here. Content inside fenced code
blocks, such as diagrams, is not checked for paths.

`--fix` copies each component's summary into its INDEX.md row.
"""

import argparse
import fnmatch
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import NamedTuple

MAP_DIR = Path(__file__).resolve().parent
REPO_ROOT = MAP_DIR.parent.parent
COMPONENTS = "components"
ALLOWLIST = "path-allowlist.txt"
TOP_LEVEL_DOCS = ("ARCHITECTURE.md", "CROSS-CUTTING.md", "INDEX.md", "GLOSSARY.md")
NOT_MAPPED = "Not mapped"
COMMON_TASKS = "Common tasks"

# A component has exactly one of these as its first section.
FIRST_SECTIONS = ("User experience", "Callers")
# (name, rank, required). Sections of equal rank are alternatives.
SECTIONS = (
    ("User experience", 0, False),
    ("Callers", 0, False),
    ("Scope", 1, True),
    ("Architecture", 2, True),
    ("Contracts and traps", 3, True),
    ("Decisions", 4, False),
    ("Known issues", 5, False),
    ("Dependencies", 6, True),
    ("Recipes", 7, False),
    ("Verification", 8, False),
)
SECTION_RANK = {name: rank for name, rank, _ in SECTIONS}
_FIX_COMMAND = "python3 .agents/feature-map/check_feature_map.py --fix"
SUMMARY_SENTENCES = 2

# A path is a repo-root path or sits under exactly one of these prefixes.
PATH_ROOTS = (
    "",
    "backend/onyx/",
    "backend/ee/onyx/",
    "backend/",
    "web/src/",
    "web/",
    "mobile/src/",
    "widget/src/",
    "desktop/src/",
)

# History belongs in git. A document states what is true at its verified commit.
PR_NUMBER = re.compile(r"(?<![\w/])#\d{4,}\b")
# Contract numbers change when a list is edited. Cite the key instead.
CONTRACT_BY_NUMBER = re.compile(
    r"\b(?:contracts?|traps?|invariants?)\s+#?\d+\b", re.IGNORECASE
)
LINE_REFERENCE = re.compile(r"\.(py|ts|tsx|js|md|ya?ml|sh):\d+")
SYMBOL_REFERENCE = re.compile(
    r"^([\w./()\[\]-]+\.(?:py|ts|tsx|js|mjs|sh)):([A-Za-z_][\w.]*)"
)
VERIFIED_LINE = re.compile(
    r"^\*\*Verified against:\*\* `([0-9a-f]{7,40})` \(\d{4}-\d{2}-\d{2}\)$",
    re.MULTILINE,
)
CODE_SPAN = re.compile(r"`([^`\n]+)`")
FENCE_MARKER = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
# `[[slug]]`, `[[slug#key]]` or `[[#key]]`.
WIKI_LINK = re.compile(r"\[\[([a-z][a-z0-9-]*)?(?:#([^\]\s]*))?\]\]")
ANY_LINK = re.compile(r"\[\[[^\]\n]*\]\]")
SLUG = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
CONTRACTS = "Contracts and traps"
RECIPES = "Recipes"
# A keyed item starts at column 0; group 1 is its key.
ITEM_START = {
    CONTRACTS: re.compile(r"^\d+\.\s+(?:`([^`\n]*)`)?"),
    RECIPES: re.compile(r"^[-*]\s+(?:`([^`\n]*)`)?"),
}
DEPENDENCY_ITEM = re.compile(r"^- \[\[([a-z][a-z0-9-]*)\]\]: \S")
# A component may sit in a subdirectory, such as `components/connectors/outlook.md`.
# Group 1 is the document's path relative to the map directory.
COMPONENT_LINK = re.compile(
    r"\((components/(?:[a-z0-9-]+/)?[a-z0-9-]+\.md)(?:#([a-z0-9-]+))?\)"
)
INDEX_ROW = re.compile(
    r"^\|\s*\[[^\]]+\]\(components/(?:[a-z0-9-]+/)?([a-z0-9-]+)\.md\)\s*\|(.*)\|\s*$"
)
# A Next.js dynamic route segment: `[id]`, `[...path]` or `[[...path]]`.
DYNAMIC_SEGMENT = re.compile(r"\[\[\.\.\.[\w-]+\]\]|\[(?:\.\.\.)?[\w-]+\]")
DYNAMIC_FILE = re.compile(rf"(?:{DYNAMIC_SEGMENT.pattern})(?:\.\w+)*")
PATH_SUFFIX = re.compile(
    r"(\.(py|ts|tsx|js|mjs|json|md|yaml|yml|toml|go|rs|sh|txt|html|css|template|conf)|(^|/)Dockerfile)$"
)


class Line(NamedTuple):
    number: int
    text: str
    section: str | None
    key: str | None
    """The key of the contract or recipe item the line belongs to."""
    in_fence: bool


@dataclass(frozen=True)
class Doc:
    rel: str
    """Path relative to the map directory, such as `components/citations.md`."""
    text: str
    lines: tuple[Line, ...]

    @property
    def name(self) -> str:
        return Path(self.rel).stem

    @property
    def is_component(self) -> bool:
        return self.rel.startswith(COMPONENTS + "/")


@dataclass(frozen=True)
class Repo:
    root: Path
    files: frozenset[str]
    dirs: frozenset[str]

    @cached_property
    def top_dirs(self) -> frozenset[str]:
        return frozenset(d for d in self.dirs if "/" not in d)


@dataclass(frozen=True)
class PathsRow:
    number: int
    tokens: tuple[str, ...]
    owner: str
    not_mapped: bool
    columns: int


def _ends_item(raw: str, after_blank: bool) -> bool:
    """An unindented line after a blank line, a rule or a heading ends a list item."""
    if not raw.strip() or raw[0].isspace():
        return False
    return after_blank or raw.startswith(("---", "#"))


def parse_lines(text: str) -> tuple[Line, ...]:
    """Each line with its `##` section and the key of the item it belongs to.

    Items are the numbered contracts in Contracts and traps and the `-` recipes in
    Recipes. Prose after the last item belongs to no item.
    """
    parsed: list[Line] = []
    section: str | None = None
    key: str | None = None
    fence: str | None = None  # the opening marker, such as "```" or "~~~~"
    after_blank = False
    for number, raw in enumerate(text.splitlines(), start=1):
        marker = FENCE_MARKER.match(raw)
        # CommonMark: only the same character, at least as long, with nothing
        # after it, closes a fence.
        is_fence = bool(marker) and (
            fence is None
            or (
                marker.group(1)[0] == fence[0]
                and len(marker.group(1)) >= len(fence)
                and not marker.group(2).strip()
            )
        )
        if fence is None:
            item = ITEM_START[section].match(raw) if section in ITEM_START else None
            if raw.startswith("## "):
                section, key = raw[3:].strip(), None
            elif item:
                key = item.group(1)
            elif _ends_item(raw, after_blank):
                key = None
        if is_fence and marker:
            fence = None if fence else marker.group(1)
        parsed.append(Line(number, raw, section, key, fence is not None or is_fence))
        after_blank = not raw.strip()
    return tuple(parsed)


def load_doc(map_dir: Path, path: Path) -> Doc:
    text = path.read_text()
    return Doc(path.relative_to(map_dir).as_posix(), text, parse_lines(text))


def load_components(map_dir: Path) -> list[Doc]:
    return [
        load_doc(map_dir, path) for path in sorted((map_dir / COMPONENTS).rglob("*.md"))
    ]


def load_top_level(map_dir: Path) -> list[Doc]:
    return [
        load_doc(map_dir, map_dir / name)
        for name in TOP_LEVEL_DOCS
        if (map_dir / name).is_file()
    ]


def repo_paths(root: Path) -> Repo:
    files = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    return Repo(root, frozenset(files), frozenset(parent_dirs(files)))


def parent_dirs(paths: Iterable[str]) -> set[str]:
    return {
        "/".join(parts[:i])
        for parts in (path.split("/") for path in paths)
        for i in range(1, len(parts))
    }


def candidates(path: str, repo: Repo) -> list[str]:
    """Every tracked file or directory the path names under the documented roots."""
    path = path.rstrip("/")
    found = [
        root + path
        for root in PATH_ROOTS
        if root + path in repo.files or root + path in repo.dirs
    ]
    return list(dict.fromkeys(found))


def looks_like_path(token: str, repo: Repo) -> str | None:
    """The repo path a code span names, or None when it is not a path.

    A token that names a tracked file or directory is a path, whatever characters
    it holds. Otherwise placeholder text such as `connectors/<source>/` is not a
    path; a Next.js dynamic segment such as `[id]` or `[...path]` is not a
    placeholder, so a mistyped route still fails the existence check.
    """
    if any(c.isspace() for c in token):
        return None
    path = token.split(":")[0].rstrip("/").rstrip(",")
    # Keep balanced parentheses: `(app)/index.tsx` is an Expo route group.
    if path.startswith("(") and ")" not in path:
        path = path[1:]
    if path.endswith(")") and "(" not in path:
        path = path[:-1]
    if path.startswith(("http", "/")):
        return None
    # A bare extension such as `.py` names a file type, not a file.
    if "/" not in path and "." not in path.lstrip(".") and path != "Dockerfile":
        return None
    if candidates(path, repo):
        return path
    if any(c in path for c in "{*<$") or "..." in DYNAMIC_SEGMENT.sub("", path):
        return None
    if "[" in path or "]" in path:
        segments = path.split("/")
        if segments[0] not in repo.top_dirs or any(
            ("[" in s or "]" in s) and not DYNAMIC_FILE.fullmatch(s) for s in segments
        ):
            return None
    if PATH_SUFFIX.search(path) or token.endswith("/"):
        return path
    # Log files are runtime output, never tracked.
    if path.split("/")[0] in repo.top_dirs and not path.endswith(".log"):
        return path
    return None


def cited_files(token: str, repo: Repo) -> list[str]:
    """The tracked files a code span cites, by path or by `path:symbol`."""
    path = looks_like_path(token, repo)
    if path is None:
        return []
    return [c for c in candidates(path, repo) if c in repo.files]


def collapse(text: str) -> str:
    return " ".join(text.split())


def section_lines(doc: Doc, name: str) -> list[Line]:
    return [
        line
        for line in doc.lines
        if line.section == name and not line.text.startswith("## ")
    ]


def item_keys(doc: Doc, section: str) -> list[tuple[int, str | None]]:
    """(line number, key) for each item of a keyed section; None when the key is missing."""
    return [
        (line.number, item.group(1))
        for line in section_lines(doc, section)
        if not line.in_fence and (item := ITEM_START[section].match(line.text))
    ]


def link_keys(doc: Doc) -> set[str]:
    """The keys that `[[slug#key]]` can cite: contract and recipe keys."""
    return {key for s in ITEM_START for _, key in item_keys(doc, s) if key}


def read_allowlist(map_dir: Path) -> set[tuple[str, str]]:
    entries: set[tuple[str, str]] = set()
    path = map_dir / ALLOWLIST
    if not path.exists():
        return entries
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        doc, _, token = line.partition(": ")
        entries.add((doc.strip(), token.strip()))
    return entries


def paths_rows(text: str) -> list[PathsRow]:
    """The body rows of every table in PATHS.md. A valid row has two columns."""
    rows: list[PathsRow] = []
    lines = text.splitlines()
    section: str | None = None
    for index, raw in enumerate(lines):
        if raw.startswith("## "):
            section = raw[3:].strip()
            continue
        if not raw.startswith("|"):
            continue
        cells = [cell.strip() for cell in raw.strip().strip("|").split("|")]
        following = lines[index + 1] if index + 1 < len(lines) else ""
        is_separator = all(set(cell) <= set("-: ") for cell in cells)
        is_header = following.startswith("|") and set(following) <= set("|-: ")
        if is_separator or is_header:
            continue
        rows.append(
            PathsRow(
                index + 1,
                tuple(CODE_SPAN.findall(cells[0])),
                cells[1] if len(cells) > 1 else "",
                section == NOT_MAPPED,
                len(cells),
            )
        )
    return rows


def resolve_token(token: str, repo: Repo) -> list[str]:
    """The repo paths a PATHS.md token names.

    A pattern with `*` stays a pattern, so a new file that matches it is covered
    too. It resolves under each documented root where some tracked file matches it.
    """
    path = token.split(":")[0].rstrip("/")
    if "*" not in path:
        return candidates(path, repo)
    literal = path[: path.index("*")].rpartition("/")[0]
    found: list[str] = []
    for root in PATH_ROOTS:
        base = (root + literal).rstrip("/")
        if base and base not in repo.dirs:
            continue
        pattern = re.compile(
            fnmatch.translate(root + path)
            + r"|"
            + fnmatch.translate(root + path + "/*")
        )
        if any(pattern.match(f) for f in repo.files if f.startswith(base)):
            found.append(root + path)
    return found


def resolve_row(tokens: Iterable[str], repo: Repo) -> list[str]:
    return [path for token in tokens for path in resolve_token(token, repo)]


def _check_header(doc: Doc) -> tuple[list[str], str | None]:
    """Errors and the summary text of a component header."""
    rel = doc.rel
    head = doc.text.split("\n## ", 1)[0]
    lines = [line for line in head.splitlines() if line.strip() not in ("", "---")]
    expected = (
        "a `# Title`, a `>` summary, then `**Verified against:**` and "
        "`**Edition:**` lines"
    )
    if not lines or not lines[0].startswith("# "):
        return [f"{rel}: the header must start with a `# Title` line"], None
    summary_lines = []
    index = 1
    while index < len(lines) and lines[index].startswith(">"):
        summary_lines.append(lines[index][1:].strip())
        index += 1
    errors: list[str] = []
    summary = collapse(" ".join(summary_lines)) or None
    if summary is None:
        errors.append(f"{rel}: the header needs a `>` summary after the title")
    else:
        sentences = re.findall(r"[.!?](?=\s|$)", CODE_SPAN.sub("", summary))
        if len(sentences) > SUMMARY_SENTENCES:
            errors.append(
                f"{rel}: the summary has {len(sentences)} sentences. Use one or two."
            )
    fields = lines[index:]
    removed = {
        "**Domain:**": "The INDEX.md section that lists the component is its domain.",
        "**Kind:**": "The first section, `## User experience` or `## Callers`, "
        "says whom the component serves.",
    }
    for prefix, reason in removed.items():
        if any(line.startswith(prefix) for line in fields):
            errors.append(f"{rel}: remove `{prefix}`. {reason}")
            fields = [line for line in fields if not line.startswith(prefix)]
    prefixes = ("**Verified against:**", "**Edition:**")
    # The Edition line may continue on the lines after it.
    if len(fields) < len(prefixes) or any(
        not fields[i].startswith(prefix) for i, prefix in enumerate(prefixes)
    ):
        errors.append(f"{rel}: the header must be {expected}, in that order")
    elif any(line.startswith(("**", ">", "#")) for line in fields[len(prefixes) :]):
        errors.append(f"{rel}: the header holds only {expected}")
    if not VERIFIED_LINE.search(head):
        errors.append(
            f"{rel}: missing a `**Verified against:** `<sha>` (YYYY-MM-DD)` line"
        )
    return errors, summary


def _check_sections(doc: Doc) -> list[str]:
    rel = doc.rel
    found = [
        line.text[3:].strip()
        for line in doc.lines
        if line.text.startswith("## ") and not line.in_fence
    ]
    allowed = ", ".join(name for name, _, _ in SECTIONS)
    errors = [
        f"{rel}: unknown section `## {name}`. Allowed: {allowed}"
        for name in found
        if name not in SECTION_RANK
    ]
    errors.extend(
        f"{rel}: section `## {name}` appears more than once"
        for name in sorted({n for n in found if found.count(n) > 1})
    )
    errors.extend(
        f"{rel}: missing required section `## {name}`"
        for name, _, required in SECTIONS
        if required and name not in found
    )
    ranks = [SECTION_RANK[name] for name in found if name in SECTION_RANK]
    if ranks != sorted(ranks):
        errors.append(f"{rel}: sections must follow the order {allowed}")
    first = [name for name in FIRST_SECTIONS if name in found]
    if len(first) != 1:
        errors.append(
            f"{rel}: a component has exactly one of `## User experience` (people use "
            "it) or `## Callers` (other code builds on it) as its first section"
        )
    return errors


def _check_style(doc: Doc) -> list[str]:
    errors: list[str] = []
    for line in doc.lines:
        prose = CODE_SPAN.sub("", line.text)
        if not line.in_fence:
            match = PR_NUMBER.search(prose)
            if match:
                errors.append(
                    f"{doc.rel}:{line.number}: `{match.group(0)}` cites a PR. "
                    "State what is true, and leave history to git."
                )
            match = CONTRACT_BY_NUMBER.search(prose)
            if match:
                errors.append(
                    f"{doc.rel}:{line.number}: `{match.group(0)}` cites a contract by "
                    "number. Cite its key: `[[slug#key]]` or `[[#key]]`."
                )
        errors.extend(
            f"{doc.rel}:{line.number}: `{token}` cites a line number. Cite `path:symbol`."
            for token in CODE_SPAN.findall(line.text)
            if LINE_REFERENCE.search(token)
        )
    return errors


def _check_symbols(doc: Doc, repo: Repo) -> list[str]:
    errors: list[str] = []
    for line in doc.lines:
        if line.in_fence:
            continue
        for token in CODE_SPAN.findall(line.text):
            match = SYMBOL_REFERENCE.match(token)
            if not match:
                continue
            files = [c for c in candidates(match.group(1), repo) if c in repo.files]
            if len(files) > 1:
                errors.append(
                    f"{doc.rel}:{line.number}: `{token}` matches more than one file: "
                    f"{', '.join(files)}. Use the full path."
                )
            if len(files) != 1:
                # A path that matches nothing is reported by the path check.
                continue
            source = (repo.root / files[0]).read_text(errors="ignore")
            errors.extend(
                f"{doc.rel}:{line.number}: `{token}`: `{name}` is not in {files[0]}"
                for name in match.group(2).strip(".").split(".")
                if not re.search(rf"\b{re.escape(name)}\b", source)
            )
    return errors


_ITEM_NAME = {CONTRACTS: "contract", RECIPES: "recipe"}
_ITEM_FORMAT = {
    CONTRACTS: "``N. `kebab-case-key` **Rule.**``",
    RECIPES: "``- `kebab-case-key` **Task.**``",
}
# Lines that start an item of the wrong form, at column 0.
_STRAY_ITEM = {
    CONTRACTS: re.compile(r"^[-*] "),
    RECIPES: re.compile(r"^(\*\*|\d+\. )"),
}


def _check_items(doc: Doc) -> list[str]:
    """Contracts and recipes carry a unique kebab-case key; the two share one namespace."""
    errors: list[str] = []
    seen: set[str] = set()
    for section, name in _ITEM_NAME.items():
        errors.extend(
            f"{doc.rel}:{line.number}: {section} holds {name} items. Write "
            f"{_ITEM_FORMAT[section]}, or indent the line under an item."
            for line in section_lines(doc, section)
            if not line.in_fence and _STRAY_ITEM[section].match(line.text)
        )
        for number, key in item_keys(doc, section):
            if key is None:
                errors.append(
                    f"{doc.rel}:{number}: the {name} has no key. Write "
                    f"{_ITEM_FORMAT[section]}."
                )
            elif not SLUG.match(key):
                errors.append(
                    f"{doc.rel}:{number}: {name} key `{key}` must be lower-case "
                    "kebab case"
                )
            elif key in seen:
                errors.append(f"{doc.rel}:{number}: duplicate key `{key}`")
            if key:
                seen.add(key)
    return errors


def _check_scope(doc: Doc, repo: Repo, allowed: set[tuple[str, str]]) -> list[str]:
    errors: list[str] = []
    for line in section_lines(doc, "Scope"):
        for token in CODE_SPAN.findall(line.text):
            if ":" in token or (doc.rel, token) in allowed:
                continue
            if looks_like_path(token, repo) is not None:
                errors.append(
                    f"{doc.rel}:{line.number}: Scope lists the path `{token}`. "
                    "PATHS.md is the only ownership record; state responsibilities."
                )
    return errors


def _check_dependencies(doc: Doc) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    previous_is_item = False
    for line in section_lines(doc, "Dependencies"):
        text = line.text
        if not text.strip() or text.strip() == "---":
            continue
        if text[0].isspace() and previous_is_item:
            continue
        match = DEPENDENCY_ITEM.match(text)
        previous_is_item = match is not None
        if match is None:
            errors.append(
                f"{doc.rel}:{line.number}: Dependencies lists only "
                "`- [[slug]]: reason` lines for what this component depends on"
            )
            continue
        slug = match.group(1)
        if slug == doc.name:
            errors.append(
                f"{doc.rel}:{line.number}: a component cannot depend on itself"
            )
        elif slug in seen:
            errors.append(f"{doc.rel}:{line.number}: `[[{slug}]]` is listed twice")
        seen.add(slug)
    return errors


def _heading_anchors(text: str) -> set[str]:
    return {
        re.sub(r"[^\w\- ]", "", match.lower()).strip().replace(" ", "-")
        for match in re.findall(r"^#+ (.+)$", text, re.MULTILINE)
    }


def _check_links(
    doc: Doc,
    keys: dict[str, set[str]],
    anchors: dict[str, set[str]],
) -> list[str]:
    """`anchors` maps each component's path, such as `components/citations.md`."""
    errors: list[str] = []
    for line in doc.lines:
        if line.in_fence:
            continue
        prose = CODE_SPAN.sub("", line.text)
        errors.extend(
            f"{doc.rel}:{line.number}: `{link}` is not a link. Write `[[slug]]`, "
            "`[[slug#key]]` or `[[#key]]`, or put it in a code span."
            for link in ANY_LINK.findall(prose)
            if not WIKI_LINK.fullmatch(link)
        )
        for slug, key in WIKI_LINK.findall(prose):
            target = slug or (doc.name if doc.is_component else "")
            link = f"[[{slug}{'#' + key if key else ''}]]"
            if not slug and not key:
                errors.append(f"{doc.rel}:{line.number}: empty link `[[]]`")
            elif not slug and not doc.is_component:
                errors.append(
                    f"{doc.rel}:{line.number}: {link} works only inside a component. "
                    "Name the component: `[[slug#key]]`."
                )
            elif target not in keys:
                errors.append(f"{doc.rel}:{line.number}: unknown component link {link}")
            elif key and key not in keys[target]:
                errors.append(
                    f"{doc.rel}:{line.number}: {link}: `{target}` has no contract "
                    f"or recipe with the key `{key}`"
                )
        for rel, anchor in COMPONENT_LINK.findall(prose):
            if rel not in anchors:
                errors.append(
                    f"{doc.rel}:{line.number}: links to missing component `{rel}`"
                )
            elif anchor and anchor not in anchors[rel]:
                errors.append(
                    f"{doc.rel}:{line.number}: `{rel}` has no heading `#{anchor}`"
                )
    return errors


def _check_index(
    map_dir: Path, components: list[Doc], summaries: dict[str, str | None]
) -> list[str]:
    text = (map_dir / "INDEX.md").read_text()
    errors: list[str] = []
    rows: dict[str, list[tuple[int, str]]] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        match = INDEX_ROW.match(line)
        if match:
            rows.setdefault(match.group(1), []).append((number, match.group(2)))
    names = {doc.name for doc in components}
    for doc in components:
        found = rows.get(doc.name, [])
        if not found:
            errors.append(f"INDEX.md: component `{doc.name}` is not listed")
            continue
        if len(found) > 1:
            errors.append(f"INDEX.md: component `{doc.name}` is listed more than once")
        summary = summaries.get(doc.name)
        number, cell = found[0]
        if summary is not None and collapse(cell) != summary:
            errors.append(
                f"INDEX.md:{number}: the row for `{doc.name}` must repeat the summary "
                f"in {doc.rel} word for word. Run `{_FIX_COMMAND}`."
            )
    errors.extend(
        f"INDEX.md: lists missing component `{name}`"
        for name in sorted(set(rows) - names)
    )
    if f"## {COMMON_TASKS}" not in text.splitlines():
        errors.append(f"INDEX.md: missing the `## {COMMON_TASKS}` table")
    return errors


def _check_paths(map_dir: Path, names: set[str], repo: Repo) -> list[str]:
    errors: list[str] = []
    for row in paths_rows((map_dir / "PATHS.md").read_text()):
        where = f"PATHS.md:{row.number}"
        if row.columns != 2:
            errors.append(
                f"{where}: a PATHS.md row has two columns: the paths, then the "
                f"component slugs or, under `## {NOT_MAPPED}`, the reason"
            )
            continue
        if not row.tokens:
            errors.append(f"{where}: the row names no backticked path")
        errors.extend(
            f"{where}: `{token}` does not exist in the repo"
            for token in row.tokens
            if not resolve_token(token, repo)
        )
        if row.not_mapped:
            if not row.owner:
                errors.append(f"{where}: a `## {NOT_MAPPED}` row needs a reason")
            continue
        parts = [part.strip() for part in row.owner.split(",")]
        bad = [part for part in parts if part not in names]
        if bad:
            errors.append(
                f"{where}: `{row.owner}` is not a list of component slugs. Name "
                f"components, or move the path to `## {NOT_MAPPED}` with a reason."
            )
    return errors


def _check_paths_exist(
    doc: Doc, repo: Repo, allowed: set[tuple[str, str]]
) -> list[str]:
    errors: list[str] = []
    for line in doc.lines:
        if line.in_fence:
            continue
        for token in CODE_SPAN.findall(line.text):
            path = looks_like_path(token, repo)
            if path is None or (doc.rel, token) in allowed:
                continue
            if not candidates(path, repo):
                errors.append(
                    f"{doc.rel}:{line.number}: `{token}` does not exist in the repo. "
                    "Use a repo-root path or a path under a documented root, or add "
                    "it to path-allowlist.txt if it is not a repo path."
                )
    return errors


def _git_status(repo: Path, *args: str) -> int:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True
    ).returncode


def _check_ancestry(components: list[Doc], repo: Repo) -> list[str]:
    """Warn when a Verified-against commit is not on origin/main."""
    if _git_status(repo.root, "rev-parse", "--verify", "-q", "origin/main^{commit}"):
        return []
    status: dict[str, int] = {}
    warnings: list[str] = []
    for doc in components:
        match = VERIFIED_LINE.search(doc.text)
        if not match:
            continue
        sha = match.group(1)
        if sha not in status:
            status[sha] = _git_status(
                repo.root, "merge-base", "--is-ancestor", sha, "origin/main"
            )
        if status[sha]:
            warnings.append(
                f"{doc.rel}: Verified against `{sha}` is not a commit on origin/main. "
                "Use `git merge-base HEAD origin/main`."
            )
    return warnings


def legacy_names(map_dir: Path) -> set[str]:
    path = map_dir / "legacy-schema.txt"
    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }


def check(
    map_dir: Path = MAP_DIR, repo_root: Path = REPO_ROOT
) -> tuple[list[str], list[str]]:
    """(errors, warnings) for the map in `map_dir`."""
    errors: list[str] = []
    components = load_components(map_dir)
    top_level = load_top_level(map_dir)
    repo = repo_paths(repo_root)
    allowed = read_allowlist(map_dir)

    seen: dict[str, str] = {}
    for doc in components:
        if doc.name in seen:
            errors.append(
                f"{doc.rel}: the name `{doc.name}` is also used by {seen[doc.name]}. "
                "Component names must be unique."
            )
        seen[doc.name] = doc.rel

    # Components listed in legacy-schema.txt keep the numbered format until the
    # rewrite lands. While any are listed, the check skips them and the map-wide
    # INDEX, PATHS and link checks, which assume the current format.
    legacy = legacy_names(map_dir)
    if legacy:
        components = [doc for doc in components if doc.name not in legacy]
        top_level = []

    summaries: dict[str, str | None] = {}
    for doc in components:
        header_errors, summary = _check_header(doc)
        summaries[doc.name] = summary
        errors.extend(header_errors)
        errors.extend(_check_sections(doc))
        errors.extend(_check_items(doc))
        errors.extend(_check_scope(doc, repo, allowed))
        errors.extend(_check_dependencies(doc))
    for doc in components + top_level:
        errors.extend(_check_style(doc))
        errors.extend(_check_symbols(doc, repo))

    if legacy:
        return errors, _check_ancestry(components, repo)

    names = {doc.name for doc in components}
    errors.extend(_check_index(map_dir, components, summaries))
    errors.extend(_check_paths(map_dir, names, repo))

    keys = {doc.name: link_keys(doc) for doc in components}
    anchors = {doc.rel: _heading_anchors(doc.text) for doc in components}
    for path in sorted(map_dir.rglob("*.md")):
        doc = load_doc(map_dir, path)
        errors.extend(_check_links(doc, keys, anchors))
        if doc.rel != "PATHS.md":
            errors.extend(_check_paths_exist(doc, repo, allowed))
    return errors, _check_ancestry(components, repo)


def summaries(components: Iterable[Doc]) -> dict[str, str]:
    return {
        doc.name: summary
        for doc in components
        if (summary := _check_header(doc)[1]) is not None
    }


def fixed_index(text: str, summary_of: dict[str, str]) -> str:
    """INDEX.md with each component row's summary cell set to the document's summary."""

    def row(line: str) -> str:
        match = INDEX_ROW.match(line)
        if not match or match.group(1) not in summary_of:
            return line
        summary = summary_of[match.group(1)]
        if collapse(match.group(2)) == summary:
            return line
        return f"{line[: match.start(2)]} {summary} |"

    return "".join(row(line) + end for line, end in _split_keep_ends(text))


def _split_keep_ends(text: str) -> list[tuple[str, str]]:
    return [
        (line.rstrip("\n"), "\n" if line.endswith("\n") else "")
        for line in text.splitlines(keepends=True)
    ]


def fix(map_dir: Path = MAP_DIR) -> bool:
    """Write the INDEX.md summaries. True when the file changed."""
    index = map_dir / "INDEX.md"
    text = index.read_text()
    fixed = fixed_index(text, summaries(load_components(map_dir)))
    if fixed == text:
        return False
    index.write_text(fixed)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fix", action="store_true", help="copy each summary into its INDEX.md row"
    )
    if parser.parse_args().fix and fix():
        print("feature map: updated the INDEX.md summaries", file=sys.stderr)
    errors, warnings = check()
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        print(
            f"\nfeature map: {len(errors)} problem(s). See .agents/feature-map/README.md.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
