"""Environment-variable inventory for the Onyx backend.

AST-walks the backend (and optionally the frontend) to build a canonical
manifest of every environment variable the code actually reads, then
cross-references the deployment files (docker-compose env templates + Helm
values/configmap) to surface drift:

  * read-but-undocumented  -> code reads a var no template mentions
  * documented-but-unread  -> a template advertises a var no code reads
  * duplicate assignments  -> same module-level constant assigned 2+ times
                              (last write wins; the rest are dead code)

It also classifies every variable on two axes (see classify_var) — a category
(platform / connector / internal / tunable) and a sensitive flag — to turn the
raw read-but-undocumented list into an actionable "operator-facing tunables that
should be documented" shortlist, plus an "operator-set secrets" sublist.

This is read-only: it never edits anything. It is meant to be the single
source of truth that `env.template` / Helm `values.yaml` can be diff-checked
against in CI.

Usage:
    python backend/scripts/env_inventory.py                # human summary
    python backend/scripts/env_inventory.py --csv out.csv  # full manifest
    python backend/scripts/env_inventory.py --json out.json
    python backend/scripts/env_inventory.py --drift-only   # just the drift report
    python backend/scripts/env_inventory.py --shortlist    # should-document names
    python backend/scripts/env_inventory.py --write-baseline  # snapshot the CI baseline
    python backend/scripts/env_inventory.py --check-baseline  # CI drift gate (exit 1 on drift)

Run from the repo root (it auto-detects paths relative to this file).
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

# --- repo layout --------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"

# Directories under backend/ to scan for env reads. We skip vendored/build dirs.
SCAN_ROOTS = [
    BACKEND_DIR / "onyx",
    BACKEND_DIR / "ee",
    BACKEND_DIR / "shared_configs",
    BACKEND_DIR / "model_server",
]
SKIP_DIR_NAMES = {
    "__pycache__",
    ".venv",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
}

# The canonical "config" location. Reads outside this set are "ad-hoc".
CONFIG_DIR_MARKERS = ("/configs/", "/shared_configs/")

# Custom helper functions whose FIRST string arg is an env var name and whose
# SECOND arg is the default. Extend this as new helpers are introduced.
ENV_HELPER_FUNCS = {
    "_non_negative_int_env": "int",
}

# Deployment files to cross-reference.
ENV_TEMPLATES = [
    REPO_ROOT / "deployment" / "docker_compose" / "env.template",
    REPO_ROOT / "deployment" / "docker_compose" / "env.prod.template",
]
HELM_VALUES = REPO_ROOT / "deployment" / "helm" / "charts" / "onyx" / "values.yaml"
HELM_CONFIGMAP = (
    REPO_ROOT
    / "deployment"
    / "helm"
    / "charts"
    / "onyx"
    / "templates"
    / "configmap.yaml"
)

# Vars we never expect deployment templates to carry (test creds, pure-dev).
# Used only to keep the drift report signal-to-noise high.
DRIFT_IGNORE_PREFIXES = ("TEST_",)
DRIFT_IGNORE_SUBSTRINGS = ("_TEST_", "TEST_")


# --- variable classification --------------------------------------------------
#
# Two orthogonal axes per variable:
#   category  -> where it belongs / who sets it
#                 platform  : injected by the runtime (k8s/docker/OS), not operators
#                 connector : connector credential/config (set per-connector in the
#                             UI, NOT in the global env templates)
#                 internal  : dev/test/debug/eval only — never operator-facing
#                 tunable   : operator-facing knob (timeout/limit/flag) — the set
#                             that SHOULD be documented in env.template / Helm values
#   sensitive -> credential-shaped (must never sit in a plaintext template; belongs
#                in a secrets manager). Orthogonal to category.
#
# Heuristic, name- + read-location-based. Known misclassifications go in
# TAG_OVERRIDES rather than contorting the regexes.

# Set by the runtime platform; an operator never puts these in a template.
PLATFORM_VARS = {
    "HOSTNAME",
    "HOME",
    "PATH",
    "POD_NAME",
    "POD_NAMESPACE",
    "KUBERNETES_SERVICE_HOST",
    "TOKENIZERS_PARALLELISM",
    "HF_HUB_DISABLE_TELEMETRY",
}

# Credential-shaped names. Excludes the suffixes that mark a non-secret reference
# (a path/url/id/username pointing AT a secret is not itself the secret).
# `_PASSWORD$` (suffix) is a real secret; `PASSWORD_*` (prefix) is policy config
# (PASSWORD_MIN_LENGTH, PASSWORD_REQUIRE_DIGIT, ...) and must NOT match.
_SENSITIVE_RE = re.compile(
    r"(SECRET|_PASSWORD$|^PASSWORD$|PASSWD|_TOKEN$|ACCESS_TOKEN|_API_KEY$|ACCESS_KEY"
    r"|PRIVATE_KEY|SERVICE_ACCOUNT_KEY|CREDENTIAL|_PEM$|_DSN$|SIGNING_KEY|AUTH_SECRET"
    r"|(^|_)SALT$)"
)
_NOT_SENSITIVE_SUFFIX_RE = re.compile(
    r"(_URL|_PATH|_FILE|_NAME|_ID|_ROUNDS|_TTL|_TIMEOUT|_HOST|_PORT|_VERSION"
    r"|_PREFIX|_USERNAME|_USER|_KEYFILE)$"
)
# High precision on purpose: anything wrongly tagged internal drops off the
# "should be documented" radar, so only clearly dev/test/eval names match.
_INTERNAL_RE = re.compile(
    r"(^DEV_|_DEV$|^MOCK_|_MOCK_|_DEBUG$|DEBUGGING|^TEST_|_TEST_|EXPERIMENTAL"
    r"|DANSWER|(^|_)EVAL(_|$))"
)

# name -> (category, sensitive) manual overrides for heuristic misses.
TAG_OVERRIDES: dict[str, tuple[str, bool]] = {}

VALID_CATEGORIES = ("platform", "connector", "internal", "tunable")


def is_sensitive(name: str) -> bool:
    if "PUBLIC" in name:  # a public key / id is not a secret to protect
        return False
    return bool(_SENSITIVE_RE.search(name)) and not _NOT_SENSITIVE_SUFFIX_RE.search(
        name
    )


def classify_var(name: str, files: set[str]) -> tuple[str, bool]:
    """Return (category, sensitive). `files` are the repo-relative read sites."""
    if name in TAG_OVERRIDES:
        return TAG_OVERRIDES[name]
    sensitive = is_sensitive(name)
    if name in PLATFORM_VARS:
        category = "platform"
    elif any("/connectors/" in f for f in files):
        category = "connector"
    elif _INTERNAL_RE.search(name):
        category = "internal"
    else:
        category = "tunable"
    return category, sensitive


@dataclass
class EnvRead:
    name: str
    file: str  # relative to repo root
    line: int
    read_style: str  # environ.get | getenv | environ[] | helper:<fn>
    inferred_type: str  # str | int | float | bool | unknown
    default: str | None  # literal default if statically determinable
    assigned_to: str | None  # module-level constant name, if it's an assignment
    assign_id: int | None  # identity of the enclosing Assign statement
    assign_line: int | None  # lineno of the enclosing Assign statement
    module_scope: bool  # assignment sits at module scope (not inside a def/lambda)
    in_config_dir: bool
    is_ee: bool


@dataclass
class VarSummary:
    name: str
    read_count: int = 0
    types: set[str] = field(default_factory=set)
    defaults: set[str] = field(default_factory=set)
    files: set[str] = field(default_factory=set)
    constants: set[str] = field(default_factory=set)
    in_config_dir: bool = False
    ad_hoc_only: bool = True
    is_ee: bool = False
    category: str = "tunable"
    sensitive: bool = False


# --- AST extraction -----------------------------------------------------------


def _str_const(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _literal_default(node: ast.AST | None) -> str | None:
    """Best-effort render of a statically-known default value."""
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return repr(node.value)
    # `os.environ.get("X") or "9000"` -> default is the rhs of the `or`
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        return _literal_default(node.values[-1])
    try:
        return ast.unparse(node)
    except Exception:
        return None


class EnvVisitor(ast.NodeVisitor):
    """Collects env reads and infers a type from the enclosing cast/comparison."""

    def __init__(
        self,
        rel_path: str,
        is_ee: bool,
        environ_aliases: set[str],
        getenv_aliases: set[str],
    ) -> None:
        self.rel_path = rel_path
        self.is_ee = is_ee
        # Names bound to os.environ / os.getenv via `from os import environ, getenv`
        # (possibly aliased). Lets us catch bare `environ.get("X")` / `getenv("X")`.
        self._environ_aliases = environ_aliases
        self._getenv_aliases = getenv_aliases
        self.in_config_dir = any(m in f"/{rel_path}" for m in CONFIG_DIR_MARKERS)
        self.reads: list[EnvRead] = []
        # parent map so we can look "up" for casts and assignment targets
        self._parents: dict[int, ast.AST] = {}
        # ids of nodes that live inside a function/lambda body (not module scope)
        self._in_function: set[int] = set()

    def visit(self, node: ast.AST) -> None:
        nested = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
        for child in ast.iter_child_nodes(node):
            self._parents[id(child)] = node
            if nested or id(node) in self._in_function:
                self._in_function.add(id(child))
        super().visit(node)

    # -- helpers --

    def _is_environ(self, node: ast.AST) -> bool:
        """True if `node` refers to os.environ — as `os.environ` (Attribute) or a
        bare name bound via `from os import environ`."""
        if isinstance(node, ast.Attribute) and node.attr == "environ":
            return True
        return isinstance(node, ast.Name) and node.id in self._environ_aliases

    def _enclosing_type(self, call_node: ast.AST) -> str:
        """Infer type from the immediate wrapper: int(...), float(...), bool comparison."""
        parent = self._parents.get(id(call_node))
        # unwrap a BoolOp (the `or default` pattern) to find the real wrapper
        hops = 0
        while isinstance(parent, ast.BoolOp) and hops < 3:
            parent = self._parents.get(id(parent))
            hops += 1
        if isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name):
            if parent.func.id in ("int", "float", "bool"):
                return parent.func.id
        # `.lower() == "true"` / `== "false"` style -> bool
        if isinstance(parent, ast.Attribute) and parent.attr in ("lower", "upper"):
            return "bool"
        if isinstance(parent, ast.Compare):
            return "bool"
        return "str"

    def _assignment(self, call_node: ast.AST) -> tuple[str, int, int] | None:
        """Walk up to the nearest Assign; return (target_name, assign_id, lineno).

        Returns None if the read isn't part of a simple single-name assignment.
        """
        node: ast.AST | None = call_node
        hops = 0
        while node is not None and hops < 8:
            parent = self._parents.get(id(node))
            if isinstance(parent, ast.Assign):
                if len(parent.targets) == 1 and isinstance(parent.targets[0], ast.Name):
                    return parent.targets[0].id, id(parent), parent.lineno
                return None
            node = parent
            hops += 1
        return None

    def _record(
        self,
        name: str,
        line: int,
        read_style: str,
        call_node: ast.AST,
        default: str | None,
        type_hint: str | None = None,
    ) -> None:
        assignment = self._assignment(call_node)
        self.reads.append(
            EnvRead(
                name=name,
                file=self.rel_path,
                line=line,
                read_style=read_style,
                inferred_type=type_hint or self._enclosing_type(call_node),
                default=default,
                assigned_to=assignment[0] if assignment else None,
                assign_id=assignment[1] if assignment else None,
                assign_line=assignment[2] if assignment else None,
                module_scope=id(call_node) not in self._in_function,
                in_config_dir=self.in_config_dir,
                is_ee=self.is_ee,
            )
        )

    # -- visitors --

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = _str_const(node.args[0]) if node.args else None
        # env_name is the first arg only when it's a valid VAR_NAME literal
        env_name = name if (name and re.fullmatch(r"[A-Z][A-Z0-9_]*", name)) else None
        default = _literal_default(node.args[1]) if len(node.args) > 1 else None
        # os.environ.get("X") / environ.get("X")  and  os.getenv("X")
        if isinstance(func, ast.Attribute):
            if env_name and func.attr == "get" and self._is_environ(func.value):
                self._record(env_name, node.lineno, "environ.get", node, default)
            elif env_name and func.attr == "getenv":
                self._record(env_name, node.lineno, "getenv", node, default)
        elif isinstance(func, ast.Name):
            # bare getenv("X") after `from os import getenv`
            if env_name and func.id in self._getenv_aliases:
                self._record(env_name, node.lineno, "getenv", node, default)
            # custom helper: _non_negative_int_env("X", 250)
            elif name is not None and func.id in ENV_HELPER_FUNCS:
                self._record(
                    name,
                    node.lineno,
                    f"helper:{func.id}",
                    node,
                    default,
                    type_hint=ENV_HELPER_FUNCS[func.id],
                )
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        # os.environ["X"] / environ["X"]
        if self._is_environ(node.value):
            name = _str_const(node.slice)
            if name is not None and re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
                self._record(name, node.lineno, "environ[]", node, default=None)
        self.generic_visit(node)


def iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        yield path


def _scan_os_imports(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Find names bound to os.environ / os.getenv via `from os import ...`.

    Catches aliased forms (`from os import environ as env`) so the visitor can
    recognise bare `env.get("X")` / `getenv("X")` reads, not just `os.environ`.
    """
    environ_aliases: set[str] = set()
    getenv_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            for alias in node.names:
                if alias.name == "environ":
                    environ_aliases.add(alias.asname or "environ")
                elif alias.name == "getenv":
                    getenv_aliases.add(alias.asname or "getenv")
    return environ_aliases, getenv_aliases


