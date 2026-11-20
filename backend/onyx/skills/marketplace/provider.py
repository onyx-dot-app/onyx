from typing import Final, Protocol

from onyx.db.enums import MarketplaceKind
from onyx.db.models import Marketplace
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.ingest_from_github import (
    GITHUB_ARCHIVE_MAX_BYTES,
    read_repository_archive,
)
from onyx.skills.marketplace.models import (
    GitHubMarketplaceConfig,
    GitHubRepoSource,
    MarketplaceArchive,
)
from onyx.utils.github import (
    GitHubSource,
    download_github_archive,
    fetch_github_tree,
    resolve_github_revision,
)

REMOTE_REPOSITORY_MAX_COUNT: Final = 20


class MarketplaceProviderAdapter(Protocol):
    def resolve_revision(self) -> str: ...

    def fetch(self, revision: str) -> MarketplaceArchive: ...

    def fetch_remote(self, source: GitHubRepoSource) -> dict[str, bytes]: ...


class GitHubMarketplaceAdapter(MarketplaceProviderAdapter):
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

    def fetch(self, revision: str) -> MarketplaceArchive:
        source = self._source()
        archive_bytes = download_github_archive(
            source,
            revision,
            self.authorization,
            max_size_bytes=GITHUB_ARCHIVE_MAX_BYTES,
        )
        try:
            tree_shas = fetch_github_tree(source, revision, self.authorization)
        except OnyxError:
            # Tree hashes are a record only; the files decide each version.
            tree_shas = None
        return MarketplaceArchive(
            revision=revision, archive_bytes=archive_bytes, tree_shas=tree_shas
        )

    def fetch_remote(self, source: GitHubRepoSource) -> dict[str, bytes]:
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
    if (
        marketplace.kind != MarketplaceKind.GITHUB
        or marketplace.provider_config is None
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "This is not a GitHub marketplace."
        )
    return GitHubMarketplaceConfig.model_validate(marketplace.provider_config)


def marketplace_adapter(
    marketplace: Marketplace, authorization: str | None
) -> MarketplaceProviderAdapter:
    return GitHubMarketplaceAdapter(marketplace_config(marketplace), authorization)
