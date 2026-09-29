from pathlib import Path

import pytest

from tests.utils import aws_secrets
from tests.utils.secret_names import TestSecret


def test_local_secret_resolves_enum_name_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = TestSecret.JIRA_API_TOKEN
    monkeypatch.setenv(secret.name, "test-token")
    monkeypatch.setattr(aws_secrets, "_DOTENV_PATH", str(tmp_path / ".env"))

    assert aws_secrets._get_local_secrets([secret]) == {secret: "test-token"}
