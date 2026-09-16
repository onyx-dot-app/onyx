"""Checks secure, relationship-preserving OneDrive spike recording."""

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import scripts.onedrive.record_test_corpus as record_test_corpus
from scripts.onedrive.provision_test_corpus import (
    FixtureConfig,
    OneDriveFixtureProvisioner,
)
from scripts.onedrive.record_test_corpus import (
    CERTIFICATE_SECRET_KEYS,
    DEFAULT_SPIKE_FIXTURE_PATH,
    EMAIL_PATTERN,
    TIMESTAMP_PATTERN,
    GraphPayload,
    OneDriveTenantSpikeRecorder,
    SensitivePattern,
    SpikeObservation,
    StableSanitizer,
    require_local_certificate_environment,
    scan_sanitized_fixture,
)

from onyx.connectors.microsoft_utils.drive_delta import (
    DriveDeltaFetchResult,
    DriveDeltaPage,
    build_onedrive_delta_request_headers,
)


def test_sanitizer_preserves_relationships_without_tenant_values() -> None:
    sanitizer = StableSanitizer(
        {
            "b!drive-secret": "<owner-drive-id>",
            "user-secret": "<primary-user-id>",
            "person@example.com": "<primary-user-email>",
        }
    )
    payload = GraphPayload.model_validate(
        {
            "value": [
                {
                    "id": "item-secret",
                    "webUrl": (
                        "https://tenant-my.sharepoint.com/personal/person/"
                        "item-secret?request=secret"
                    ),
                    "createdDateTime": "2026-09-15T20:01:02.123Z",
                    "parentReference": {
                        "driveId": "b!drive-secret",
                        "id": "item-secret",
                        "path": (
                            "/drives/b!drive-secret/root:/encoded/b%21drive-secret"
                        ),
                    },
                    "file": {
                        "hashes": {
                            "quickXorHash": "raw-quick-xor-hash",
                            "sha1Hash": "raw-sha1-hash",
                        }
                    },
                    "lastModifiedBy": {
                        "user": {
                            "id": "user-secret",
                            "displayName": "Private Name",
                            "email": "person@example.com",
                        }
                    },
                    "@microsoft.graph.downloadUrl": (
                        "https://download.example.com/file?tempauth=credential"
                    ),
                }
            ],
            "@odata.nextLink": (
                "https://graph.microsoft.com/v1.0/drives/b!drive-secret/root/delta"
                "?$skiptoken=opaque-secret&$top=50"
            ),
            "request-id": "request-secret",
        }
    )

    sanitized = sanitizer.sanitize_payload(payload, default_id_kind="item").root
    serialized = GraphPayload(sanitized).model_dump_json()

    item = sanitized["value"][0]
    assert item["id"] == item["parentReference"]["id"]
    assert item["parentReference"]["driveId"] == "<owner-drive-id>"
    assert item["parentReference"]["path"] == (
        "/drives/<owner-drive-id>/root:/encoded/<owner-drive-id>"
    )
    assert item["file"]["hashes"] == {
        "quickXorHash": "<quick-xor-hash>",
        "sha1Hash": "<sha1-hash>",
    }
    assert item["lastModifiedBy"]["user"]["id"] == "<primary-user-id>"
    assert item["lastModifiedBy"]["user"]["displayName"] == "<user-display-name-1>"
    assert item["lastModifiedBy"]["user"]["email"] == "<primary-user-email>"
    assert item["createdDateTime"] == "<timestamp>"
    assert item["@microsoft.graph.downloadUrl"] == "<download-url>"
    assert "<graph-host>" in sanitized["@odata.nextLink"]
    assert "<delta-token>" in sanitized["@odata.nextLink"]
    assert "request-id" not in sanitized
    for secret in (
        "tenant-my.sharepoint.com",
        "person@example.com",
        "item-secret",
        "b!drive-secret",
        "b%21drive-secret",
        "raw-quick-xor-hash",
        "raw-sha1-hash",
        "user-secret",
        "opaque-secret",
        "credential",
        "Private Name",
        "2026-09-15",
    ):
        assert secret not in serialized


def test_sanitizer_replaces_sharing_capability_url() -> None:
    sanitizer = StableSanitizer({})
    payload = GraphPayload.model_validate(
        {
            "value": [
                {
                    "id": "3",
                    "grantedToV2": {
                        "user": {"id": "user", "displayName": "Private Name"}
                    },
                    "link": {
                        "scope": "anonymous",
                        "webUrl": "https://tenant.example/opaque-capability",
                    },
                }
            ]
        }
    )

    sanitized = sanitizer.sanitize_payload(payload, default_id_kind="permission").root

    assert sanitized["value"][0]["link"]["webUrl"] == "<sharing-link-url>"
    assert (
        sanitized["value"][0]["grantedToV2"]["user"]["displayName"]
        == "<user-display-name-1>"
    )


def test_sanitization_scan_detects_each_sensitive_pattern() -> None:
    serialized = """
    {
      "id": "11111111-1111-1111-1111-111111111111",
      "driveId": "b!raw-drive",
      "email": "person@example.com",
      "siteUrl": "https://tenant.sharepoint.com/site",
      "request-id": "request",
      "quickXorHash": "raw-hash",
      "createdDateTime": "2026-09-15T20:01:02Z"
    }
    """

    scan = scan_sanitized_fixture(serialized)

    assert all(scan.counts[pattern] == 1 for pattern in SensitivePattern)


