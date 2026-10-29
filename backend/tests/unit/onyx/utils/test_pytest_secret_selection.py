"""Deselected tests must not require credentials for an active test run."""

from pathlib import Path

import pytest

pytest_plugins = ["pytester"]


@pytest.mark.parametrize("selection", [("-m", "not nightly"), ("-k", "test_selected")])
def test_secrets_include_only_selected_tests(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    selection: tuple[str, str],
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[4]))
    pytester.makeini("[pytest]\nmarkers = nightly: excluded provider tests")
    pytester.makeconftest(
        """
        from unittest.mock import patch

        import pytest

        from tests.utils.secret_names import TestSecret

        pytest_plugins = ["tests.utils.pytest_secrets"]

        @pytest.fixture(scope="session", autouse=True)
        def local_secrets():
            with patch(
                "tests.utils.pytest_secrets.get_secrets",
                return_value={TestSecret.OPENAI_API_KEY: "test-placeholder"},
            ) as resolver:
                yield
            resolver.assert_called_once_with([TestSecret.OPENAI_API_KEY])
        """
    )
    pytester.makepyfile(
        """
        import pytest

        from tests.utils.secret_names import TestSecret

        @pytest.mark.secrets(TestSecret.OPENAI_API_KEY)
        def test_selected(test_secrets):
            assert test_secrets[TestSecret.OPENAI_API_KEY] == "test-placeholder"

        @pytest.mark.nightly
        @pytest.mark.secrets(TestSecret.BEDROCK_API_KEY)
        def test_nightly(test_secrets):
            pytest.fail("This test must be deselected")
        """
    )

    result = pytester.runpytest_subprocess(*selection, "-q")

    result.assert_outcomes(passed=1, deselected=1)