def collect_reads() -> list[EnvRead]:
    reads: list[EnvRead] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in iter_python_files(root):
            rel = str(path.relative_to(REPO_ROOT))
            is_ee = "/ee/" in f"/{rel}" or rel.startswith("backend/ee/")
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError:
                continue
            environ_aliases, getenv_aliases = _scan_os_imports(tree)
            visitor = EnvVisitor(rel, is_ee, environ_aliases, getenv_aliases)
            visitor.visit(tree)
            reads.extend(visitor.reads)
    return reads


# --- duplicate-assignment detection ------------------------------------------


def find_duplicate_assignments(reads: list[EnvRead]) -> dict[str, list[int]]:
    """Same module-level constant assigned from an env read on 2+ distinct lines.

    These are silent dead-code: only the last assignment survives at import. We
    restrict to module scope (a `connector = ...` local reassigned in a function
    body is not dead code) and dedupe identical line numbers (a var read twice on
    one line is one assignment, not two).
    """
    # Map (file, const) -> {assign_id: assign_line}. Keying on the Assign node
    # (not the read line) collapses one multi-line assignment that happens to
    # contain several env reads into a single assignment.
    by_file_const: dict[tuple[str, str], dict[int, int]] = defaultdict(dict)
    for r in reads:
        # Only true UPPER_SNAKE config constants; skip lowercase script-block
        # locals (e.g. `connector = ...` reused in a connector __main__ harness).
        if (
            r.assigned_to
            and r.module_scope
            and r.assign_id is not None
            and re.fullmatch(r"[A-Z][A-Z0-9_]*", r.assigned_to)
        ):
            by_file_const[(r.file, r.assigned_to)][r.assign_id] = (
                r.assign_line or r.line
            )
    return {
        f"{file}::{const}": sorted(assigns.values())
        for (file, const), assigns in by_file_const.items()
        if len(assigns) > 1
    }


