"""Record sanitized Graph responses for the OneDrive fixture corpus."""

from __future__ import annotations

import argparse
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, RootModel
from scripts.onedrive.provision_test_corpus import (
    FIXTURE_ROOT_NAME,
    FilePath,
    FixtureConfig,
    FixtureState,
    FolderPath,
    OneDriveFixtureProvisioner,
    build_provisioner,
    load_fixture_config,
)

from onyx.connectors.microsoft_utils.drive_delta import (
    DRIVE_DELTA_SELECT_FIELDS,
    build_onedrive_delta_request_headers,
    fetch_drive_delta_checkpoint_page,
)
from tests.utils.secret_names import TestSecret

logger = logging.getLogger(__name__)

SPIKE_PAGE_SIZE = 50
SPIKE_SCHEMA_VERSION = 2
DEFAULT_SPIKE_FIXTURE_PATH = (
    Path(__file__).parents[2]
    / "tests/unit/onyx/connectors/onedrive/fixtures/tenant_spike.json"
)
EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
TIMESTAMP_PATTERN = re.compile(
    r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\b"
)
REQUEST_ID_KEYS = frozenset(
    {
        "request-id",
        "client-request-id",
        "requestId",
        "clientRequestId",
    }
)
CURSOR_QUERY_KEYS = frozenset({"token", "$skiptoken", "$deltatoken"})
SAFE_QUERY_KEYS = frozenset({"$select", "$top"})
HASH_KEY_PATTERN = re.compile(r"(?<!^)(?=[A-Z])")
PLACEHOLDER_PATTERN = re.compile(r"(<[^<>]+>)")
UUID_PATTERN = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
)
RAW_DRIVE_ID_PATTERN = re.compile(r"(?i)\bb(?:!|%21)[A-Za-z0-9_-]+")
TENANT_HOST_PATTERN = re.compile(r"https://(?!<)[^\"/]+")
REQUEST_ID_PATTERN = re.compile(
    r'"(?:request-id|client-request-id|requestId|clientRequestId)"\s*:'
)
UNREDACTED_HASH_PATTERN = re.compile(r'"[A-Za-z0-9]*Hash"\s*:\s*"(?!<)')
CERTIFICATE_SECRET_KEYS = (
    TestSecret.PERM_SYNC_SHAREPOINT_CLIENT_ID,
    TestSecret.PERM_SYNC_SHAREPOINT_PRIVATE_KEY,
    TestSecret.PERM_SYNC_SHAREPOINT_CERTIFICATE_PASSWORD,
    TestSecret.PERM_SYNC_SHAREPOINT_DIRECTORY_ID,
)


class RecorderArgs(BaseModel):
    apply: bool
    output: Path


class GraphPayload(RootModel[dict[str, Any]]):
    pass


class SensitivePattern(str, Enum):
    UUID = "uuid"
    DRIVE_ID = "drive_id"
    EMAIL = "email"
    TENANT_HOST = "tenant_host"
    REQUEST_ID = "request_id"
    HASH = "hash"
    TIMESTAMP = "timestamp"


SENSITIVE_PATTERNS: dict[SensitivePattern, re.Pattern[str]] = {
    SensitivePattern.UUID: UUID_PATTERN,
    SensitivePattern.DRIVE_ID: RAW_DRIVE_ID_PATTERN,
    SensitivePattern.EMAIL: EMAIL_PATTERN,
    SensitivePattern.TENANT_HOST: TENANT_HOST_PATTERN,
    SensitivePattern.REQUEST_ID: REQUEST_ID_PATTERN,
    SensitivePattern.HASH: UNREDACTED_HASH_PATTERN,
    SensitivePattern.TIMESTAMP: TIMESTAMP_PATTERN,
}


class SanitizationScan(BaseModel):
    counts: dict[SensitivePattern, int]

    @property
    def is_clean(self) -> bool:
        return not any(self.counts.values())


class DeltaRecording(BaseModel):
    pages: list[GraphPayload]
    fixture_item_count: int
    shared_changed_count: int
    tombstone_count: int


class SpikeObservation(BaseModel):
    schema_version: int = SPIKE_SCHEMA_VERSION
    delta_request_headers: dict[str, str]
    full_delta_pages: list[GraphPayload]
    incremental_delta_pages: list[GraphPayload]
    permission_shapes: dict[str, GraphPayload]
    group_transitive_member_shapes: dict[str, GraphPayload]
    full_fixture_item_count: int
    incremental_fixture_item_count: int
    observations: list[str]


