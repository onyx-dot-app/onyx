import ast
import re
import subprocess
from pathlib import Path

import pytest
from lint import check_gate_changes
from lint.check_gate_changes import check_change, violations


@pytest.mark.parametrize(
    ("file", "row"),
    [
        ("db_ops_outside_db_baseline.txt", "file.py {}"),
        ("no_http_exception_baseline.txt", "file.py {}"),
        ("no_direct_redis_baseline.txt", "{} file.py"),
        ("no_response_model_baseline.txt", "{} file.py"),
        ("test_skip_baseline.txt", "{} file.py"),
        ("test_sleep_baseline.txt", "{} file.py"),
    ],
)
def test_count_ratchet(file: str, row: str) -> None:
    path = f"backend/lint/{file}"
    assert check_change(path, row.format(1), row.format(2))
    assert check_change(path, "", row.format(1))
    assert check_change(path, row.format(2), row.format(1)) is None
    assert check_change(path, row.format(1), "") is None


@pytest.mark.parametrize(
    ("path", "row"),
    [
        ("backend/lint/celery_task_allowlist.txt", "task package.task: reason"),
        ("backend/lint/celery_task_allowlist.txt", "beat nightly: reason"),
        ("backend/scripts/env_inventory_baseline.txt", "FEATURE_ENABLED"),
    ],
)
def test_set_ratchet(path: str, row: str) -> None:
    assert check_change(path, "", row)
    assert check_change(path, row, "") is None


@pytest.mark.parametrize(
    "marker",
    [
        "celery-expires: allow (reason)",
        "db-ops-outside-db: allow reason",
        "http-exception: allow reason",
        "migration-determinism: allow",
        "no-response-model: allow reason",
        "no-direct-redis: allow reason",
        "noqa: S101 - reason",
        "noqa: C901",
        "noqa",
        "ruff: noqa: S101",
        "flake8: noqa",
    ],
)
def test_suppression_ratchet(marker: str) -> None:
    path = "backend/onyx/example.py"
    clean = "run()\n"
    suppressed = f"run()  # {marker}\n"
    assert check_change(path, clean, suppressed)
    assert check_change(path, suppressed, clean) is None
    assert check_change(path, suppressed, f"other()\n{suppressed}") is None


def test_marker_text_in_string() -> None:
    assert check_change("example.py", "", 'text = "# noqa: S101"') is None
    assert check_change("example.py", "", 'text = "no-direct-redis: allow"')


@pytest.mark.parametrize(
    "path",
    [
        "backend/lint/check_celery_task_expires.py",
        "backend/scripts/check_migration_determinism.py",
        ".pre-commit-config.yaml",
        ".github/workflows/pr-quality-checks.yml",
        ".github/workflows/pr-gate-changes.yml",
        ".github/CODEOWNERS",
        "backend/onyx/.ruff.toml",
    ],
)
def test_gate_edit_requires_approval(path: str) -> None:
    assert check_change(path, "old", "new")


@pytest.mark.parametrize("table", ["per-file-ignores", "extend-per-file-ignores"])
def test_ruff_per_file_ratchet(table: str) -> None:
    section = f"[tool.ruff.lint.{table}]\n"
    original = section + '"file.py" = ["S101", "C901"]\n'
    reduced = section + '"file.py" = ["S101"]\n'
    assert check_change("pyproject.toml", reduced, original)
    assert check_change("pyproject.toml", section, reduced)
    assert check_change("pyproject.toml", original, reduced) is None
    assert check_change("pyproject.toml", original, "") is None


def test_ruff_config_and_unrelated_toml() -> None:
    assert check_change("pyproject.toml", "", '[tool.ruff.lint]\nignore = ["S101"]')
    assert check_change("pyproject.toml", "", '[project]\nname = "onyx"') is None


@pytest.mark.parametrize(
    ("file", "before", "looser", "tighter", "reason"),
    [
        (
            "backend/lint/no_direct_redis_baseline.txt",
            "2 file.py",
            "3 file.py",
            "1 file.py",
            "baseline entry added or increased",
        ),
        (
            "web/tests/example.spec.tsx",
            "await page.waitForTimeout(1);",
            "await page.waitForTimeout(1); /* test-flakes: allow reviewed */",
            "",
            "suppression added or edited",
        ),
    ],
)
def test_git_diff_reads_committed_gate_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file: str,
    before: str,
    looser: str,
    tighter: str,
    reason: str,
) -> None:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], text=True).strip()

    monkeypatch.chdir(tmp_path)
    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    path = Path(file)
    path.parent.mkdir(parents=True)

    def commit(source: str) -> str:
        path.write_text(source + "\n")
        git("add", str(path))
        git("commit", "-qm", "fixture")
        return git("rev-parse", "HEAD")

    base = commit(before)
    weakened = commit(looser)
    tightened = commit(tighter)
    assert violations(base, weakened) == [(file, reason)]
    assert violations(base, tightened) == []