# --- summarization ------------------------------------------------------------


def summarize(reads: list[EnvRead]) -> dict[str, VarSummary]:
    summaries: dict[str, VarSummary] = {}
    for r in reads:
        s = summaries.setdefault(r.name, VarSummary(name=r.name))
        s.read_count += 1
        s.types.add(r.inferred_type)
        if r.default is not None:
            s.defaults.add(r.default)
        s.files.add(r.file)
        if r.assigned_to:
            s.constants.add(r.assigned_to)
        if r.in_config_dir:
            s.in_config_dir = True
            s.ad_hoc_only = False
        if r.is_ee:
            s.is_ee = True
    for s in summaries.values():
        s.category, s.sensitive = classify_var(s.name, s.files)
    return summaries


# --- deployment cross-reference ----------------------------------------------

_ENV_LINE_RE = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)\s*=")


def parse_env_template(path: Path) -> set[str]:
    """Extract var names from a docker-compose-style env file.

    Captures both active (`KEY=`) and commented (`# KEY=`) lines, since the
    template uses comments to advertise optional/default knobs.
    """
    names: set[str] = set()
    if not path.exists():
        return names
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _ENV_LINE_RE.match(line)
        if m:
            names.add(m.group(1))
    return names


_YAML_KEY_RE = re.compile(r"^(\s*)([A-Z][A-Z0-9_]*)\s*:")


