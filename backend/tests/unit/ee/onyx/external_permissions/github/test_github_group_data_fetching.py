from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, create_autospec, patch

import pytest

from ee.onyx.external_permissions.github.doc_sync import (
    _is_repo_visibility_changed_from_groups,
)
from ee.onyx.external_permissions.github.group_sync import github_group_sync
from ee.onyx.external_permissions.github.utils import (
    GitHubGroupSyncCache,
    form_collaborators_group_id,
    form_organization_group_id,
    get_external_access_permission,
    get_external_user_group,
)
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.github.models import GitHubRepository, GitHubUser
from onyx.connectors.github.source_operations import (
    GitHubApiError,
    GitHubSourceOperations,
)
from onyx.db.models import ConnectorCredentialPair


def _gateway(emails: dict[str, str | None] | None = None) -> MagicMock:
    gateway: MagicMock = create_autospec(GitHubSourceOperations, instance=True)
    known: dict[str, str | None] = emails or {}
    gateway.get_user.side_effect = lambda *, login: GitHubUser(
        login=login, email=known.get(login)
    )
    return gateway


def _repo(repo_id: int, visibility: str, **overrides: Any) -> GitHubRepository:
    return GitHubRepository.from_raw(
        {
            "id": repo_id,
            "name": f"repo-{repo_id}",
            "full_name": f"acme/repo-{repo_id}",
            "html_url": f"https://github.com/acme/repo-{repo_id}",
            "visibility": visibility,
            "private": visibility != "public",
            "owner": {"login": "acme", "id": 42, "type": "Organization"},
            **overrides,
        }
    )


def _cc_pair() -> ConnectorCredentialPair:
    credential_json = MagicMock()
    credential_json.get_value.return_value = {}
    return cast(
        ConnectorCredentialPair,
        SimpleNamespace(
            connector=SimpleNamespace(
                source=DocumentSource.GITHUB, connector_specific_config={}
            ),
            credential=SimpleNamespace(credential_json=credential_json),
        ),
    )


def test_private_repositories_use_one_group_and_cache_user_profiles() -> None:
    gateway = _gateway({"octocat": "octocat@example.com"})
    gateway.list_repository_collaborators.return_value = ["octocat"]
    cache = GitHubGroupSyncCache()

    first_groups = get_external_user_group(_repo(1, "private"), gateway, cache)
    second_groups = get_external_user_group(_repo(2, "private"), gateway, cache)

    assert [(group.id, group.user_emails) for group in first_groups] == [
        (form_collaborators_group_id(1), ["octocat@example.com"])
    ]
    assert [(group.id, group.user_emails) for group in second_groups] == [
        (form_collaborators_group_id(2), ["octocat@example.com"])
    ]
    # The profile is read once for both repositories.
    gateway.get_user.assert_called_once_with(login="octocat")
    gateway.list_organization_members.assert_not_called()


def test_private_repository_without_emails_has_no_group() -> None:
    gateway = _gateway({"octocat": None})
    gateway.list_repository_collaborators.return_value = ["octocat"]

    assert (
        get_external_user_group(_repo(1, "private"), gateway, GitHubGroupSyncCache())
        == []
    )


def test_private_repository_documents_reference_only_collaborator_group() -> None:
    external_access = get_external_access_permission(
        _repo(1, "private"), add_prefix=False
    )

    assert external_access.external_user_group_ids == {form_collaborators_group_id(1)}


def test_internal_repository_documents_reference_the_organization_group() -> None:
    external_access = get_external_access_permission(
        _repo(1, "internal"), add_prefix=True
    )

    assert external_access.external_user_group_ids == {
        build_ext_group_name_for_onyx(
            source=DocumentSource.GITHUB,
            ext_group_name=form_organization_group_id(42),
        )
    }


def test_public_repository_documents_are_public() -> None:
    assert get_external_access_permission(_repo(1, "public")).is_public


def test_unknown_visibility_is_treated_as_private() -> None:
    external_access = get_external_access_permission(_repo(1, "secret"))

    assert external_access.external_user_group_ids == {form_collaborators_group_id(1)}


def test_private_collaborator_fetch_failure_is_fatal() -> None:
    gateway = _gateway()
    gateway.list_repository_collaborators.side_effect = GitHubApiError(
        "500", status_code=500
    )

    with pytest.raises(GitHubApiError):
        get_external_user_group(_repo(1, "private"), gateway, GitHubGroupSyncCache())


def test_internal_organization_group_is_fetched_and_emitted_once() -> None:
    gateway = _gateway({"octocat": "octocat@example.com"})
    gateway.list_organization_members.return_value = ["octocat"]
    cache = GitHubGroupSyncCache()

    first_groups = get_external_user_group(_repo(1, "internal"), gateway, cache)
    second_groups = get_external_user_group(_repo(2, "internal"), gateway, cache)

    assert [(group.id, group.user_emails) for group in first_groups] == [
        (form_organization_group_id(42), ["octocat@example.com"])
    ]
    assert second_groups == []
    gateway.get_user.assert_called_once_with(login="octocat")
    gateway.list_organization_members.assert_called_once_with(org_login="acme")


def test_internal_member_fetch_failure_is_not_cached() -> None:
    gateway = _gateway()
    gateway.list_organization_members.side_effect = GitHubApiError(
        "500", status_code=500
    )
    cache = GitHubGroupSyncCache()

    with pytest.raises(GitHubApiError):
        get_external_user_group(_repo(1, "internal"), gateway, cache)

    assert cache.organization_groups_by_id == {}


def test_internal_repository_of_a_user_owner_is_an_error() -> None:
    repo = _repo(1, "internal", owner={"login": "octocat", "id": 7, "type": "User"})

    with pytest.raises(ValueError, match="has no organization"):
        get_external_user_group(repo, _gateway(), GitHubGroupSyncCache())


def test_visibility_change_is_read_from_the_existing_groups() -> None:
    private_group = build_ext_group_name_for_onyx(
        source=DocumentSource.GITHUB, ext_group_name=form_collaborators_group_id(1)
    )

    assert not _is_repo_visibility_changed_from_groups(
        _repo(1, "private"), [private_group]
    )
    assert _is_repo_visibility_changed_from_groups(_repo(1, "public"), [private_group])


def test_repository_failure_aborts_group_sync() -> None:
    connector = MagicMock()
    connector.fetch_configured_repos.return_value = [_repo(1, "private")]

    with (
        patch(
            "ee.onyx.external_permissions.github.group_sync.GithubConnector",
            return_value=connector,
        ),
        patch(
            "ee.onyx.external_permissions.github.group_sync.get_external_user_group",
            side_effect=GitHubApiError("500", status_code=500),
        ),
        pytest.raises(GitHubApiError),
    ):
        list(github_group_sync("tenant", _cc_pair()))
