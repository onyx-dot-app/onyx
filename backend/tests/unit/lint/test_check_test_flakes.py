from pathlib import Path

from lint.check_test_flakes import check, playwright_findings, python_findings, scan


def test_python_calls_and_markers() -> None:
    source = """
from time import sleep as pause
import pytest as p
pause(1)
pause(1)  # test-flakes: allow exercise an actual timeout
@p.mark.skip
def test_bare(): pass
@p.mark.skipif(False, reason=f"Requires {platform} support")
def test_reason(): pass
p.skip(reason=" ")
p.skip("Service unavailable")
p.mark.skip(reason="test-flakes: allow")
p.skip(f"{env_name} is not set.")
p.skip(f"{dynamic_reason}")
"""
    assert sorted(python_findings(source)) == [
        (4, "sleep", False),
        (5, "sleep", True),
        (6, "skip", False),
        (8, "skip", True),
        (10, "skip", False),
        (11, "skip", True),
        (12, "skip", True),
        (13, "skip", True),
        (14, "skip", False),
    ]


def test_playwright_calls_and_markers() -> None:
    source = """
// page.waitForTimeout(100)
const sample = "test.skip()";
await page.waitForTimeout(100); // test-flakes: allow exercise a timeout
await page.waitForTimeout(100); // test-flakes: allow
test.skip(!enabled, "Feature is disabled");
test.skip("The title", async () => {});
test.describe.fixme("Group title", () => {});
test.fixme(); // test-flakes: allow tracked in issue #1234
test.skip(!enabled, `${feature} is disabled`);
test.skip(!enabled, `${dynamicReason}`);
"""
    assert list(playwright_findings(source)) == [
        (4, "sleep", True),
        (5, "sleep", False),
        (6, "skip", True),
        (7, "skip", False),
        (8, "skip", False),
        (9, "skip", True),
        (10, "skip", True),
        (11, "skip", False),
    ]


def test_sleep_and_skip_counts_ratchet_independently(tmp_path: Path) -> None:
    file = tmp_path / "backend/tests/test_example.py"
    file.parent.mkdir(parents=True)
    file.write_text("import time\nimport pytest\ntime.sleep(1)\n")
    assert check(tmp_path, tmp_path, write=True) == 0
    assert check(tmp_path, tmp_path) == 0

    file.write_text("import time\nimport pytest\ntime.sleep(1)\ntime.sleep(2)\n")
    assert check(tmp_path, tmp_path) == 1

    file.write_text("import time\nimport pytest\ntime.sleep(1)\npytest.skip()\n")
    assert check(tmp_path, tmp_path) == 1

    file.write_text("import pytest\npytest.skip()\n")
    assert check(tmp_path, tmp_path) == 1


def test_python_format_reasons_need_fixed_text() -> None:
    source = """
pytest.skip("Requires {}".format(service))
pytest.skip("{}".format(reason))
pytest.skip("{0:>10}".format(reason))
pytest.skip("missing {".format(reason))
pytest.skip(get_reason())
"""
    assert list(python_findings(source)) == [
        (2, "skip", True),
        (3, "skip", False),
        (4, "skip", False),
        (5, "skip", False),
        (6, "skip", False),
    ]


def test_playwright_test_import_aliases() -> None:
    source = """
import { test as pwTest } from "@playwright/test";
import { test as other } from "./unrelated";
pwTest.skip("Disabled case", async () => {});
pwTest . describe . fixme("Disabled group", () => {});
pwTest.fixme(!enabled, "Feature is disabled");
other.skip();
"""
    assert list(playwright_findings(source)) == [
        (4, "skip", False),
        (5, "skip", False),
        (6, "skip", True),
    ]


def test_playwright_extended_objects_and_fixture_imports(tmp_path: Path) -> None:
    web_tests = tmp_path / "web/tests/e2e"
    web_tests.mkdir(parents=True)
    (web_tests / "fixtures.ts").write_text(
        'import { test as base } from "@playwright/test";\n'
        "export const test = base.extend<{ flag: boolean }>({});\n"
        "export const worldTest = test.extend({});\n"
        "export const unrelated = helper.extend({});\n"
    )
    (web_tests / "menu.spec.ts").write_text(
        'import { test } from "@playwright/test";\n'
        'import { worldTest as world, unrelated } from "./fixtures";\n'
        'import { worldTest } from "@tests/e2e/fixtures";\n'
        "const localTest = world.extend({});\n"
        "test.skip();\n"
        'world.skip("Disabled title", async () => {});\n'
        'worldTest.describe.fixme("Disabled group", () => {});\n'
        'localTest.fixme(!enabled, "Missing feature");\n'
        "unrelated.skip();\n"
    )
    assert list(scan(tmp_path)) == [
        ("web/tests/e2e/menu.spec.ts", (5, "skip", False)),
        ("web/tests/e2e/menu.spec.ts", (6, "skip", False)),
        ("web/tests/e2e/menu.spec.ts", (7, "skip", False)),
        ("web/tests/e2e/menu.spec.ts", (8, "skip", True)),
    ]


def test_scan_flags_unresolved_plain_playwright_test(tmp_path: Path) -> None:
    tests = tmp_path / "web/tests/e2e"
    tests.mkdir(parents=True)
    (tests / "fixtures.ts").write_text('export { test } from "@playwright/test";\n')
    (tests / "example.spec.ts").write_text(
        'import { test } from "./fixtures";\ntest.skip();\ntest.fixme();\n'
    )

    assert list(scan(tmp_path)) == [
        ("web/tests/e2e/example.spec.ts", (2, "skip", False)),
        ("web/tests/e2e/example.spec.ts", (3, "skip", False)),
    ]