def scan_sanitized_fixture(serialized: str) -> SanitizationScan:
    return SanitizationScan(
        counts={
            name: len(pattern.findall(serialized))
            for name, pattern in SENSITIVE_PATTERNS.items()
        }
    )


class StableSanitizer:
    """Replace tenant-specific values while preserving response relationships."""

    def __init__(self, replacements: dict[str, str]) -> None:
        self._replacements = replacements
        self._generated: dict[tuple[str, str], str] = {}

    @classmethod
    def from_state(cls, state: FixtureState, config: FixtureConfig) -> StableSanitizer:
        replacements = {
            state.owner.id: "<owner-user-id>",
            state.second_owner.id: "<second-owner-user-id>",
            state.primary_user.id: "<primary-user-id>",
            state.alternate_user.id: "<alternate-user-id>",
            state.drive.id: "<owner-drive-id>",
            state.second_drive.id: "<second-owner-drive-id>",
            state.site.id: "<owner-site-id>",
            state.root_item.id: "<fixture-root-item-id>",
            state.visible_group.id: "<visible-group-id>",
            state.hidden_group.id: "<hidden-group-id>",
            state.second_drive_duplicate.id: "<second-drive-duplicate-item-id>",
            config.owner_upn: "<owner-email>",
            config.second_owner_upn: "<second-owner-email>",
            config.primary_upn: "<primary-user-email>",
            config.alternate_upn: "<alternate-user-email>",
            config.owner_upn.replace("@", "_").replace(".", "_"): (
                "<owner-personal-path>"
            ),
            config.second_owner_upn.replace("@", "_").replace(".", "_"): (
                "<second-owner-personal-path>"
            ),
        }
        replacements.update(
            {
                item.id: f"<folder-{path.name.lower().replace('_', '-')}-id>"
                for path, item in state.folders.items()
            }
        )
        replacements.update(
            {
                item.id: f"<file-{path.name.lower().replace('_', '-')}-id>"
                for path, item in state.files.items()
            }
        )
        return cls(replacements)

    def sanitize_payload(
        self, payload: GraphPayload, *, default_id_kind: str
    ) -> GraphPayload:
        sanitized = self._sanitize(payload.root, default_id_kind, None)
        return GraphPayload.model_validate(sanitized)

    def _sanitize(self, value: Any, default_id_kind: str, key: str | None) -> Any:
        if isinstance(value, dict):
            self._register_ids(value, default_id_kind, key)
            return {
                child_key: self._sanitize(
                    child_value,
                    self._id_kind(child_key, key, default_id_kind),
                    child_key,
                )
                for child_key, child_value in value.items()
                if child_key not in REQUEST_ID_KEYS
            }
        if isinstance(value, list):
            return [self._sanitize(child, default_id_kind, key) for child in value]
        if not isinstance(value, str):
            return value
        if key == "@microsoft.graph.downloadUrl":
            return "<download-url>"
        if key == "webUrl" and default_id_kind == "permission":
            return "<sharing-link-url>"
        if key == "displayName" and default_id_kind in {"group", "user"}:
            return self._display_name_placeholder(default_id_kind, value)
        if key and key.lower().endswith("hash"):
            hash_kind = HASH_KEY_PATTERN.sub("-", key).lower()
            return f"<{hash_kind}>"
        if key in {"createdDateTime", "lastModifiedDateTime", "sharedDateTime"}:
            return "<timestamp>"
        if key == "id" or key in {
            "driveId",
            "siteId",
            "listId",
            "listItemId",
            "listItemUniqueId",
            "tenantId",
            "webId",
        }:
            return self._placeholder(default_id_kind, value)
        return self._sanitize_string(value)

    def _register_ids(
        self,
        value: dict[str, Any],
        default_id_kind: str,
        parent_key: str | None,
    ) -> None:
        for key, child_value in value.items():
            if (key == "id" or key.endswith("Id")) and isinstance(child_value, str):
                self._placeholder(
                    self._id_kind(key, parent_key, default_id_kind), child_value
                )

    def _id_kind(self, key: str, parent_key: str | None, default_id_kind: str) -> str:
        if key == "driveId":
            return "drive"
        if key in {"siteId", "tenantId", "webId"}:
            return key.removesuffix("Id").lower()
        if key in {"listId", "listItemId", "listItemUniqueId"}:
            return key.removesuffix("Id").lower()
        if parent_key in {"user", "sharedBy", "owner"}:
            return "user"
        if parent_key == "group":
            return "group"
        if parent_key == "parentReference":
            return "item"
        return default_id_kind

    def _placeholder(self, kind: str, raw_value: str) -> str:
        replacement = self._replacements.get(raw_value)
        if replacement is not None:
            return replacement
        map_key = (kind, raw_value)
        if map_key not in self._generated:
            count = sum(existing_kind == kind for existing_kind, _ in self._generated)
            self._generated[map_key] = f"<{kind}-id-{count + 1}>"
            self._replacements[raw_value] = self._generated[map_key]
        return self._generated[map_key]

    def _display_name_placeholder(self, kind: str, raw_value: str) -> str:
        map_key = (f"{kind}-display-name", raw_value)
        if map_key not in self._generated:
            count = sum(
                existing_kind == map_key[0] for existing_kind, _ in self._generated
            )
            self._generated[map_key] = f"<{kind}-display-name-{count + 1}>"
            self._replacements[raw_value] = self._generated[map_key]
        return self._generated[map_key]

    def _sanitize_string(self, value: str) -> str:
        replacement = self._replacements.get(value)
        if replacement is not None:
            return replacement
        value = EMAIL_PATTERN.sub(self._replace_email, value)
        value = TIMESTAMP_PATTERN.sub("<timestamp>", value)
        if value.startswith(("https://", "http://")):
            return self._sanitize_url(value)
        return self._replace_embedded_known_values(value)

    def _replace_email(self, match: re.Match[str]) -> str:
        return self._placeholder("email", match.group(0).lower())

    def _sanitize_url(self, value: str) -> str:
        parts = urlsplit(value)
        host = (
            "<graph-host>"
            if parts.hostname and "microsoft.com" in parts.hostname
            else "<tenant-host>"
        )
        path = self._replace_embedded_known_values(parts.path)
        fragment = self._replace_embedded_known_values(parts.fragment)
        query = [
            (
                key,
                raw_value
                if key in SAFE_QUERY_KEYS
                else (
                    "<delta-token>"
                    if key.lower() in CURSOR_QUERY_KEYS
                    else "<query-value>"
                ),
            )
            for key, raw_value in parse_qsl(parts.query, keep_blank_values=True)
        ]
        return urlunsplit(
            (
                parts.scheme,
                host,
                path,
                urlencode(query, safe="$,<>"),
                fragment,
            )
        )

    def _replace_embedded_known_values(self, value: str) -> str:
        parts = PLACEHOLDER_PATTERN.split(value)
        for index in range(0, len(parts), 2):
            parts[index] = self._replace_unredacted_segment(parts[index])
        return "".join(parts)

    def _replace_unredacted_segment(self, value: str) -> str:
        for raw, replacement in sorted(
            self._replacements.items(), key=lambda pair: len(pair[0]), reverse=True
        ):
            variants = {
                raw,
                quote(raw, safe=""),
                quote(raw, safe="").replace("!", "%21"),
            }
            for variant in variants:
                if not variant:
                    continue
                if variant.isdigit() and len(variant) < 8:
                    value = re.sub(
                        rf"(?<![A-Za-z0-9]){re.escape(variant)}(?![A-Za-z0-9])",
                        replacement,
                        value,
                    )
                    continue
                value = value.replace(variant, replacement)
        return value


