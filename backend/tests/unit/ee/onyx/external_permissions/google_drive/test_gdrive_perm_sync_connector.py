"""Permission sync lists the same files that indexing indexes, so its
connector takes the indexing image policy. Doc and group sync spend from the
credential's shared API budget, and report Google's rate limits to it."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.external_permissions.google_drive import doc_sync, group_sync
from onyx.configs.constants import DocumentSource
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.db.models import ConnectorCredentialPair


@pytest.mark.parametrize("images_enabled", [True, False])
def test_perm_sync_connector_takes_the_image_policy(
    monkeypatch: pytest.MonkeyPatch, images_enabled: bool
) -> None:
    monkeypatch.setattr(
        doc_sync, "get_image_extraction_and_analysis_enabled", lambda: images_enabled
    )
    monkeypatch.setattr(doc_sync, "credential_json", lambda _cc_pair: {})
    loaded: list[dict[str, Any]] = []
    monkeypatch.setattr(
        GoogleDriveConnector,
        "load_credentials",
        lambda _self, credentials: loaded.append(credentials),
    )
    cc_pair = cast(
        ConnectorCredentialPair,
        SimpleNamespace(
            connector=SimpleNamespace(
                source=DocumentSource.GOOGLE_DRIVE,
                connector_specific_config={"include_shared_drives": True},
            ),
            credential_id=7,
        ),
    )

    connector = doc_sync.build_perm_sync_connector(cc_pair)

    assert connector.allow_images is images_enabled
    assert loaded == [{}]


def _limiter_calls(
    monkeypatch: pytest.MonkeyPatch, module: Any
) -> tuple[MagicMock, list[tuple[DocumentSource, int, Callable[[], bool] | None]]]:
    limiter = MagicMock()
    built: list[tuple[DocumentSource, int, Callable[[], bool] | None]] = []

    def build(
        source: DocumentSource,
        credential_id: int,
        should_stop: Callable[[], bool] | None = None,
    ) -> MagicMock:
        built.append((source, credential_id, should_stop))
        return limiter

    monkeypatch.setattr(module, "build_source_api_limiter", build)
    monkeypatch.setattr(module, "credential_json", lambda _cc_pair: {})
    return limiter, built


def test_doc_sync_attaches_the_shared_limiter_before_it_loads_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter, built = _limiter_calls(monkeypatch, doc_sync)
    monkeypatch.setattr(
        doc_sync, "get_image_extraction_and_analysis_enabled", lambda: False
    )
    order: list[str] = []
    monkeypatch.setattr(
        GoogleDriveConnector,
        "set_source_api_limiter",
        lambda _self, given: order.append("limiter") if given is limiter else None,
    )
    monkeypatch.setattr(
        GoogleDriveConnector,
        "load_credentials",
        lambda _self, _credentials: order.append("credentials"),
    )
    cc_pair = cast(
        ConnectorCredentialPair,
        SimpleNamespace(
            connector=SimpleNamespace(
                source=DocumentSource.GOOGLE_DRIVE,
                connector_specific_config={"include_shared_drives": True},
            ),
            credential_id=7,
        ),
    )

    should_stop = MagicMock(return_value=False)
    doc_sync.build_perm_sync_connector(cc_pair, should_stop)

    assert built == [(DocumentSource.GOOGLE_DRIVE, 7, should_stop)]
    assert order == ["limiter", "credentials"]


def test_group_sync_attaches_the_shared_limiter_before_it_loads_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter, built = _limiter_calls(monkeypatch, group_sync)
    connector = MagicMock()
    cc_pair = MagicMock()
    cc_pair.credential_id = 7
    with (
        patch.object(group_sync, "GoogleDriveConnector", return_value=connector),
        patch.object(group_sync, "build_connector_kwargs", return_value={}),
        patch.object(group_sync, "_get_drive_members", return_value={}),
        patch.object(group_sync, "_get_all_google_groups", return_value=[]),
        patch.object(group_sync, "_get_all_folders", return_value=iter([])),
        patch.object(group_sync, "_get_all_domain_users", return_value=[]),
    ):
        list(group_sync.gdrive_group_sync("tenant", cc_pair))

    assert [(source, credential_id) for source, credential_id, _ in built] == [
        (DocumentSource.GOOGLE_DRIVE, 7)
    ]
    # A wait for the budget ends at the sync's deadline.
    should_stop = built[0][2]
    assert should_stop is not None
    assert should_stop() is False
    with (
        patch.object(group_sync.time, "monotonic", return_value=float("inf")),
        pytest.raises(TimeoutError),
    ):
        should_stop()
    calls = [call[0] for call in connector.method_calls]
    assert calls.index("set_source_api_limiter") < calls.index("load_credentials")
    connector.set_source_api_limiter.assert_called_once_with(limiter)
