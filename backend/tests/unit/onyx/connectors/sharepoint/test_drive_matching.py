from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from onyx.connectors.sharepoint.connector import SHARED_DOCUMENTS_MAP
from onyx.connectors.sharepoint.connector import SharepointConnector
from onyx.connectors.sharepoint.connector import SharepointConnectorCheckpoint
from onyx.connectors.sharepoint.connector import SiteDescriptor


class _FakeQuery:
    def __init__(self, payload: Sequence[Any]) -> None:
        self._payload = payload

    def execute_query(self) -> Sequence[Any]:
        return self._payload


class _FakeFolder:
    def __init__(self, items: Sequence[Any]) -> None:
        self._items = items
        self.name = "root"

    def get_by_path(self, _path: str) -> _FakeFolder:
        return self

    def get_files(
        self, *, recursive: bool, page_size: int
    ) -> _FakeQuery:  # noqa: ARG002
        return _FakeQuery(self._items)


class _FakeDrive:
    def __init__(self, name: str, items: Sequence[Any]) -> None:
        self.name = name
        self.root = _FakeFolder(items)


class _FakeDrivesCollection:
    def __init__(self, drives: Sequence[_FakeDrive]) -> None:
        self._drives = drives

    def get(self) -> _FakeQuery:
        return _FakeQuery(list(self._drives))


class _FakeSite:
    def __init__(self, drives: Sequence[_FakeDrive]) -> None:
        self.drives = _FakeDrivesCollection(drives)


class _FakeSites:
    def __init__(self, drives: Sequence[_FakeDrive]) -> None:
        self._drives = drives

    def get_by_url(self, _url: str) -> _FakeSite:
        return _FakeSite(self._drives)


class _FakeGraphClient:
    def __init__(self, drives: Sequence[_FakeDrive]) -> None:
        self.sites = _FakeSites(drives)


def _build_connector(drives: Sequence[_FakeDrive]) -> SharepointConnector:
    connector = SharepointConnector()
    connector._graph_client = _FakeGraphClient(drives)  # type: ignore[assignment]
    return connector


@pytest.mark.parametrize(
    ("requested_drive_name", "graph_drive_name"),
    [
        ("Shared Documents", "Documents"),
        ("Freigegebene Dokumente", "Dokumente"),
        ("Documentos compartidos", "Documentos"),
    ],
)
def test_fetch_driveitems_matches_international_drive_names(
    requested_drive_name: str, graph_drive_name: str
) -> None:
    item = SimpleNamespace(parent_reference=SimpleNamespace(path=None))
    connector = _build_connector([_FakeDrive(graph_drive_name, [item])])
    site_descriptor = SiteDescriptor(
        url="https://example.sharepoint.com/sites/sample",
        drive_name=requested_drive_name,
        folder_path=None,
    )

    results = connector._fetch_driveitems(site_descriptor=site_descriptor)

    assert len(results) == 1
    drive_item, returned_drive_name = results[0]
    assert drive_item is item
    assert returned_drive_name == requested_drive_name


@pytest.mark.parametrize(
    ("requested_drive_name", "graph_drive_name"),
    [
        ("Shared Documents", "Documents"),
        ("Freigegebene Dokumente", "Dokumente"),
        ("Documentos compartidos", "Documentos"),
    ],
)
def test_get_drive_items_for_drive_name_matches_map(
    requested_drive_name: str, graph_drive_name: str
) -> None:
    item = SimpleNamespace()
    connector = _build_connector([_FakeDrive(graph_drive_name, [item])])
    site_descriptor = SiteDescriptor(
        url="https://example.sharepoint.com/sites/sample",
        drive_name=requested_drive_name,
        folder_path=None,
    )

    results = connector._get_drive_items_for_drive_name(
        site_descriptor=site_descriptor,
        drive_name=requested_drive_name,
    )

    assert len(results) == 1
    assert results[0] is item


def test_load_from_checkpoint_maps_drive_name(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = SharepointConnector()
    connector._graph_client = object()  # type: ignore[assignment]
    connector.include_site_pages = False

    captured_drive_names: list[str] = []

    def fake_get_drive_items(
        self: SharepointConnector,
        site_descriptor: SiteDescriptor,
        drive_name: str,
        start: datetime | None,
        end: datetime | None,
    ) -> list[SimpleNamespace]:
        assert drive_name == "Documents"
        return [
            SimpleNamespace(
                name="sample.pdf",
                web_url="https://example.sharepoint.com/sites/sample/sample.pdf",
            )
        ]

    def fake_convert(
        driveitem: SimpleNamespace,
        drive_name: str,
        ctx: Any,
        graph_client: Any,
        include_permissions: bool,
    ) -> SimpleNamespace:
        captured_drive_names.append(drive_name)
        return SimpleNamespace(sections=["content"])

    monkeypatch.setattr(
        SharepointConnector,
        "_get_drive_items_for_drive_name",
        fake_get_drive_items,
    )
    monkeypatch.setattr(
        "onyx.connectors.sharepoint.connector._convert_driveitem_to_document_with_permissions",
        fake_convert,
    )

    checkpoint = SharepointConnectorCheckpoint(has_more=True)
    checkpoint.cached_site_descriptors = deque()
    checkpoint.current_site_descriptor = SiteDescriptor(
        url="https://example.sharepoint.com/sites/sample",
        drive_name=SHARED_DOCUMENTS_MAP["Documents"],
        folder_path=None,
    )
    checkpoint.cached_drive_names = deque(["Documents"])
    checkpoint.current_drive_name = None
    checkpoint.process_site_pages = False

    generator = connector._load_from_checkpoint(
        start=0,
        end=0,
        checkpoint=checkpoint,
        include_permissions=False,
    )

    documents: list[Any] = []
    try:
        while True:
            documents.append(next(generator))
    except StopIteration:
        pass

    assert len(documents) == 1
    assert captured_drive_names == [SHARED_DOCUMENTS_MAP["Documents"]]