def parse_helm_values_configmap(path: Path) -> set[str]:
    """Extract the env keys declared under the `configMap:` block of values.yaml.

    Light indentation-based parser (avoids a hard PyYAML dependency). We find the
    `configMap:` mapping and collect immediate UPPER_SNAKE child keys.
    """
    names: set[str] = set()
    if not path.exists():
        return names
    lines = path.read_text(encoding="utf-8").splitlines()
    in_block = False
    block_indent = -1
    for line in lines:
        stripped = line.rstrip()
        if not stripped or stripped.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if re.match(r"^\s*configMap\s*:\s*$", line):
            in_block = True
            block_indent = indent
            continue
        if in_block:
            # left the block when we dedent back to/under the configMap line
            if indent <= block_indent:
                in_block = False
                continue
            m = _YAML_KEY_RE.match(line)
            if m and len(m.group(1)) > block_indent:
                names.add(m.group(2))
    return names


def parse_helm_configmap_template(path: Path) -> set[str]:
    """Extract literal env keys from the Go-templated configmap.yaml."""
    names: set[str] = set()
    if not path.exists():
        return names
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s*:", line)
        if m:
            names.add(m.group(1))
    return names


def _drift_ignored(name: str) -> bool:
    if any(name.startswith(p) for p in DRIFT_IGNORE_PREFIXES):
        return True
    return any(sub in name for sub in DRIFT_IGNORE_SUBSTRINGS)


