from typing import Any
from unittest.mock import MagicMock

from onyx.db.credentials import fetch_github_access_token_for_repo
from onyx.utils.sensitive import SensitiveValue


def _sensitive_json(payload: str) -> SensitiveValue[dict[str, Any]]:
    return SensitiveValue(
        encrypted_bytes=payload.encode("utf-8"),
        decrypt_fn=lambda raw: raw.decode("utf-8"),
        is_json=True,
    )


def _db_session_returning(rows: list[tuple[Any, Any]]) -> MagicMock:
    db_session = MagicMock()
    db_session.execute.return_value.all.return_value = rows
    return db_session


def _connector(
    repo_owner: str, repositories: str, include_code_files: bool = True
) -> MagicMock:
    connector = MagicMock()
    connector.connector_specific_config = {
        "repo_owner": repo_owner,
        "repositories": repositories,
        "include_code_files": include_code_files,
    }
    return connector


def test_returns_token_for_named_repo() -> None:
    """Regression: credential_json is a SensitiveValue, not a dict — the
    token must be read via get_value, not attribute access on the wrapper."""
    credential = MagicMock()
    credential.credential_json = _sensitive_json('{"github_access_token": "tok"}')
    db_session = _db_session_returning(
        [(credential, _connector("Onyx-Dot-App", "onyx, other-repo"))]
    )

    token = fetch_github_access_token_for_repo(
        db_session=db_session, repo_owner="onyx-dot-app", repo_name="Onyx"
    )
    assert token == "tok"


def test_skips_credential_without_json() -> None:
    credential = MagicMock()
    credential.credential_json = None
    db_session = _db_session_returning([(credential, _connector("owner", "repo"))])

    token = fetch_github_access_token_for_repo(
        db_session=db_session, repo_owner="owner", repo_name="repo"
    )
    assert token is None


def test_ignores_unnamed_repo_and_wrong_owner() -> None:
    credential = MagicMock()
    credential.credential_json = _sensitive_json('{"github_access_token": "tok"}')
    connector = _connector("owner", "some-other-repo")
    db_session = _db_session_returning([(credential, connector)])

    assert (
        fetch_github_access_token_for_repo(
            db_session=db_session, repo_owner="owner", repo_name="repo"
        )
        is None
    )
    connector.connector_specific_config["repo_owner"] = "different-owner"
    connector.connector_specific_config["repositories"] = "repo"
    assert (
        fetch_github_access_token_for_repo(
            db_session=db_session, repo_owner="owner", repo_name="repo"
        )
        is None
    )


def test_no_repo_name_short_circuits() -> None:
    db_session = MagicMock()
    token = fetch_github_access_token_for_repo(
        db_session=db_session, repo_owner="owner", repo_name=None
    )
    assert token is None
    db_session.execute.assert_not_called()


def test_skips_connector_that_does_not_index_code() -> None:
    """A PR/issue-only connector never exposed the source tree; its token
    must not hand the full repo to the coding agent."""
    credential = MagicMock()
    credential.credential_json = _sensitive_json('{"github_access_token": "tok"}')
    db_session = _db_session_returning(
        [(credential, _connector("owner", "repo", include_code_files=False))]
    )

    token = fetch_github_access_token_for_repo(
        db_session=db_session, repo_owner="owner", repo_name="repo"
    )
    assert token is None