@pytest.mark.parametrize("prefix", ["run()  # noqa", "# ruff: noqa", "# flake8: noqa"])
def test_reduce_noqa_selectors(prefix: str) -> None:
    path = "example.py"
    broad = f"{prefix}: S101, C901"
    narrow = f"{prefix}: C901"
    assert check_change(path, broad, narrow) is None
    assert check_change(path, narrow, broad)
    assert check_change(path, narrow, prefix)
    assert check_change(path, prefix, narrow) is None


def test_unchanged_line_becomes_active() -> None:
    assert check_change(
        "example.py",
        'text = """\n# ruff: noqa: S101\n"""\n',
        'text = ""\n# ruff: noqa: S101\nassert False\n',
    )


def test_migration_marker_in_sql_string() -> None:
    assert check_change(
        "backend/alembic/versions/example.py",
        'op.execute("INSERT INTO example VALUES (now())")',
        'op.execute("INSERT INTO example VALUES (now()) -- migration-determinism: allow")',
    )


def test_empty_nested_ruff_config_requires_approval() -> None:
    assert check_change("backend/onyx/pyproject.toml", "", "[tool.ruff]")


@pytest.mark.parametrize(
    "source",
    [
        "assert ready  # ruff: ignore[S101]",
        "# ruff: disable[S101]\nassert ready\n# ruff: enable[S101]",
    ],
)
def test_ruff_bracket_suppressions(source: str) -> None:
    assert check_change("example.py", "", source)
    assert check_change("example.py", source, "assert ready") is None
    assert check_change("example.py", "", repr(source)) is None


def test_ruff_range_can_shrink_but_cannot_extend() -> None:
    start = "# ruff: disable[S101, C901]\nassert ready\n"
    end = "# ruff: enable[S101, C901]\nassert other\n"
    narrow = start.replace("S101, C901", "S101")
    assert check_change("example.py", start + end, narrow + end) is None
    assert check_change("example.py", start + end, start + "assert other\n")
    assert check_change("example.py", start + "assert other\n", start + end) is None


@pytest.mark.parametrize(
    ("path", "clean", "exception"),
    [
        (
            "backend/alembic/versions/rev.py",
            "op.create_index()",
            "# migration-design: allow blocking-index - reviewed",
        ),
        (
            "backend/tests/unit/example.py",
            "time.sleep(1)",
            "# test-flakes: allow reviewed",
        ),
        (
            "web/tests/e2e/test.spec.ts",
            "await page.waitForTimeout(1);",
            "// test-flakes: allow reviewed",
        ),
        (
            "web/tests/e2e/test.spec.tsx",
            "await page.waitForTimeout(1);",
            "/* test-flakes: allow reviewed */",
        ),
    ],
)
def test_stack_markers(path: str, clean: str, exception: str) -> None:
    allowed = f"{clean}  {exception}\n"
    assert check_change(path, clean, allowed)
    assert check_change(path, allowed, clean) is None


@pytest.mark.parametrize("selector", ["S113", "DTZ", "TID251"])
def test_stack_ruff_ignores(selector: str) -> None:
    clean = '[tool.ruff.lint.per-file-ignores]\n"file.py" = ["S101"]\n'
    allowed = clean.replace('"S101"', f'"S101", "{selector}"')
    assert check_change("pyproject.toml", clean, allowed)
    assert check_change("pyproject.toml", allowed, clean) is None


def test_import_boundary_exception_ratchet() -> None:
    path = "backend/lint/import_boundaries.toml"
    clean = '[[contract]]\nname = "provider-sdks"\nexternal_forbidden = ["openai"]\n'
    allowed = clean + (
        '[[contract.exception]]\nimporter = "adapter.py"\n'
        'imports = "openai"\nreason = "SDK adapter"\n'
    )
    assert check_change(path, clean, allowed)
    assert check_change(path, allowed, clean) is None
    assert check_change(path, allowed, allowed.replace("adapter.py", "other.py"))
    assert check_change(path, clean, clean.replace('["openai"]', "[]"))


def test_all_backend_gate_definitions_have_coverage() -> None:
    root = Path(__file__).resolve().parents[4]
    lint = root / "backend/lint"
    definitions = [
        *(
            path
            for path in lint.glob("check_*.py")
            if path.name != "check_gate_changes.py"
        ),
        root / "backend/scripts/check_migration_determinism.py",
    ]
    policy_files = {
        path
        for pattern in ("*_baseline.txt", "*_allowlist.txt", "*.toml")
        for path in lint.glob(pattern)
    }
    for path in definitions:
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            for marker in re.findall(r"[a-z][a-z0-9-]*: allow\b", node.value):
                assert marker in (
                    *check_gate_changes.MARKERS,
                    *check_gate_changes.RAW_MARKERS,
                ), path
            if re.fullmatch(r"[\w-]+\.(?:toml|txt)", node.value):
                definition = lint / node.value
                if definition.is_file():
                    policy_files.add(definition)

    for path in policy_files:
        relative = path.relative_to(root).as_posix()
        if path.suffix == ".toml":
            assert check_change(relative, "", path.read_text())
        else:
            assert relative in (
                check_gate_changes.COUNT_BASELINES.keys()
                | check_gate_changes.SET_BASELINES
            )
            assert check_change(relative, path.read_text(), "") is None
