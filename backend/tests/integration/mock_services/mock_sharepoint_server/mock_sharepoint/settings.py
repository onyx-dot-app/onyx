"""Settings of the mock SharePoint server.

The server reads them at startup from MOCK_SHAREPOINT_CONFIG (a JSON object) or
MOCK_SHAREPOINT_CONFIG_FILE (a JSON file). `PATCH /_mock/config` changes the
quota, latency and fault settings of a running server, and `POST /_mock/corpus`
generates a new corpus.
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

GRAPH_HOST = "graph.microsoft.com"
LOGIN_HOST = "login.microsoftonline.com"
SHAREPOINT_SUFFIX = "sharepoint.com"
GRAPH_BASE = f"https://{GRAPH_HOST}/v1.0"

# File extension -> mime type, for the files Onyx indexes.
SUPPORTED_MIMES: dict[str, str] = {
    "txt": "text/plain",
    "md": "text/markdown",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
}
# Files Onyx must skip.
UNSUPPORTED_MIMES: dict[str, str] = {
    "zip": "application/zip",
    "exe": "application/x-msdownload",
}


class _Settings(BaseModel):
    # A misspelled key fails the request instead of keeping the default.
    model_config = ConfigDict(extra="forbid")


class CorpusSettings(_Settings):
    """The shape of the generated tenant. The same settings always give the
    same corpus."""

    seed: int = 42
    # The SharePoint host is <tenant>.sharepoint.com.
    tenant: str = Field(default="onyxmock", pattern=r"^[a-z0-9]+$")
    # Users sign in as user<N>@<user_domain>. None gives <tenant>.onmicrosoft.com.
    user_domain: str | None = None
    num_sites: int = Field(default=3, ge=1)
    # Personal (OneDrive) sites in the site listing. They have no content.
    num_personal_sites: int = Field(default=1, ge=0)
    # The first library of each site is "Documents".
    libraries_per_site: int = Field(default=2, ge=1)
    # Folder levels under the root of each library.
    folder_depth: int = Field(default=2, ge=0)
    # Subfolders of each folder above the last level.
    folder_branching: int = Field(default=2, ge=1)
    # Supported files in each folder and in each library root.
    files_per_folder: int = Field(default=3, ge=0)
    # Files of a type Onyx skips, in the root of each library.
    unsupported_files_per_library: int = Field(default=2, ge=0)
    pages_per_site: int = Field(default=3, ge=0)
    # Pages whose canvasLayout fails to expand, as a page with duplicate web
    # part ids does. The page listing with $expand=canvasLayout then fails too.
    corrupt_canvas_pages_per_site: int = Field(default=0, ge=0)
    num_users: int = Field(default=8, ge=1)
    num_security_groups: int = Field(default=3, ge=0)
    num_m365_groups: int = Field(default=1, ge=0)
    # Share of files and folders with broken inheritance.
    unique_permission_fraction: float = Field(default=0.15, ge=0, le=1)
    # Share of the items with broken inheritance that grant read to
    # "Everyone except external users".
    public_fraction: float = Field(default=0.1, ge=0, le=1)
    # Share of files with a sharing link. A link breaks inheritance.
    sharing_link_fraction: float = Field(default=0.05, ge=0, le=1)
    # Relative weights of the supported file extensions.
    extension_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "txt": 0.3,
            "md": 0.2,
            "docx": 0.2,
            "pptx": 0.1,
            "pdf": 0.2,
        }
    )
    avg_content_bytes: int = Field(default=1_500, ge=100)
    max_content_bytes: int = Field(default=20_000, ge=100)
    # Created and modified times are spread over the 30 days before this time.
    base_time: datetime = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)

    @field_validator("base_time")
    @classmethod
    def _base_time_in_utc(cls, value: datetime) -> datetime:
        """A time with no zone is UTC. The corpus compares it with aware times."""
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _check_weights(self) -> "CorpusSettings":
        unknown = set(self.extension_weights) - set(SUPPORTED_MIMES)
        if unknown:
            raise ValueError(f"Unsupported extensions in extension_weights: {unknown}")
        weights = self.extension_weights.values()
        if any(weight < 0 or not math.isfinite(weight) for weight in weights):
            raise ValueError("Each extension weight must be finite and not negative")
        if sum(weights) <= 0:
            raise ValueError("extension_weights must have a positive weight")
        if self.corrupt_canvas_pages_per_site > self.pages_per_site:
            raise ValueError("corrupt_canvas_pages_per_site is more than the pages")
        return self

    @property
    def sharepoint_host(self) -> str:
        return f"{self.tenant}.{SHAREPOINT_SUFFIX}"

    @property
    def email_domain(self) -> str:
        return self.user_domain or f"{self.tenant}.onmicrosoft.com"


class QuotaSettings(_Settings):
    """Microsoft's resource units (RU). The server counts them for each app:
    a (tenant id, client id) pair."""

    enabled: bool = True
    window_seconds: float = Field(default=60.0, gt=0)
    ru_per_minute: int = Field(default=1_250, ge=0)
    # None means no daily limit.
    ru_per_day: int | None = Field(default=None, ge=0)
    day_window_seconds: float = Field(default=86_400.0, gt=0)
    item_get_ru: int = Field(default=1, ge=0)
    delta_with_token_ru: int = Field(default=1, ge=0)
    delta_without_token_ru: int = Field(default=2, ge=0)
    download_ru: int = Field(default=1, ge=0)
    # A fetch of a pre-authenticated download URL is not a Graph call.
    download_url_ru: int = Field(default=0, ge=0)
    list_children_ru: int = Field(default=2, ge=0)
    permission_ru: int = Field(default=5, ge=0)
    rest_ru: int = Field(default=2, ge=0)
    other_ru: int = Field(default=1, ge=0)
    throttle_status: Literal[429, 503] = 429
    # The Retry-After value, and the length of the pause that follows a
    # throttled call. None sends no header and starts no pause.
    retry_after_seconds: int | None = Field(default=10, ge=1)
    # A throttled call also uses its RU.
    count_throttled_calls: bool = True


class LatencySettings(_Settings):
    """Time each call takes. A call waits its base time, scaled by a random
    factor in [1 - jitter, 1 + jitter], plus its body size over the bandwidth."""

    # An infinite wait would hang every call of that kind.
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    enabled: bool = True
    token_ms: float = Field(default=80, ge=0)
    metadata_ms: float = Field(default=100, ge=0)
    list_ms: float = Field(default=250, ge=0)
    content_ms: float = Field(default=300, ge=0)
    rest_ms: float = Field(default=150, ge=0)
    throttled_ms: float = Field(default=20, ge=0)
    jitter: float = Field(default=0.5, ge=0, le=1)
    bandwidth_bytes_per_second: float = Field(default=10_000_000, gt=0)


class FaultSettings(_Settings):
    # Share of API calls that fail with a 500 or 503.
    server_error_rate: float = Field(default=0.0, ge=0, le=1)
    # Every delta call with a token answers 410 Gone. `token=latest` and a call
    # without a token still work.
    expire_delta_tokens: bool = False
    # Seconds a pre-authenticated download URL stays valid. 0 gives a URL
    # that is always expired.
    download_url_ttl_seconds: int = Field(default=3_600, ge=0)
    download_url_expired_status: Literal[401, 403] = 401
    # The next N fetches of a download URL answer throttle_status with
    # Retry-After, as SharePoint's download host does (activityLimitReached).
    # Each throttled fetch takes one from the count.
    download_url_throttled_calls: int = Field(default=0, ge=0)
    download_url_retry_after_seconds: int = Field(default=1, ge=1)
    # /content answers 302 to a download URL, as Graph does. False sends the
    # bytes.
    content_redirect: bool = True


class AuthSettings(_Settings):
    """The app registration of GET /_mock/credentials. The token endpoint
    accepts any client id, so a test can sign in as more than one app."""

    client_id: str = "11111111-2222-4333-8444-555555555555"
    client_secret: str = "mock-client-secret"
    app_display_name: str = "Onyx mock indexer"
    certificate_password: str = "mock-certificate-password"
    # SharePoint REST refuses an app-only token that did not come from a
    # certificate.
    rest_requires_certificate: bool = True


class PagingSettings(_Settings):
    """Page sizes of the listings whose callers send no $top."""

    sites_page_size: int = Field(default=200, ge=1)
    site_pages_page_size: int = Field(default=100, ge=1)
    children_page_size: int = Field(default=200, ge=1)
    directory_page_size: int = Field(default=100, ge=1)
    # SharePoint REST sends a whole collection when the caller sends no $top.
    rest_page_size: int | None = Field(default=None, ge=1)


class MockSettings(_Settings):
    corpus: CorpusSettings = Field(default_factory=CorpusSettings)
    quota: QuotaSettings = Field(default_factory=QuotaSettings)
    latency: LatencySettings = Field(default_factory=LatencySettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    paging: PagingSettings = Field(default_factory=PagingSettings)
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
    config_file = os.environ.get("MOCK_SHAREPOINT_CONFIG_FILE")
    if config_file:
        with open(config_file) as f:
            raw = deep_merge(raw, json.load(f))
    config_json = os.environ.get("MOCK_SHAREPOINT_CONFIG")
    if config_json:
        raw = deep_merge(raw, json.loads(config_json))
    return MockSettings.model_validate(raw)
