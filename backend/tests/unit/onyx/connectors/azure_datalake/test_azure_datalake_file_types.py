import pytest

from onyx.connectors.azure_datalake.connector import has_indexable_name


@pytest.mark.parametrize(
    ("path", "allow_images", "expected"),
    [
        ("dir/report.PDF", False, True),
        ("dir/notes.md", False, True),
        ("dir/archive.zip", True, False),
        ("dir/Makefile", True, False),
        ("dir/photo.png", False, False),
        ("dir/photo.png", True, True),
        ("dir/anim.gif", True, False),
    ],
)
def test_has_indexable_name(path: str, allow_images: bool, expected: bool) -> None:
    assert has_indexable_name(path, allow_images=allow_images) is expected
