import hashlib
import hmac
from typing import Literal, Protocol

from pydantic import BaseModel, ValidationError

from onyx.db.models import Marketplace
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.github_auth import github_authorization_header
from onyx.skills.marketplace.github_webhooks import GitHubWebhooks
from onyx.skills.marketplace.models import MarketplaceArchive, MarketplaceProvider
from onyx.utils.github import (
    GITHUB_ARCHIVE_MAX_BYTES,
    GITHUB_COMMIT_SHA_PATTERN,
    GitHubSource,
    download_github_archive,
    resolve_github_revision,
)


class _Repository(BaseModel):
    full_name: str


class _Delivery(BaseModel):
    repository: _Repository
    ref: str | None = None


WebhookResult = Literal["ignored", "received", "sync"]


class MarketplaceProviderAdapter(Protocol):
    """Provider owns login, ref resolution, change checks and webhook capability."""

    @property
    def supports_webhooks(self) -> bool: ...

    def verify_webhook(
        self, raw_body: bytes, *, signature: str, event: str, hook_id: str
    ) -> WebhookResult: ...

    def resolve_revision(self) -> str: ...

    def resolve_webhook_ref(self) -> str: ...

    def register_webhook(self, callback_url: str) -> str: ...

    def remove_webhook(self) -> None: ...

    def fetch_if_changed(self, *, force: bool = False) -> MarketplaceArchive | None: ...


class GitHubMarketplaceAdapter(MarketplaceProviderAdapter):
    def __init__(self, marketplace: Marketplace, tenant_id: str) -> None:
        self.marketplace = marketplace
        self.tenant_id = tenant_id

    @property
    def supports_webhooks(self) -> bool:
        # Registration and its management UI are not enabled yet.
        return False

    def verify_webhook(
        self, raw_body: bytes, *, signature: str, event: str, hook_id: str
    ) -> WebhookResult:
        """Verify delivery without provider I/O, including during a locked recheck."""
        if (
            self.marketplace.webhook_secret is None
            or self.marketplace.webhook_ref is None
        ):
            raise OnyxError(OnyxErrorCode.NOT_FOUND)
        secret = self.marketplace.webhook_secret.get_value(apply_mask=False)
        if not secret:
            raise OnyxError(OnyxErrorCode.NOT_FOUND)
        expected = (
            "sha256="
            + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        )
        if not hmac.compare_digest(signature.encode("utf-8"), expected.encode("ascii")):
            raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
        if (
            event != "ping"
            and self.marketplace.webhook_id is not None
            and hook_id != self.marketplace.webhook_id
        ):
            raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
        try:
            delivery = _Delivery.model_validate_json(raw_body)
        except ValidationError as exc:
            raise OnyxError(
                OnyxErrorCode.BAD_REQUEST, "Invalid GitHub delivery."
            ) from exc
        config = self.marketplace.provider_config
        if (
            delivery.repository.full_name.casefold()
            != f"{config.owner}/{config.repo}".casefold()
        ):
            raise OnyxError(
                OnyxErrorCode.BAD_REQUEST, "GitHub repository does not match."
            )
        if self.marketplace.webhook_id is None or event not in {"ping", "push"}:
            return "ignored"
        if event == "ping" and hook_id != self.marketplace.webhook_id:
            return "ignored"
        if event == "push" and delivery.ref is None:
            raise OnyxError(OnyxErrorCode.BAD_REQUEST, "GitHub push has no ref.")
        configured_refs = (
            {config.ref}
            if config.ref.startswith("refs/")
            else {f"refs/heads/{config.ref}", f"refs/tags/{config.ref}"}
        )
        should_sync = (
            event == "push"
            and self.marketplace.webhook_id is not None
            and not GITHUB_COMMIT_SHA_PATTERN.fullmatch(config.ref)
            and delivery.ref == self.marketplace.webhook_ref
            and (
                self.marketplace.webhook_ref in configured_refs
                or (
                    config.ref == "HEAD"
                    and self.marketplace.webhook_ref.startswith("refs/heads/")
                )
            )
        )
        return "sync" if should_sync else "received"

    def _authorization(self) -> str | None:
        return github_authorization_header(
            self.tenant_id, self.marketplace.login_user_id, require_user_connection=True
        )

    def _webhooks(self) -> GitHubWebhooks:
        authorization = self._authorization()
        if authorization is None:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Connect GitHub before configuring push updates.",
            )
        return GitHubWebhooks(self.marketplace.provider_config, authorization)

    def resolve_webhook_ref(self) -> str:
        return self._webhooks().resolve_ref()

    def register_webhook(self, callback_url: str) -> str:
        secret = self.marketplace.webhook_secret
        if secret is None or self.marketplace.webhook_ref is None:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Save webhook signing state before registration.",
            )
        return self._webhooks().ensure(callback_url, secret.get_value(apply_mask=False))

    def remove_webhook(self) -> None:
        if self.marketplace.webhook_id is not None:
            self._webhooks().remove(self.marketplace.webhook_id)

    def _source(self) -> GitHubSource:
        config = self.marketplace.provider_config
        # One tail item prevents a branch containing slashes being read as a folder.
        return GitHubSource(config.owner, config.repo, tree_tail=(config.ref,))

    def resolve_revision(self) -> str:
        return resolve_github_revision(self._source(), self._authorization()).revision

    def fetch_if_changed(self, *, force: bool = False) -> MarketplaceArchive | None:
        authorization = self._authorization()
        source = self._source()
        # Resolve pinned SHAs through GitHub too; do not use the SHA shortcut.
        revision = resolve_github_revision(source, authorization).revision
        if not force and revision == self.marketplace.last_synced_revision:
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