# --- reporting ----------------------------------------------------------------


def documented_names() -> set[str]:
    """Union of var names advertised by the env templates and Helm chart."""
    names: set[str] = set()
    for t in ENV_TEMPLATES:
        names |= parse_env_template(t)
    names |= parse_helm_values_configmap(HELM_VALUES)
    names |= parse_helm_configmap_template(HELM_CONFIGMAP)
    return names


def should_document_list(reads: list[EnvRead]) -> list[str]:
    """Operator-facing tunables that no template advertises — the 'should be
    documented' shortlist (excludes connector/platform/internal/test vars)."""
    summaries = summarize(reads)
    documented = documented_names()
    return sorted(
        n
        for n, s in summaries.items()
        if s.category == "tunable" and n not in documented and not _drift_ignored(n)
    )


# --- drift baseline (CI gate) -------------------------------------------------
#
# The baseline freezes the CURRENT should-document backlog so the CI gate only
# catches NEW drift, not the pre-existing tail. Golden-file semantics: the gate
# asserts the live should-document set equals the committed baseline exactly, so
# the file shrinks in lockstep as Phase-2 documentation lands.

BASELINE_PATH = BACKEND_DIR / "scripts" / "env_inventory_baseline.txt"

_BASELINE_HEADER = """\
# Env-var drift baseline — operator-facing tunables that backend code READS but
# no deployment template (env.template / Helm values.yaml) documents yet.
#
# GENERATED — do not hand-edit. Managed by backend/scripts/env_inventory.py.
# Regenerate:
#   python backend/scripts/env_inventory.py --write-baseline
#
# The CI drift gate (`--check-baseline`) fails when this list drifts from what
# the code actually reads:
#   * a NEW undocumented tunable appeared -> document it in env.template + Helm
#     values.yaml (preferred), OR regenerate this file if it's intentionally
#     left undocumented for now.
#   * a listed var became documented/removed -> regenerate so the backlog shrinks.
#
# One VAR_NAME per line, sorted.
"""