class OneDriveTenantSpikeRecorder:
    """Capture sanitized Graph behavior and leave the tenant at baseline."""

    def __init__(
        self,
        config: FixtureConfig,
        provisioner: OneDriveFixtureProvisioner,
        output_path: Path,
    ) -> None:
        self.config = config
        self.provisioner = provisioner
        self.graph = provisioner.graph
        self.output_path = output_path

    def record(self) -> SpikeObservation:
        observation: SpikeObservation | None = None
        try:
            state = self.provisioner.setup()
            observation = self._capture(state)
        finally:
            self.provisioner.setup()

        self._write(observation)
        return observation

    def _capture(self, state: FixtureState) -> SpikeObservation:
        sanitizer = StableSanitizer.from_state(state, self.config)
        fixture_item_ids = {
            state.root_item.id,
            state.second_drive_duplicate.id,
            *(item.id for item in state.folders.values()),
            *(item.id for item in state.files.values()),
        }
        recorded_item_ids = {
            state.root_item.id,
            state.folders[FolderPath.INHERITED].id,
            state.folders[FolderPath.RESTRICTED].id,
            state.folders[FolderPath.MOVE_DESTINATION].id,
            state.files[FilePath.DIRECT].id,
            state.files[FilePath.INHERITED].id,
            state.files[FilePath.RESTRICTED].id,
            state.files[FilePath.VISIBLE_GROUP].id,
            state.files[FilePath.ANONYMOUS_LINK].id,
            state.files[FilePath.MOVE].id,
            state.files[FilePath.REMOVE_SHARE].id,
            state.files[FilePath.RESTORE_INHERITANCE].id,
            state.files[FilePath.UPDATE].id,
            state.files[FilePath.DELETE].id,
        }
        full_recording = self._record_delta_pages(
            state.drive.id, fixture_item_ids, recorded_item_ids
        )
        permission_shapes = self._record_baseline_permissions(state)
        group_shapes = self._record_group_shapes(state)

        incremental_start = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.provisioner.mutate()
        permission_shapes.update(self._record_mutated_permissions(state))
        incremental_recording = self._record_delta_pages(
            state.drive.id,
            fixture_item_ids,
            recorded_item_ids,
            incremental_start,
        )

        sanitized_full = [
            sanitizer.sanitize_payload(page, default_id_kind="item")
            for page in full_recording.pages
        ]
        sanitized_incremental = [
            sanitizer.sanitize_payload(page, default_id_kind="item")
            for page in incremental_recording.pages
        ]
        sanitized_permissions = {
            name: sanitizer.sanitize_payload(payload, default_id_kind="permission")
            for name, payload in permission_shapes.items()
        }
        sanitized_groups = {
            name: sanitizer.sanitize_payload(payload, default_id_kind="user")
            for name, payload in group_shapes.items()
        }
        observations = self._summarize_delta_behavior(
            full_recording,
            incremental_recording,
        )
        return SpikeObservation(
            delta_request_headers=build_onedrive_delta_request_headers(),
            full_delta_pages=sanitized_full,
            incremental_delta_pages=sanitized_incremental,
            permission_shapes=sanitized_permissions,
            group_transitive_member_shapes=sanitized_groups,
            full_fixture_item_count=full_recording.fixture_item_count,
            incremental_fixture_item_count=incremental_recording.fixture_item_count,
            observations=observations,
        )

    def _record_delta_pages(
        self,
        drive_id: str,
        fixture_item_ids: set[str],
        recorded_item_ids: set[str],
        start: datetime | None = None,
    ) -> DeltaRecording:
        page_url = f"{self.graph.base_url}/drives/{drive_id}/root/delta"
        params: dict[str, str] | None = {
            "$top": str(SPIKE_PAGE_SIZE),
            "$select": DRIVE_DELTA_SELECT_FIELDS,
        }
        if start is not None:
            params["token"] = start.isoformat(timespec="seconds")

        pages: list[GraphPayload] = []
        fixture_item_count = 0
        shared_changed_count = 0
        tombstone_count = 0
        while page_url:
            result = fetch_drive_delta_checkpoint_page(
                self.graph,
                page_url=page_url,
                drive_id=drive_id,
                request_headers=build_onedrive_delta_request_headers(),
                query_params=params,
                page_size=SPIKE_PAGE_SIZE,
                select_fields=DRIVE_DELTA_SELECT_FIELDS,
                allow_full_resync=False,
            )
            fixture_item_count += sum(
                item.id in fixture_item_ids for item in result.page.items
            )
            shared_changed_count += sum(
                item.id in fixture_item_ids and item.shared_changed is True
                for item in result.page.items
            )
            tombstone_count += sum(
                item.id in fixture_item_ids and item.is_tombstone
                for item in result.page.items
            )
            filtered = result.page.model_copy(
                update={
                    "items": [
                        item
                        for item in result.page.items
                        if item.id in recorded_item_ids
                    ]
                }
            )
            pages.append(
                GraphPayload.model_validate(
                    filtered.model_dump(mode="json", by_alias=True, exclude_none=True)
                )
            )
            page_url = result.next_checkpoint_url
            params = None
        return DeltaRecording(
            pages=pages,
            fixture_item_count=fixture_item_count,
            shared_changed_count=shared_changed_count,
            tombstone_count=tombstone_count,
        )

    def _record_baseline_permissions(
        self, state: FixtureState
    ) -> dict[str, GraphPayload]:
        cases = {
            "direct": state.files[FilePath.DIRECT],
            "inherited": state.files[FilePath.INHERITED],
            "restricted": state.files[FilePath.RESTRICTED],
            "visible_group": state.files[FilePath.VISIBLE_GROUP],
            "hidden_group": state.files[FilePath.HIDDEN_GROUP],
            "anonymous_link": state.files[FilePath.ANONYMOUS_LINK],
            "organization_link": state.files[FilePath.ORGANIZATION_LINK],
        }
        return {
            name: self._get_payload(
                f"drives/{state.drive.id}/items/{item.id}/permissions"
            )
            for name, item in cases.items()
        }

    def _record_mutated_permissions(
        self, state: FixtureState
    ) -> dict[str, GraphPayload]:
        cases = {
            "move_destination_after": state.files[FilePath.MOVE],
            "remove_share_after": state.files[FilePath.REMOVE_SHARE],
            "restore_inheritance_after": state.files[FilePath.RESTORE_INHERITANCE],
        }
        return {
            name: self._get_payload(
                f"drives/{state.drive.id}/items/{item.id}/permissions"
            )
            for name, item in cases.items()
        }

    def _record_group_shapes(self, state: FixtureState) -> dict[str, GraphPayload]:
        params = {"$select": "id,displayName,userPrincipalName,mail"}
        return {
            "visible": self._get_payload(
                f"groups/{state.visible_group.id}/transitiveMembers", params
            ),
            "hidden": self._get_payload(
                f"groups/{state.hidden_group.id}/transitiveMembers", params
            ),
        }

    def _get_payload(
        self, path: str, params: dict[str, str] | None = None
    ) -> GraphPayload:
        return GraphPayload.model_validate(
            self.graph.get_json(self.graph._url(path), params)
        )

    def _summarize_delta_behavior(
        self,
        full_recording: DeltaRecording,
        incremental_recording: DeltaRecording,
    ) -> list[str]:
        return [
            (
                "Full delta returned "
                f"{full_recording.fixture_item_count} fixture items across "
                f"{len(full_recording.pages)} pages."
            ),
            (
                "Timestamp delta returned "
                f"{incremental_recording.fixture_item_count} fixture items across "
                f"{len(incremental_recording.pages)} pages."
            ),
            (
                "Timestamp delta marked "
                f"{incremental_recording.shared_changed_count} items with "
                "@microsoft.graph.sharedChanged."
            ),
            (
                "Timestamp delta returned "
                f"{incremental_recording.tombstone_count} tombstones."
            ),
        ]

    def _write(self, observation: SpikeObservation) -> None:
        serialized = observation.model_dump_json(indent=2, by_alias=True)
        self._assert_sanitized(serialized)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(f"{serialized}\n", encoding="utf-8")

    def _assert_sanitized(self, serialized: str) -> None:
        scan = scan_sanitized_fixture(serialized)
        if not scan.is_clean:
            failed = ", ".join(
                name.value for name, count in scan.counts.items() if count
            )
            raise RuntimeError(f"Sanitized fixture failed checks: {failed}")
        forbidden = {
            self.config.owner_upn,
            self.config.second_owner_upn,
            self.config.primary_upn,
            self.config.alternate_upn,
        }
        if any(value and value in serialized for value in forbidden):
            raise RuntimeError("Sanitized fixture still contains a configured identity")


