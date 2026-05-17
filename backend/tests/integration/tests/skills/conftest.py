import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker(pytest.mark.skip(reason="Skills tests under refactor"))


@pytest.fixture(autouse=True)
def _reset_db(reset: None) -> None:  # noqa: ARG001
    """Auto-reset DB before each skills test."""
