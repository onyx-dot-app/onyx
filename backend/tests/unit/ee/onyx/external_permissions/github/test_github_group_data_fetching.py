from typing import cast
from unittest.mock import MagicMock

from github import Github
from github.NamedUser import NamedUser
from github.Organization import Organization
from github.Repository import Repository

from ee.onyx.external_permissions.github.utils import (
    GitHubGroupSyncCache,
    form_collaborators_group_id,
    form_organization_group_id,
    get_external_access_permission,
    get_external_user_group,
)


class FakeUser:
    def __init__(self, login: str, email: str | None) -> None:
        self.login = login
        self._email = email
        self.email_reads = 0

    @property
    def email(self) -> str | None:
        self.email_reads += 1
        return self._email


def _private_repo(repo_id: int, collaborators: list[FakeUser]) -> Repository:
    repo = MagicMock(spec=Repository)
    repo.id = repo_id
    repo.name = f"repo-{repo_id}"
    repo.full_name = f"acme/repo-{repo_id}"
    repo.visibility = "private"
    repo.organization = MagicMock(spec=Organization)
    repo.get_collaborators.return_value = [
        cast(NamedUser, collaborator) for collaborator in collaborators
    ]
    return cast(Repository, repo)


def _internal_repo(repo_id: int, organization: Organization) -> Repository:
    repo = MagicMock(spec=Repository)
    repo.id = repo_id
    repo.name = f"repo-{repo_id}"
    repo.full_name = f"acme/repo-{repo_id}"
    repo.visibility = "internal"
    repo.organization = organization
    return cast(Repository, repo)


def test_private_repositories_use_one_group_and_cache_user_profiles() -> None:
    first_user = FakeUser("octocat", "octocat@example.com")
    repeated_user = FakeUser("octocat", "changed@example.com")
    first_repo = _private_repo(1, [first_user])
    second_repo = _private_repo(2, [repeated_user])
    github_client = MagicMock(spec=Github)
    cache = GitHubGroupSyncCache()

    first_groups = get_external_user_group(first_repo, github_client, cache)
    second_groups = get_external_user_group(second_repo, github_client, cache)

    assert [(group.id, group.user_emails) for group in first_groups] == [
        (form_collaborators_group_id(1), ["octocat@example.com"])
    ]
    assert [(group.id, group.user_emails) for group in second_groups] == [
        (form_collaborators_group_id(2), ["octocat@example.com"])
    ]
    assert first_user.email_reads == 1
    assert repeated_user.email_reads == 0
    cast(MagicMock, first_repo.get_teams).assert_not_called()
    cast(MagicMock, second_repo.get_teams).assert_not_called()
    github_client.get_organization.assert_not_called()


def test_private_repository_documents_reference_only_collaborator_group() -> None:
    repo = _private_repo(1, [])
    external_access = get_external_access_permission(
        repo, MagicMock(spec=Github), add_prefix=False
    )

    assert external_access.external_user_group_ids == {form_collaborators_group_id(1)}
    cast(MagicMock, repo.get_teams).assert_not_called()


def test_internal_organization_group_is_fetched_and_emitted_once() -> None:
    organization = MagicMock(spec=Organization)
    organization.id = 42
    organization.login = "acme"
    org_api = MagicMock(spec=Organization)
    org_user = FakeUser("octocat", "octocat@example.com")
    org_api.get_members.return_value = [cast(NamedUser, org_user)]
    github_client = MagicMock(spec=Github)
    github_client.get_organization.return_value = org_api
    cache = GitHubGroupSyncCache()

    first_groups = get_external_user_group(
        _internal_repo(1, cast(Organization, organization)),
        github_client,
        cache,
    )
    second_groups = get_external_user_group(
        _internal_repo(2, cast(Organization, organization)),
        github_client,
        cache,
    )

    assert [(group.id, group.user_emails) for group in first_groups] == [
        (form_organization_group_id(42), ["octocat@example.com"])
    ]
    assert second_groups == []
    assert org_user.email_reads == 1
    github_client.get_organization.assert_called_once_with("acme")
    org_api.get_members.assert_called_once_with(filter_="all")
