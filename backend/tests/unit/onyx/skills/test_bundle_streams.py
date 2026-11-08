import io
import zipfile
from functools import partial

import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.skills import bundle
from onyx.utils.bundle import compute_bundle_metadata

MD = b"---\nname: hello\ndescription: A skill\n---\nInstructions\n"


class BoundedStream(io.BytesIO):
    def read(self, size: int | None = -1, /) -> bytes:
        assert size is not None and 0 < size <= 64 * 1024
        return super().read(size)


def test_streamed_bundle_has_stable_bytes_and_digest() -> None:
    files = {
        "SKILL.md": partial(BoundedStream, MD),
        "data": partial(BoundedStream, b"abc"),
    }
    result = bundle.build_custom_bundle(files)
    assert result == bundle.build_custom_bundle(dict(reversed(list(files.items()))))
    with zipfile.ZipFile(io.BytesIO(result)) as archive:
        assert archive.read("SKILL.md") == MD
        assert archive.read("data") == b"abc"
        assert all(i.date_time == (1980, 1, 1, 0, 0, 0) for i in archive.infolist())
    metadata = compute_bundle_metadata(result)
    assert metadata.file_count == 2
    assert metadata.unpacked_size_bytes == len(MD) + 3
    other = io.BytesIO()
    with zipfile.ZipFile(other, "w") as archive:
        archive.writestr("data", b"abc")
        archive.writestr("SKILL.md", MD)
    assert compute_bundle_metadata(other.getvalue()) == metadata


@pytest.mark.parametrize(
    "limit",
    [
        "DEFAULT_PER_FILE_MAX_BYTES",
        "DEFAULT_TOTAL_MAX_BYTES",
        "DEFAULT_MAX_FILE_COUNT",
        "DEFAULT_ZIP_MAX_BYTES",
    ],
)
def test_streamed_bundle_enforces_each_limit(
    limit: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = {"SKILL.md": partial(BoundedStream, MD)}
    size = len(bundle.build_custom_bundle(files))
    boundary = {
        "DEFAULT_PER_FILE_MAX_BYTES": len(MD),
        "DEFAULT_TOTAL_MAX_BYTES": len(MD),
        "DEFAULT_MAX_FILE_COUNT": 1,
        "DEFAULT_ZIP_MAX_BYTES": size,
    }[limit]
    monkeypatch.setattr(bundle, limit, boundary)
    bundle.build_custom_bundle(files)
    monkeypatch.setattr(bundle, limit, boundary - 1)
    with pytest.raises(OnyxError) as error:
        bundle.build_custom_bundle(files)
    assert error.value.status_code == 413


@pytest.mark.parametrize("path", ["../bad", "data.template", "data/file/../bad"])
def test_streamed_bundle_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(OnyxError):
        bundle.build_custom_bundle(
            {"SKILL.md": partial(io.BytesIO, MD), path: io.BytesIO}
        )


def test_streamed_bundle_uses_validated_file_names() -> None:
    result = bundle.build_custom_bundle(
        {"SKILL.md": partial(io.BytesIO, MD), "data/": partial(io.BytesIO, b"abc")}
    )
    with zipfile.ZipFile(io.BytesIO(result)) as archive:
        assert archive.namelist() == ["SKILL.md", "data"]
        assert archive.read("data") == b"abc"


def test_streamed_bundle_rejects_normalized_name_collisions() -> None:
    with pytest.raises(OnyxError):
        bundle.build_custom_bundle(
            {
                "SKILL.md": partial(io.BytesIO, MD),
                "data": partial(io.BytesIO, b"a"),
                "data/": partial(io.BytesIO, b"b"),
            }
        )
