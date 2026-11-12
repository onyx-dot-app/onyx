"""The Egnyte connector: plain-text files index, document ids stay the same
across file versions, and the walk covers subfolders and skips files deleted
before their download."""

from unittest.mock import MagicMock

from onyx.connectors.egnyte.connector import EgnyteConnector
from onyx.connectors.egnyte.models import EgnyteFile, EgnyteFolder, EgnyteFolderPage
from onyx.connectors.egnyte.source_operations import EgnyteApiError
from onyx.connectors.models import Document


def _file(path: str, entry_id: str = "entry-1") -> EgnyteFile:
    return EgnyteFile(
        name=path.rsplit("/", 1)[-1],
        path=path,
        group_id=f"group{path}",
        entry_id=entry_id,
        last_modified="Tue, 10 Nov 2026 18:00:00 GMT",
    )


def _connector(ops: MagicMock, folder_path: str | None = None) -> EgnyteConnector:
    connector = EgnyteConnector(folder_path=folder_path)
    connector.load_credentials({"domain": "acme", "access_token": "test-token"})
    connector._ops = ops
    return connector


def _indexed(connector: EgnyteConnector) -> list[Document]:
    return [
        doc
        for batch in connector.load_from_state()
        for doc in batch
        if isinstance(doc, Document)
    ]


def test_plain_text_file_indexes_with_its_group_id() -> None:
    ops = MagicMock()
    ops.iterate_folder_pages.return_value = iter(
        [
            EgnyteFolderPage(
                folders=[], files=[_file("/Shared/notes.txt", entry_id="v2")]
            )
        ]
    )
    ops.download_file.return_value = b"Version two of the notes.\n"

    docs = _indexed(_connector(ops))

    assert [(doc.id, doc.sections[0].text) for doc in docs] == [
        ("egnyte-group/Shared/notes.txt", "Version two of the notes.")
    ]


def test_walk_reads_subfolders_and_skips_files_deleted_before_download() -> None:
    pages = {
        "/Shared": [
            EgnyteFolderPage(
                folders=[EgnyteFolder(name="Sub", path="/Shared/Sub", folder_id="f1")],
                files=[_file("/Shared/gone.txt")],
            )
        ],
        "/Shared/Sub": [
            EgnyteFolderPage(folders=[], files=[_file("/Shared/Sub/kept.txt")])
        ],
    }
    ops = MagicMock()
    ops.iterate_folder_pages.side_effect = lambda folder_path: iter(pages[folder_path])

    def download(file_path: str) -> bytes:
        if file_path == "/Shared/gone.txt":
            raise EgnyteApiError("deleted", status_code=404)
        return b"kept"

    ops.download_file.side_effect = download

    docs = _indexed(_connector(ops, folder_path="Shared/"))

    assert [doc.semantic_identifier for doc in docs] == ["kept.txt"]
