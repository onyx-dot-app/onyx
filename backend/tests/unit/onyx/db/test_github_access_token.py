from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID

from onyx.db.credentials import ConnectorRepoAccess, fetch_github_repo_access
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus, Permission
from onyx.utils.sensitive import SensitiveValue

_CC_PAIRS_FN = (
    "onyx.db.connector_credential_pair.get_connector_credential_pairs_for_user"
)

_USER_ID = UUID("11111111-2222-3333-4444-555555555555")


def _user(is_anonymous: bool = False) -> MagicMock:
    user = MagicMock()
    user.id = _USER_ID
    user.is_anonymous = is_anonymous
    return user


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
    branch: str | None = None,
    pair_id: int = 1,
) -> MagicMock:
    cc_pair = MagicMock()
    cc_pair.id = pair_id
    cc_pair.access_type = access_type
    cc_pair.status = status
    cc_pair.credential = credential
    cc_pair.connector.connector_specific_config = {
        "repo_owner": repo_owner,
        "repositories": repositories,
        "include_code_files": include_code_files,
        "branch": branch,
    }
    return cc_pair


def _access(
    cc_pairs: list[Any],
    repo_owner: str,
    repo_name: str,
    user: MagicMock | None = None,
    group_shared_ids: set[int] | None = None,
    manages_connectors: bool = True,
) -> ConnectorRepoAccess | None:
    user = user or _user()
    with (
        patch(_CC_PAIRS_FN, return_value=cc_pairs) as lookup,
        patch(
            "onyx.db.credentials.get_effective_permissions",
            return_value=(
                {Permission.MANAGE_CONNECTORS} if manages_connectors else set()
            ),
        ),
        patch(
            "onyx.db.credentials._group_shared_cc_pair_ids",
            return_value=group_shared_ids or set(),
        ),
    ):
        access = fetch_github_repo_access(
            db_session=MagicMock(),
            repo_owner=repo_owner,
            repo_name=repo_name,
            user=user,
        )
    if user.is_anonymous:
        lookup.assert_not_called()
        return access
    # The gate is the acting user's own read access, not a global listing.
    assert lookup.call_args.kwargs["user"] is user
    assert lookup.call_args.kwargs["get_editable"] is False
    return access


def _fetch(cc_pairs: list[Any], repo_owner: str, repo_name: str) -> str | None:
    access = _access(cc_pairs, repo_owner, repo_name)
    return access.token if access else None


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


def test_emits_audit_event_with_actor_on_decrypt() -> None:
    """The token reaches an LLM-driven agent, so the decrypt must be audited
    like every other connector-credential read — and name who triggered it."""
    cc_pair = _cc_pair(_credential_with_token(), "owner", "repo")

    with patch("onyx.db.credentials.emit_credential_access") as emit:
        assert _fetch([cc_pair], "owner", "repo") == "tok"

    emit.assert_called_once_with(
        credential_type="connector",
        provider="github",
        row_id=7,
        user_id=str(_USER_ID),
        resource="owner/repo",
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


def test_skips_permission_synced_pairs() -> None:
    """SYNC pairs carry per-document ACLs: a user entitled to some of a repo's
    files can be entitled to few of them, and a repo archive is all-or-nothing.
    cc-pair access cannot stand in for it, so these never qualify."""
    synced = _cc_pair(
        _credential_with_token(), "owner", "repo", access_type=AccessType.SYNC
    )

    assert _fetch([synced], "owner", "repo") is None


def test_private_pair_qualifies_when_the_user_may_read_it() -> None:
    """The lookup only returns pairs this user may read, so a private pair
    reaching the loop means the user is in one of its groups."""
    private = _cc_pair(
        _credential_with_token(), "owner", "repo", access_type=AccessType.PRIVATE
    )

    assert _fetch([private], "owner", "repo") == "tok"


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


def test_anonymous_users_never_receive_a_credential() -> None:
    """An anonymously reachable persona must not turn a PUBLIC connector into
    private source access, and the audit line would name nobody."""
    cc_pair = _cc_pair(_credential_with_token(), "owner", "repo")

    assert _access([cc_pair], "owner", "repo", user=_user(is_anonymous=True)) is None


def test_curator_without_group_membership_is_refused() -> None:
    """READ_CONNECTORS (implied by managing document sets) returns every pair
    from the listing. Listing a connector is not holding its PAT."""
    private = _cc_pair(
        _credential_with_token(), "owner", "repo", access_type=AccessType.PRIVATE
    )

    assert _access([private], "owner", "repo", manages_connectors=False) is None
    assert (
        _access(
            [private],
            "owner",
            "repo",
            manages_connectors=False,
            group_shared_ids={private.id},
        )
        is not None
    )


def test_access_reports_the_indexed_branch() -> None:
    """The grant covers what the connector indexes, so the caller can pin the
    read to that branch instead of one the model asked for."""
    cc_pair = _cc_pair(_credential_with_token(), "owner", "repo", branch=" main ")

    access = _access([cc_pair], "owner", "repo")

    assert access == ConnectorRepoAccess(token="tok", branch="main")


def test_the_newest_matching_pair_wins() -> None:
    """Several connectors can index one repo with different PATs; which one
    answers must not depend on row order."""
    older = _cc_pair(_credential_with_token(), "owner", "repo", pair_id=1)
    newer_credential = MagicMock()
    newer_credential.id = 9
    newer_credential.credential_json = _sensitive_json(
        '{"github_access_token": "newer"}'
    )
    newer = _cc_pair(newer_credential, "owner", "repo", pair_id=2)

    assert _fetch([older, newer], "owner", "repo") == "newer"
    assert _fetch([newer, older], "owner", "repo") == "newer"
