from typing import Any
from unittest.mock import MagicMock, patch

from onyx.db.credentials import fetch_github_access_token_for_repo
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.utils.sensitive import SensitiveValue

_CC_PAIRS_FN = (
    "onyx.db.connector_credential_pair.get_connector_credential_pairs_for_source"
)


def _sensitive_json(payload: str) -> SensitiveValue[dict[str, Any]]:
    return SensitiveValue(
        encrypted_bytes=payload.encode("utf-8"),
        decrypt_fn=lambda raw: raw.decode("utf-8"),
        is_json=True,
    )


def _cc_pair(
    credential: Any,
    repo_owner: str,
    repositories: str,
    include_code_files: bool = True,
    access_type: AccessType = AccessType.PUBLIC,
    status: ConnectorCredentialPairStatus = ConnectorCredentialPairStatus.ACTIVE,
) -> MagicMock:
    cc_pair = MagicMock()
    cc_pair.access_type = access_type
    cc_pair.status = status
    cc_pair.credential = credential
    cc_pair.connector.connector_specific_config = {
        "repo_owner": repo_owner,
        "repositories": repositories,
        "include_code_files": include_code_files,
    }
    return cc_pair


def _fetch(cc_pairs: list[Any], repo_owner: str, repo_name: str) -> str | None:
    with patch(_CC_PAIRS_FN, return_value=cc_pairs):
        return fetch_github_access_token_for_repo(
            db_session=MagicMock(), repo_owner=repo_owner, repo_name=repo_name
        )


def _credential_with_token() -> MagicMock:
    credential = MagicMock()
    credential.id = 7
    credential.credential_json = _sensitive_json('{"github_access_token": "tok"}')
    return credential


def test_returns_token_for_named_repo() -> None:
    """Regression: credential_json is a SensitiveValue, not a dict — the
    token must be read via get_value, not attribute access on the wrapper."""
    cc_pair = _cc_pair(_credential_with_token(), "Onyx-Dot-App", "onyx, other-repo")

    assert _fetch([cc_pair], "onyx-dot-app", "Onyx") == "tok"


def test_emits_audit_event_on_decrypt() -> None:
    """The token reaches an LLM-driven agent, so the decrypt must be audited
    like every other connector-credential read."""
    cc_pair = _cc_pair(_credential_with_token(), "owner", "repo")

    with patch("onyx.db.credentials.emit_credential_access") as emit:
        assert _fetch([cc_pair], "owner", "repo") == "tok"

    emit.assert_called_once_with(
        credential_type="connector", provider="github", row_id=7
    )


def test_skips_credential_without_json() -> None:
    credential = MagicMock()
    credential.credential_json = None
    cc_pair = _cc_pair(credential, "owner", "repo")

    assert _fetch([cc_pair], "owner", "repo") is None


def test_ignores_unnamed_repo_and_wrong_owner() -> None:
    cc_pair = _cc_pair(_credential_with_token(), "owner", "some-other-repo")
    assert _fetch([cc_pair], "owner", "repo") is None

    cc_pair.connector.connector_specific_config["repo_owner"] = "different-owner"
    cc_pair.connector.connector_specific_config["repositories"] = "repo"
    assert _fetch([cc_pair], "owner", "repo") is None


def test_skips_connector_that_does_not_index_code() -> None:
    """A PR/issue-only connector never exposed the source tree; its token
    must not hand the full repo to the coding agent."""
    cc_pair = _cc_pair(
        _credential_with_token(), "owner", "repo", include_code_files=False
    )

    assert _fetch([cc_pair], "owner", "repo") is None


def test_skips_non_public_and_inactive_pairs() -> None:
    private = _cc_pair(
        _credential_with_token(), "owner", "repo", access_type=AccessType.SYNC
    )
    assert _fetch([private], "owner", "repo") is None

    paused = _cc_pair(
        _credential_with_token(),
        "owner",
        "repo",
        status=ConnectorCredentialPairStatus.PAUSED,
    )
    assert _fetch([paused], "owner", "repo") is None
