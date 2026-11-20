from typing import Final

from onyx.db.enums import MarketplaceKind
from onyx.db.models import Marketplace
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.ingest_from_github import (
    GITHUB_ARCHIVE_MAX_BYTES,
    RepositoryArchive,
    read_repository_archive,
)
from onyx.skills.marketplace.models import (
    GitHubMarketplaceConfig,
    GitHubRepoSource,
)
from onyx.utils.github import (
    GitHubSource,
    download_github_archive,
    resolve_github_revision,
)

REMOTE_REPOSITORY_MAX_COUNT: Final = 20


class GitHubMarketplaceAdapter:
    def __init__(
        self, config: GitHubMarketplaceConfig, authorization: str | None
    ) -> None:
        self.config = config
        self.authorization = authorization

    def _source(self) -> GitHubSource:
        # One tail part keeps a branch with "/" in its name whole.
        return GitHubSource(
            owner=self.config.owner,
            repo=self.config.repo,
            tree_tail=(self.config.ref,) if self.config.ref else (),
        )

    def resolve_revision(self) -> str:
        return resolve_github_revision(self._source(), self.authorization).revision

    def fetch(self, revision: str) -> bytes:
        return download_github_archive(
            self._source(),
            revision,
            self.authorization,
            max_size_bytes=GITHUB_ARCHIVE_MAX_BYTES,
        )

    def fetch_remote(self, source: GitHubRepoSource) -> RepositoryArchive:
        github_source = GitHubSource(
            owner=source.owner,
            repo=source.repo,
            tree_tail=(source.ref,) if source.ref else (),
        )
        revision = resolve_github_revision(
            github_source, self.authorization, revision=source.sha
        ).revision
        return read_repository_archive(
            download_github_archive(
                github_source,
                revision,
                self.authorization,
                max_size_bytes=GITHUB_ARCHIVE_MAX_BYTES,
            )
        )


def marketplace_config(marketplace: Marketplace) -> GitHubMarketplaceConfig:
    if marketplace.kind != MarketplaceKind.GITHUB or marketplace.repository is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "This is not a GitHub marketplace."
        )
    owner, repo = marketplace.repository.split("/", 1)
    return GitHubMarketplaceConfig(
        owner=owner,
        repo=repo,
        folder=marketplace.folder or None,
        ref=marketplace.ref or None,
    )
