import pytest

from onyx.connectors.egnyte.connector import is_indexable
from onyx.connectors.egnyte.models import EgnyteFile


def _file(name: str) -> EgnyteFile:
    return EgnyteFile(
        name=name,
        path=f"/Shared/{name}",
        group_id="group-1",
        entry_id="entry-1",
        last_modified="Tue, 10 Nov 2026 18:00:00 GMT",
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("report.docx", True),
        ("NOTES.TXT", True),
        ("data.csv", True),
        ("deck.pptx", True),
        # Images are not indexed.
        ("photo.png", False),
        ("photo.webp", False),
        ("archive.zip", False),
        ("Makefile", False),
    ],
)
def test_is_indexable_by_extension(name: str, expected: bool) -> None:
    assert is_indexable(_file(name)) is expected
