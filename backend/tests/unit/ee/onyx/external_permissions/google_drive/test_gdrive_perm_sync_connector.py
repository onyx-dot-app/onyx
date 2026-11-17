"""Permission sync lists the same files that indexing indexes, so its
connector takes the indexing image policy."""

from types import SimpleNamespace
from typing import Any, cast

import pytest

from ee.onyx.external_permissions.google_drive import doc_sync
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
            )
        ),
    )

    connector = doc_sync.build_perm_sync_connector(cc_pair)

    assert connector.allow_images is images_enabled
    assert loaded == [{}]
