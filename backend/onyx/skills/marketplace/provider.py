from typing import Protocol

from onyx.db.models import Marketplace
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.github_auth import github_authorization_header
from onyx.skills.marketplace.models import MarketplaceArchive, MarketplaceProvider
from onyx.utils.github import (
    GITHUB_ARCHIVE_MAX_BYTES,
    GitHubSource,
    download_github_archive,
    resolve_github_revision,
)


class MarketplaceProviderAdapter(Protocol):
    """Provider owns login, ref resolution, change checks and webhook capability."""

    @property
    def supports_webhooks(self) -> bool: ...

    def resolve_revision(self) -> str: ...

    def fetch_if_changed(self) -> MarketplaceArchive | None: ...


class GitHubMarketplaceAdapter(MarketplaceProviderAdapter):
    def __init__(self, marketplace: Marketplace, tenant_id: str) -> None:
        self.marketplace = marketplace
        self.tenant_id = tenant_id

    @property
    def supports_webhooks(self) -> bool:
        # W1 adds self-hosted webhook registration and signature/ref checks here.
        return False

    def _authorization(self) -> str | None:
        return github_authorization_header(
            self.tenant_id, self.marketplace.login_user_id, require_user_connection=True
        )

    def _source(self) -> GitHubSource:
        config = self.marketplace.provider_config
        # One tail item prevents a branch containing slashes being read as a folder.
        return GitHubSource(config.owner, config.repo, tree_tail=(config.ref,))

    def resolve_revision(self) -> str:
        return resolve_github_revision(self._source(), self._authorization()).revision

    def fetch_if_changed(self) -> MarketplaceArchive | None:
        authorization = self._authorization()
        source = self._source()
        # Even a pinned SHA must exist in the repository; do not use the SHA shortcut.
        revision = resolve_github_revision(source, authorization).revision
        if revision == self.marketplace.last_synced_revision:
            return None
        return MarketplaceArchive(
            revision=revision,
            archive_bytes=download_github_archive(
                source, revision, authorization, max_size_bytes=GITHUB_ARCHIVE_MAX_BYTES
            ),
            folder=self.marketplace.provider_config.folder,
        )


def get_marketplace_adapter(
    marketplace: Marketplace, tenant_id: str
) -> MarketplaceProviderAdapter:
    if marketplace.provider == MarketplaceProvider.GITHUB:
        return GitHubMarketplaceAdapter(marketplace, tenant_id)
    raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Unsupported marketplace provider.")
