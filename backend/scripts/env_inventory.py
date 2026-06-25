"""Environment-variable inventory for the Onyx backend.

AST-walks the backend (and optionally the frontend) to build a canonical
manifest of every environment variable the code actually reads, then
cross-references the deployment files (docker-compose env templates + Helm
values/configmap) to surface drift:

  * read-but-undocumented  -> code reads a var no template mentions
  * documented-but-unread  -> a template advertises a var no code reads
  * duplicate assignments  -> same module-level constant assigned 2+ times
                              (last write wins; the rest are dead code)

This is read-only: it never edits anything. It is meant to be the single
source of truth that `env.template` / Helm `values.yaml` can be diff-checked
against in CI.

Usage:
    python backend/scripts/env_inventory.py                # human summary
    python backend/scripts/env_inventory.py --csv out.csv  # full manifest
    python backend/scripts/env_inventory.py --json out.json
    python backend/scripts/env_inventory.py --drift-only   # just the drift report

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

    def __init__(self, rel_path: str, is_ee: bool) -> None:
        self.rel_path = rel_path
        self.is_ee = is_ee
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
        # os.environ.get("X", default) / os.getenv("X", default)
        if isinstance(func, ast.Attribute):
            name = _str_const(node.args[0]) if node.args else None
            if name is not None and re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
                # os.environ.get(...)
                if (
                    func.attr == "get"
                    and isinstance(func.value, ast.Attribute)
                    and func.value.attr == "environ"
                ):
                    default = (
                        _literal_default(node.args[1]) if len(node.args) > 1 else None
                    )
                    self._record(name, node.lineno, "environ.get", node, default)
                # os.getenv(...)
                elif func.attr == "getenv":
                    default = (
                        _literal_default(node.args[1]) if len(node.args) > 1 else None
                    )
                    self._record(name, node.lineno, "getenv", node, default)
        # custom helper: _non_negative_int_env("X", 250)
        elif isinstance(func, ast.Name) and func.id in ENV_HELPER_FUNCS:
            name = _str_const(node.args[0]) if node.args else None
            if name is not None:
                default = _literal_default(node.args[1]) if len(node.args) > 1 else None
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
        # os.environ["X"]
        value = node.value
        if isinstance(value, ast.Attribute) and value.attr == "environ":
            name = _str_const(node.slice)
            if name is not None and re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
                self._record(name, node.lineno, "environ[]", node, default=None)
        self.generic_visit(node)


def iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        yield path


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
            visitor = EnvVisitor(rel, is_ee)
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
        print(f"  {n:45s} [{loc}] {sorted(s.types)}")
    print()
    print(
        f"DOCUMENTED-BUT-UNREAD ({len(documented_unread)}): templates advertise "
        "these, no code reads them (possibly dead/renamed)"
    )
    for n in documented_unread:
        print(f"  {n}")


def write_csv(reads: list[EnvRead], out: Path) -> None:
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
            ]
        )
        for r in sorted(reads, key=lambda r: (r.name, r.file, r.line)):
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
            }
            for name, s in sorted(summaries.items())
        },
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
    args = parser.parse_args()

    reads = collect_reads()
    if not reads:
        print(
            "No env reads found — are you running from the repo root?", file=sys.stderr
        )
        return 1

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