def read_baseline(path: Path) -> set[str]:
    """Parse a baseline file into a set of names (ignores blanks + `#` comments)."""
    names: set[str] = set()
    if not path.exists():
        return names
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            names.add(line)
    return names


def format_baseline(names: list[str]) -> str:
    """Render the canonical baseline file body (header + sorted names)."""
    body = "\n".join(sorted(set(names)))
    return f"{_BASELINE_HEADER}\n{body}\n" if body else f"{_BASELINE_HEADER}\n"


def diff_baseline(current: set[str], baseline: set[str]) -> tuple[list[str], list[str]]:
    """Compare the live should-document set to a committed baseline.

    Returns (new_drift, resolved):
      * new_drift -> tunables the code reads that are neither documented nor in
                     the baseline (the gate FAILS on these).
      * resolved  -> baseline entries the code no longer reads-and-leaves-
                     undocumented (now documented or deleted; baseline is stale).
    Both empty means the gate passes.
    """
    return sorted(current - baseline), sorted(baseline - current)


def human_report(reads: list[EnvRead], drift_only: bool = False) -> None:
    summaries = summarize(reads)
    dupes = find_duplicate_assignments(reads)

    template_names: set[str] = set()
    for t in ENV_TEMPLATES:
        template_names |= parse_env_template(t)
    helm_values_names = parse_helm_values_configmap(HELM_VALUES)
    helm_cm_names = parse_helm_configmap_template(HELM_CONFIGMAP)
    documented = template_names | helm_values_names | helm_cm_names

    code_names = set(summaries)

    read_undocumented = sorted(
        n for n in code_names - documented if not _drift_ignored(n)
    )
    documented_unread = sorted(
        n for n in documented - code_names if not _drift_ignored(n)
    )

    if not drift_only:
        total_reads = len(reads)
        ad_hoc = sum(1 for r in reads if not r.in_config_dir)
        ee_vars = sum(1 for s in summaries.values() if s.is_ee)
        multi_type = {n: s.types for n, s in summaries.items() if len(s.types) > 1}

        print("=" * 78)
        print("ONYX BACKEND ENV-VAR INVENTORY")
        print("=" * 78)
        print(f"Distinct env vars read in code : {len(code_names)}")
        print(f"Total read sites               : {total_reads}")
        print(
            f"  in configs/ dirs             : {total_reads - ad_hoc} "
            f"({100 * (total_reads - ad_hoc) // max(total_reads, 1)}%)"
        )
        print(
            f"  ad-hoc (outside configs/)    : {ad_hoc} "
            f"({100 * ad_hoc // max(total_reads, 1)}%)"
        )
        print(f"EE-only vars                   : {ee_vars}")
        print()

        # type breakdown
        type_counts: dict[str, int] = defaultdict(int)
        for s in summaries.values():
            for t in s.types:
                type_counts[t] += 1
        print("Inferred types (a var can appear under >1 if read inconsistently):")
        for t, c in sorted(type_counts.items(), key=lambda kv: -kv[1]):
            print(f"  {t:10s} {c}")
        print()

        print(f"Vars read with INCONSISTENT types across sites: {len(multi_type)}")
        for n, ts in sorted(multi_type.items())[:15]:
            print(f"  {n}: {sorted(ts)}")
        print()

        print(f"DUPLICATE module-level assignments (dead code): {len(dupes)}")
        for key, lines in sorted(dupes.items()):
            line_str = ", ".join(str(n) for n in lines)
            print(f"  {key}  -> lines {line_str} ({len(lines)}x, last wins)")
        print()

        # variable classification (see classify_var)
        cat_counts: dict[str, int] = defaultdict(int)
        for s in summaries.values():
            cat_counts[s.category] += 1
        sensitive_count = sum(1 for s in summaries.values() if s.sensitive)
        print("Classification (category = who sets it / where it belongs):")
        for c in VALID_CATEGORIES:
            print(f"  {c:10s} {cat_counts.get(c, 0)}")
        print(f"  sensitive (credential-shaped, orthogonal): {sensitive_count}")
        print()

        # ad-hoc hotspots
        ad_hoc_by_file: dict[str, int] = defaultdict(int)
        for r in reads:
            if not r.in_config_dir:
                ad_hoc_by_file[r.file] += 1
        print("Top ad-hoc env-read files (candidates to centralize):")
        for f, c in sorted(ad_hoc_by_file.items(), key=lambda kv: -kv[1])[:15]:
            print(f"  {c:4d}  {f}")
        print()

    print("=" * 78)
    print("DEPLOYMENT DRIFT")
    print("=" * 78)
    print(f"Documented in templates/Helm : {len(documented)}")
    print(
        f"  env.template(+prod)        : {len(template_names)}\n"
        f"  helm values.yaml configMap : {len(helm_values_names)}\n"
        f"  helm configmap.yaml        : {len(helm_cm_names)}"
    )
    print()
    print(
        f"READ-BUT-UNDOCUMENTED ({len(read_undocumented)}): code reads these, no "
        "template advertises them"
    )
    for n in read_undocumented:
        s = summaries[n]
        loc = "config" if s.in_config_dir else "ad-hoc"
        sens = " SECRET" if s.sensitive else ""
        print(f"  {n:45s} [{s.category:9s}|{loc}]{sens} {sorted(s.types)}")
    print()
    print(
        f"DOCUMENTED-BUT-UNREAD ({len(documented_unread)}): templates advertise "
        "these, no code reads them (possibly dead/renamed)"
    )
    for n in documented_unread:
        print(f"  {n}")
    print()

    # actionable shortlists derived from category + drift
    should_document = [
        n for n in read_undocumented if summaries[n].category == "tunable"
    ]
    operator_secrets = [n for n in should_document if summaries[n].sensitive]
    print("=" * 78)
    print("ACTIONABLE SHORTLIST")
    print("=" * 78)
    print(
        f"OPERATOR-FACING TUNABLES, UNDOCUMENTED ({len(should_document)}): the set "
        "that\n  most plausibly SHOULD be in env.template / Helm values but isn't.\n"
        "  (Excludes connector creds, platform-injected, and dev/test/eval vars.)"
    )
    for n in should_document:
        sens = " SECRET" if summaries[n].sensitive else ""
        print(f"  {n}{sens}")
    print()
    print(
        f"OPERATOR-SET SECRETS, UNDOCUMENTED ({len(operator_secrets)}): credential-"
        "shaped\n  tunables with no template entry — wire via a secrets manager, "
        "not plaintext."
    )
    for n in operator_secrets:
        print(f"  {n}")


