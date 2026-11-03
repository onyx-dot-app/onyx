"""Enterprise code loads only when the build ships a real `ee.onyx` package.

`is_ee_available` rejects a missing `ee` package, a bare `ee` package, and an
`ee/onyx` directory with no `__init__.py`. `set_is_ee_if_available` selects
the Enterprise Edition only when `is_ee_available` is true.
"""

from importlib.machinery import ModuleSpec
from unittest.mock import patch

import pytest

from onyx.utils import variable_functionality
from onyx.utils.variable_functionality import (
    global_version,
    is_ee_available,
    set_is_ee_if_available,
)


def test_ee_is_available_when_the_package_is_real() -> None:
    # Mocked, so this also runs on the MIT-only mirror, which has no `ee.onyx`.
    with patch(
        "onyx.utils.variable_functionality.importlib.util.find_spec",
        return_value=ModuleSpec("ee.onyx", loader=None, origin="ee/onyx/__init__.py"),
    ):
        assert is_ee_available()


def test_ee_is_unavailable_with_no_ee_package() -> None:
    with patch(
        "onyx.utils.variable_functionality.importlib.util.find_spec",
        side_effect=ModuleNotFoundError("No module named 'ee'"),
    ):
        assert not is_ee_available()


@pytest.mark.parametrize(
    "spec",
    [
        # The MIT-only mirror: a bare `ee` package with no `onyx` inside.
        None,
        # A leftover `ee/onyx` directory with no `__init__.py`.
        ModuleSpec("ee.onyx", loader=None, origin=None),
    ],
)
def test_ee_is_unavailable_without_a_real_package(spec: ModuleSpec | None) -> None:
    with patch(
        "onyx.utils.variable_functionality.importlib.util.find_spec",
        return_value=spec,
    ):
        assert not is_ee_available()


@pytest.mark.parametrize("available", [True, False])
def test_ee_loads_only_when_the_build_ships_it(available: bool) -> None:
    with patch.object(
        variable_functionality, "is_ee_available", return_value=available
    ):
        set_is_ee_if_available()
    try:
        assert global_version.is_ee_version() is available
    finally:
        global_version.unset_ee()
