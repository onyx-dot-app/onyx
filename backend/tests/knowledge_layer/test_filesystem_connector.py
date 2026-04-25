import pytest
from knowledge_layer.connectors.filesystem import FilesystemConnector
from onyx.configs.constants import DocumentSource


def test_connector_source():
    conn = FilesystemConnector(watch_path="/tmp")
    conn.load_credentials({})
    assert conn.SOURCE == DocumentSource.WIKI_RAW_FS


def test_load_from_state_yields_documents(tmp_path):
    (tmp_path / "note.md").write_text("# Hello\nThis is a note.")
    (tmp_path / "guide.txt").write_text("A plain text guide.")

    conn = FilesystemConnector(watch_path=str(tmp_path))
    conn.load_credentials({})

    docs = []
    for batch in conn.load_from_state():
        docs.extend(batch)

    assert len(docs) == 2
    slugs = {d.semantic_identifier for d in docs}
    assert "note.md" in slugs
    assert "guide.txt" in slugs


def test_load_from_state_skips_unsupported_extensions(tmp_path):
    (tmp_path / "image.png").write_bytes(b"\x89PNG")
    (tmp_path / "doc.md").write_text("# A doc")

    conn = FilesystemConnector(watch_path=str(tmp_path))
    conn.load_credentials({})

    docs = []
    for batch in conn.load_from_state():
        docs.extend(batch)

    assert len(docs) == 1
    assert docs[0].semantic_identifier == "doc.md"


def test_document_has_doc_type_raw_doc(tmp_path):
    (tmp_path / "test.md").write_text("Content")
    conn = FilesystemConnector(watch_path=str(tmp_path))
    conn.load_credentials({})

    docs = list(next(conn.load_from_state()))
    assert docs[0].metadata.get("doc_type") == "raw_doc"