def write_csv(reads: list[EnvRead], out: Path) -> None:
    summaries = summarize(reads)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "name",
                "file",
                "line",
                "read_style",
                "inferred_type",
                "default",
                "assigned_to",
                "assign_line",
                "module_scope",
                "in_config_dir",
                "is_ee",
                "category",
                "sensitive",
            ]
        )
        for r in sorted(reads, key=lambda r: (r.name, r.file, r.line)):
            s = summaries[r.name]
            w.writerow(
                [
                    r.name,
                    r.file,
                    r.line,
                    r.read_style,
                    r.inferred_type,
                    r.default if r.default is not None else "",
                    r.assigned_to or "",
                    r.assign_line if r.assign_line is not None else "",
                    r.module_scope,
                    r.in_config_dir,
                    r.is_ee,
                    s.category,
                    s.sensitive,
                ]
            )


def write_json(reads: list[EnvRead], out: Path) -> None:
    summaries = summarize(reads)
    payload = {
        "vars": {
            name: {
                "read_count": s.read_count,
                "types": sorted(s.types),
                "defaults": sorted(s.defaults),
                "files": sorted(s.files),
                "constants": sorted(s.constants),
                "in_config_dir": s.in_config_dir,
                "ad_hoc_only": s.ad_hoc_only,
                "is_ee": s.is_ee,
                "category": s.category,
                "sensitive": s.sensitive,
            }
            for name, s in sorted(summaries.items())
        },
        # `file::const -> [assignment line numbers]`; dead code (last write wins).
        # Surfaced here so the --json artifact carries the duplication signal for
        # a CI drift gate, not just the human report.
        "duplicates": find_duplicate_assignments(reads),
        "reads": [
            asdict(r) for r in sorted(reads, key=lambda r: (r.name, r.file, r.line))
        ],
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, help="write full per-read manifest to CSV")
    parser.add_argument(
        "--json", type=Path, help="write summarized + raw manifest to JSON"
    )
    parser.add_argument(
        "--drift-only",
        action="store_true",
        help="print only the deployment drift report",
    )
    parser.add_argument(
        "--shortlist",
        action="store_true",
        help="print only the operator-facing-tunable + undocumented names "
        "(one per line; for piping into doc-gen / a CI gate)",
    )
    parser.add_argument(
        "--write-baseline",
        nargs="?",
        type=Path,
        const=BASELINE_PATH,
        metavar="PATH",
        help="snapshot the current should-document set to the drift baseline "
        f"(default: {BASELINE_PATH.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--check-baseline",
        nargs="?",
        type=Path,
        const=BASELINE_PATH,
        metavar="PATH",
        help="CI drift gate: exit non-zero if the should-document set drifts "
        f"from the committed baseline (default: {BASELINE_PATH.relative_to(REPO_ROOT)})",
    )
    args = parser.parse_args()

    reads = collect_reads()
    if not reads:
        print(
            "No env reads found — are you running from the repo root?", file=sys.stderr
        )
        return 1

    if args.write_baseline is not None:
        path = args.write_baseline
        path.parent.mkdir(parents=True, exist_ok=True)
        current = should_document_list(reads)
        path.write_text(format_baseline(current), encoding="utf-8")
        print(f"Wrote drift baseline ({len(current)} undocumented tunables) -> {path}")
        return 0

    if args.check_baseline is not None:
        path = args.check_baseline
        if not path.exists():
            print(
                f"Drift baseline not found: {path}\n"
                "Generate it with: python backend/scripts/env_inventory.py "
                "--write-baseline",
                file=sys.stderr,
            )
            return 1
        current = should_document_list(reads)
        new_drift, resolved = diff_baseline(set(current), read_baseline(path))
        if not new_drift and not resolved:
            print(
                f"env drift gate OK — {len(current)} undocumented operator-facing "
                "tunables, all baselined."
            )
            return 0
        if new_drift:
            print(
                f"❌ {len(new_drift)} NEW undocumented operator-facing env var(s):",
                file=sys.stderr,
            )
            for n in new_drift:
                print(f"    + {n}", file=sys.stderr)
            print(
                "  → Document each in deployment/docker_compose/env.template and "
                "deployment/helm/charts/onyx/values.yaml,\n"
                "    or (if intentionally left undocumented) regenerate the baseline.",
                file=sys.stderr,
            )
        if resolved:
            print(
                f"⚠️  {len(resolved)} baseline entr(y/ies) no longer undocumented "
                "(now documented or removed) — baseline is stale:",
                file=sys.stderr,
            )
            for n in resolved:
                print(f"    - {n}", file=sys.stderr)
        print(
            "  → Regenerate: python backend/scripts/env_inventory.py --write-baseline",
            file=sys.stderr,
        )
        return 1

    if args.shortlist:
        for n in should_document_list(reads):
            print(n)
        return 0

    if args.csv:
        write_csv(reads, args.csv)
        print(f"Wrote {len(reads)} read sites -> {args.csv}")
    if args.json:
        write_json(reads, args.json)
        print(f"Wrote manifest -> {args.json}")
    if not (args.csv or args.json) or args.drift_only:
        human_report(reads, drift_only=args.drift_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