def require_local_certificate_environment() -> None:
    missing = [
        key.value
        for key in CERTIFICATE_SECRET_KEYS
        if key.name not in os.environ and key.value not in os.environ
    ]
    if missing:
        raise RuntimeError(
            "Recorder requires all credential keys from the local environment. "
            f"Missing: {', '.join(missing)}"
        )
    names = ", ".join(key.value for key in CERTIFICATE_SECRET_KEYS)
    logger.info("Resolved 4 credential keys locally: %s", names)


def parse_args() -> RecorderArgs:
    parser = argparse.ArgumentParser(
        description="Record sanitized responses for the OneDrive test corpus"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Record live responses. Without this flag, only print the plan.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_SPIKE_FIXTURE_PATH,
        help="Destination for the sanitized tenant-spike fixture.",
    )
    return RecorderArgs.model_validate(vars(parser.parse_args()))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    print(f"Fixture root: {FIXTURE_ROOT_NAME}")
    print("Record: full delta, mutation delta, permissions, and groups.")
    print("The recorder restores baseline before it exits.")
    if not args.apply:
        return

    require_local_certificate_environment()
    config = load_fixture_config()
    provisioner = build_provisioner(config)
    observation = OneDriveTenantSpikeRecorder(config, provisioner, args.output).record()
    for evidence in observation.observations:
        print(evidence)
    scan = scan_sanitized_fixture(observation.model_dump_json(by_alias=True))
    for pattern, count in scan.counts.items():
        print(f"Sanitization scan {pattern.value}: {count}")
    print(f"Wrote sanitized fixture to {args.output}.")


if __name__ == "__main__":
    main()
