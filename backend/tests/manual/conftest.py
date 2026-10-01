"""Root conftest for the opt-in manual suites under ``backend/tests/manual``.

No CI workflow collects this directory. This conftest is the second guard: it
skips every test in it unless the gate env vars of the test's suite are
``true``. A test that declares no gate is skipped too (fail closed), so an
accidental ``pytest backend/tests`` never spends money or changes a deployment.

The ``manual_suite`` marker is registered in ``backend/pytest.ini``.

Do NOT import ``tests.utils.pytest_secrets`` or any AWS secrets helper here or
in any manual suite. Manual suites read keys from plain env vars only.
"""

from pathlib import Path

import pytest

from tests.manual.gates import (
    MANUAL_SUITE_MARKER,
    README_PATH,
    missing_gates,
    skip_reason,
)

_MANUAL_TESTS_DIR = Path(__file__).resolve().parent


def _is_manual_test(item: pytest.Item) -> bool:
    return item.path.resolve().is_relative_to(_MANUAL_TESTS_DIR)


def pytest_collection_modifyitems(
    config: pytest.Config,  # noqa: ARG001
    items: list[pytest.Item],
) -> None:
    # pytest calls this hook with every collected item in the session, not only
    # the items below this directory, so filter on the path first.
    for item in items:
        if not _is_manual_test(item):
            continue
        marker = item.get_closest_marker(MANUAL_SUITE_MARKER)
        if marker is None or not marker.args:
            item.add_marker(
                pytest.mark.skip(
                    reason=(
                        "Manual test without an opt-in gate. Add "
                        "`pytestmark = manual_suite(...)` from tests.manual.gates. "
                        f"See {README_PATH}."
                    )
                )
            )
            continue
        missing = missing_gates(tuple(str(arg) for arg in marker.args))
        if missing:
            item.add_marker(pytest.mark.skip(reason=skip_reason(missing)))
