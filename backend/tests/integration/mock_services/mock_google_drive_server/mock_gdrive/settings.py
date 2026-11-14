"""Settings of the mock Google Drive server.

The server reads them at startup from MOCK_GDRIVE_CONFIG (a JSON object) or
MOCK_GDRIVE_CONFIG_FILE (a JSON file). `PATCH /_mock/config` changes the quota,
latency and fault settings of a running server, and `POST /_mock/corpus`
generates a new corpus.
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DOC_MIME = "application/vnd.google-apps.document"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
SLIDES_MIME = "application/vnd.google-apps.presentation"
FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TEXT_MIME = "text/plain"
MARKDOWN_MIME = "text/markdown"

GOOGLE_NATIVE_MIMES = frozenset({DOC_MIME, SHEET_MIME, SLIDES_MIME})
UPLOADED_MIMES = frozenset({PDF_MIME, DOCX_MIME, PPTX_MIME, TEXT_MIME, MARKDOWN_MIME})
CONTENT_MIMES = GOOGLE_NATIVE_MIMES | UPLOADED_MIMES

SCOPE_PREFIX = "https://www.googleapis.com/auth/"


class _Settings(BaseModel):
    # A misspelled key fails the request instead of keeping the default.
    model_config = ConfigDict(extra="forbid")


class ExternalShareSettings(_Settings):
    """Files owned by accounts outside the domain. Each recipient gets the same
    set, as when a set of external files is shared with several domain users.
    The token endpoint refuses to impersonate the owners."""

    # Accounts ext1@<owner_domain> ... extN@<owner_domain>.
    owners: int = Field(default=2, ge=1)
    owner_domain: str = "gmail.com"
    files: int = Field(default=50, ge=0)
    # The first `recipients` non-admin domain users.
    recipients: int = Field(default=3, ge=1)


class BulkUploadSettings(_Settings):
    """Bursts of files that share one whole-second modifiedTime, as a bulk
    upload gives."""

    # Files in each burst.
    count: int = Field(ge=1)
    bursts: int = Field(default=1, ge=1)
    # Seconds between the bursts.
    spacing_seconds: int = Field(default=2, ge=1)
    start: datetime = datetime(2025, 6, 1, 7, 58, tzinfo=timezone.utc)
    # "my_drive": the My Drive of user `index` (0 is the admin).
    # "shared_drive": shared drive `index`.
    # "external": owned by external account `index` and shared with the
    # external_shares recipients.
    container: Literal["my_drive", "shared_drive", "external"] = "my_drive"
    index: int = Field(default=0, ge=0)


class FolderTreeSettings(_Settings):
    """A folder tree for folder targets (shared_folder_urls). The corpus
    summary lists its root folder in `folder_tree_root_ids`."""

    container: Literal["my_drive", "shared_drive"] = "my_drive"
    # A user index (0 is the admin) or a shared drive index.
    index: int = Field(default=0, ge=0)
    # Folder levels under the tree's root folder.
    depth: int = Field(default=3, ge=0)
    # Subfolders of each folder above the last level.
    branching: int = Field(default=2, ge=1)
    files_per_folder: int = Field(default=3, ge=0)
    # Extra files in the first folder of the last level.
    deepest_folder_files: int = Field(default=0, ge=0)


class CorpusSettings(_Settings):
    """The shape of the generated Workspace. The same settings always give the
    same corpus."""

    seed: int = 42
    domain: str = "onyx-mock.test"
    # The first user is the domain admin, admin@<domain>.
    num_users: int = Field(default=8, ge=1)
    num_groups: int = Field(default=3, ge=0)
    num_shared_drives: int = Field(default=3, ge=0)
    files_per_shared_drive: int = Field(default=150, ge=0)
    files_per_user: int = Field(default=40, ge=0)
    # Folders in each shared drive and each My Drive.
    folders_per_container: int = Field(default=8, ge=0)
    max_folder_depth: int = Field(default=3, ge=1)
    # Share of My Drive files shared with other users, groups or the domain.
    share_fraction: float = Field(default=0.3, ge=0, le=1)
    shortcut_fraction: float = Field(default=0.02, ge=0, le=1)
    # Share of shared drives the admin is a member of.
    admin_drive_membership: float = Field(default=0.5, ge=0, le=1)
    # Relative weights of the content mime types.
    mime_weights: dict[str, float] = Field(
        default_factory=lambda: {
            DOC_MIME: 0.35,
            SHEET_MIME: 0.12,
            SLIDES_MIME: 0.05,
            PDF_MIME: 0.15,
            DOCX_MIME: 0.10,
            TEXT_MIME: 0.15,
            MARKDOWN_MIME: 0.08,
        }
    )
    # Content sizes follow a log-normal spread around this mean.
    avg_content_bytes: int = Field(default=6_000, ge=200)
    max_content_bytes: int = Field(default=200_000, ge=200)
    # Off by default, so the default corpus does not change.
    external_shares: ExternalShareSettings | None = None
    bulk_uploads: list[BulkUploadSettings] = Field(default_factory=list)
    folder_trees: list[FolderTreeSettings] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_mime_weights(self) -> "CorpusSettings":
        unknown = set(self.mime_weights) - CONTENT_MIMES
        if unknown:
            raise ValueError(f"Unsupported mime types in mime_weights: {unknown}")
        if any(
            weight < 0 or not math.isfinite(weight)
            for weight in self.mime_weights.values()
        ):
            raise ValueError("Each mime weight must be finite and not negative")
        if sum(self.mime_weights.values()) <= 0:
            raise ValueError("mime_weights must have a positive weight")
        return self

    @model_validator(mode="after")
    def _check_containers(self) -> "CorpusSettings":
        external = self.external_shares
        if external is not None and external.recipients > max(self.num_users - 1, 1):
            raise ValueError("external_shares.recipients is more than the users")
        targets: list[BulkUploadSettings | FolderTreeSettings] = [
            *self.bulk_uploads,
            *self.folder_trees,
        ]
        for target in targets:
            if target.container == "my_drive":
                limit = self.num_users
            elif target.container == "shared_drive":
                limit = self.num_shared_drives
            elif external is None:
                raise ValueError("An external bulk upload needs external_shares")
            else:
                limit = external.owners
            if target.index >= limit:
                raise ValueError(
                    f"No {target.container} with index {target.index} in the corpus"
                )
        return self


class QuotaSettings(_Settings):
    """Google's per-minute quotas. "units" is the quota model of GCP projects
    created on or after 2026-05-01; "requests" is the older one."""

    model: Literal["units", "requests", "off"] = "units"
    window_seconds: float = Field(default=60.0, gt=0)
    project_units_per_minute: int = 1_000_000
    user_units_per_minute: int = 325_000
    project_requests_per_minute: int = 12_000
    user_requests_per_minute: int = 12_000
    list_units: int = 100
    read_units: int = 5
    content_units: int = 200
    # The Docs API has its own quota, counted in requests.
    docs_project_reads_per_minute: int = 3_000
    docs_user_reads_per_minute: int = 300
    # None means no limit on the Admin SDK directory calls.
    admin_user_requests_per_minute: int | None = 2_400
    # Google answers a per-user limit with 403 userRateLimitExceeded and a
    # project limit with 429 rateLimitExceeded.
    user_limit_status: Literal[403, 429] = 403
    # Google usually sends no Retry-After header.
    retry_after_seconds: int | None = None


class LatencySettings(_Settings):
    """Time each call takes. A call waits its base time, scaled by a random
    factor in [1 - jitter, 1 + jitter], plus its body size over the bandwidth."""

    enabled: bool = True
    token_ms: float = 80
    metadata_ms: float = 100
    list_ms: float = 250
    content_ms: float = 300
    docs_api_ms: float = 250
    rate_limited_ms: float = 20
    jitter: float = Field(default=0.5, ge=0, le=1)
    bandwidth_bytes_per_second: float = Field(default=10_000_000, gt=0)


class FaultSettings(_Settings):
    # Share of API calls that fail with a 500 or 503.
    server_error_rate: float = Field(default=0.0, ge=0, le=1)
    # Scopes the service account may use with domain-wide delegation. None
    # grants every scope. A token request for any other scope fails with
    # unauthorized_client, as Google does.
    granted_scopes: list[str] | None = None
    service_account_email: str = "mock-indexer@onyx-mock-drive.iam.gserviceaccount.com"


class MockSettings(_Settings):
    corpus: CorpusSettings = Field(default_factory=CorpusSettings)
    quota: QuotaSettings = Field(default_factory=QuotaSettings)
    latency: LatencySettings = Field(default_factory=LatencySettings)
    faults: FaultSettings = Field(default_factory=FaultSettings)


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def load_settings_from_env() -> MockSettings:
    raw: dict[str, Any] = {}
    config_file = os.environ.get("MOCK_GDRIVE_CONFIG_FILE")
    if config_file:
        with open(config_file) as f:
            raw = deep_merge(raw, json.load(f))
    config_json = os.environ.get("MOCK_GDRIVE_CONFIG")
    if config_json:
        raw = deep_merge(raw, json.loads(config_json))
    return MockSettings.model_validate(raw)