def test_delta_recorder_filters_items_and_uses_pr2_headers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    graph = MagicMock()
    graph.base_url = "https://graph.microsoft.com/v1.0"
    provisioner = MagicMock(spec=OneDriveFixtureProvisioner)
    provisioner.graph = graph
    recorder = OneDriveTenantSpikeRecorder(
        FixtureConfig(), provisioner, tmp_path / "fixture.json"
    )
    calls: list[dict[str, object]] = []

    def fake_fetch(*_args: object, **kwargs: object) -> DriveDeltaFetchResult:
        calls.append(kwargs)
        return DriveDeltaFetchResult(
            page=DriveDeltaPage.model_validate(
                {
                    "value": [
                        {"id": "fixture", "name": "keep.docx"},
                        {"id": "unrelated", "name": "drop.docx"},
                    ],
                    "@odata.deltaLink": "https://graph.example/delta?token=done",
                }
            )
        )

    monkeypatch.setattr(
        record_test_corpus, "fetch_drive_delta_checkpoint_page", fake_fetch
    )

    recording = recorder._record_delta_pages(
        "drive", {"fixture", "unrelated"}, {"fixture"}
    )

    assert [item["id"] for item in recording.pages[0].root["value"]] == ["fixture"]
    assert recording.fixture_item_count == 2
    assert calls[0]["request_headers"] == build_onedrive_delta_request_headers()


def test_recorder_restores_baseline_when_capture_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    provisioner = MagicMock(spec=OneDriveFixtureProvisioner)
    provisioner.graph = MagicMock()
    provisioner.setup.return_value = MagicMock()
    recorder = OneDriveTenantSpikeRecorder(
        FixtureConfig(), provisioner, tmp_path / "fixture.json"
    )
    monkeypatch.setattr(
        recorder,
        "_capture",
        MagicMock(side_effect=RuntimeError("capture failed")),
    )

    with pytest.raises(RuntimeError, match="capture failed"):
        recorder.record()

    assert provisioner.setup.call_count == 2
    assert not recorder.output_path.exists()


def test_recorder_writes_only_after_restore(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    provisioner = MagicMock(spec=OneDriveFixtureProvisioner)
    provisioner.graph = MagicMock()
    provisioner.setup.return_value = MagicMock()
    recorder = OneDriveTenantSpikeRecorder(
        FixtureConfig(), provisioner, tmp_path / "fixture.json"
    )
    observation = SpikeObservation(
        delta_request_headers=build_onedrive_delta_request_headers(),
        full_delta_pages=[],
        incremental_delta_pages=[],
        permission_shapes={},
        group_transitive_member_shapes={},
        full_fixture_item_count=0,
        incremental_fixture_item_count=0,
        observations=[],
    )
    monkeypatch.setattr(recorder, "_capture", MagicMock(return_value=observation))

    recorder.record()

    assert provisioner.setup.call_count == 2
    assert recorder.output_path.exists()


def test_local_credential_check_requires_all_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in CERTIFICATE_SECRET_KEYS:
        monkeypatch.delenv(key.name, raising=False)
        monkeypatch.delenv(key.value, raising=False)
    monkeypatch.setenv(CERTIFICATE_SECRET_KEYS[0].name, "present")

    with pytest.raises(RuntimeError, match="Missing:"):
        require_local_certificate_environment()


def test_local_credential_check_accepts_all_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in CERTIFICATE_SECRET_KEYS:
        monkeypatch.setenv(key.name, "present")

    require_local_certificate_environment()


def test_recorded_fixture_contains_only_stable_placeholders() -> None:
    serialized = DEFAULT_SPIKE_FIXTURE_PATH.read_text(encoding="utf-8")
    observation = SpikeObservation.model_validate_json(serialized)
    scan = scan_sanitized_fixture(serialized)

    assert scan.is_clean
    assert all(count == 0 for count in scan.counts.values())
    assert scan.counts.keys() == set(SensitivePattern)
    assert not EMAIL_PATTERN.search(serialized)
    assert not TIMESTAMP_PATTERN.search(serialized)
    assert not re.search(r"<[^>]*<", serialized)
    assert observation.full_delta_pages
    assert observation.incremental_delta_pages
    assert observation.group_transitive_member_shapes["visible"].root["value"]
    assert observation.group_transitive_member_shapes["hidden"].root["value"]
    assert any(
        permission.get("link", {}).get("webUrl") == "<sharing-link-url>"
        for permission in observation.permission_shapes["anonymous_link"].root["value"]
    )


def test_recorded_mutated_permissions_preserve_access_distinctions() -> None:
    observation = SpikeObservation.model_validate_json(
        DEFAULT_SPIKE_FIXTURE_PATH.read_text(encoding="utf-8")
    )
    assert {
        "move_destination_after",
        "remove_share_after",
        "restore_inheritance_after",
    } <= observation.permission_shapes.keys()

    remove_share = observation.permission_shapes["remove_share_after"]
    restore_inheritance = observation.permission_shapes["restore_inheritance_after"]
    remove_serialized = remove_share.model_dump_json()
    restore_serialized = restore_inheritance.model_dump_json()

    assert "<primary-user-email>" not in remove_serialized
    assert "<primary-user-email>" in restore_serialized
    assert any(
        "inheritedFrom" in permission
        for permission in restore_inheritance.root["value"]
    )
    assert scan_sanitized_fixture(remove_serialized).is_clean
    assert scan_sanitized_fixture(restore_serialized).is_clean
