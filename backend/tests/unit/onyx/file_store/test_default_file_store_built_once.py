"""The default file store is built once per process. Every image and
attachment a connector stores went through a fresh store, and so a fresh S3
client, before; the client is the expensive part."""

from unittest.mock import patch

from onyx.file_store import file_store as file_store_module
from onyx.file_store.file_store import get_default_file_store


def test_the_default_file_store_is_built_once() -> None:
    with (
        patch.object(file_store_module, "_DEFAULT_FILE_STORE", None),
        patch.object(file_store_module, "_build_default_file_store") as build,
    ):
        first = get_default_file_store()
        second = get_default_file_store()

    assert first is second
    assert build.call_count == 1
