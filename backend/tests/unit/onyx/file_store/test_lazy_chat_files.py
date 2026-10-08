"""Lazy file content contracts without database or object storage."""

from onyx.file_store.models import ChatFileType, ChatLoadedFile
from onyx.tools.models import ChatFile


class TestLazyShimContract:
    """Lazy file wrappers defer byte reads and reuse their first result."""

    def test_no_load_on_construction(self) -> None:
        calls = {"n": 0}

        def loader() -> bytes:
            calls["n"] += 1
            return b"data"

        ChatLoadedFile.lazy_loaded(
            file_id="x",
            file_type=ChatFileType.PLAIN_TEXT,
            filename="x.txt",
            content_text="cached text",
            token_count=3,
            loader=loader,
        )
        assert calls["n"] == 0

    def test_first_access_materializes_once_only(self) -> None:
        calls = {"n": 0}

        def loader() -> bytes:
            calls["n"] += 1
            return b"data"

        f = ChatLoadedFile.lazy_loaded(
            file_id="x",
            file_type=ChatFileType.PLAIN_TEXT,
            filename="x.txt",
            content_text=None,
            token_count=0,
            loader=loader,
        )
        assert f.content == b"data"
        assert f.content == b"data"
        assert calls["n"] == 1

    def test_non_content_attrs_do_not_trigger(self) -> None:
        calls = {"n": 0}
        f = ChatLoadedFile.lazy_loaded(
            file_id="x",
            file_type=ChatFileType.IMAGE,
            filename="x.png",
            content_text=None,
            token_count=0,
            loader=lambda: (calls.__setitem__("n", calls["n"] + 1), b"img")[1],
        )
        _ = f.file_id
        _ = f.filename
        _ = f.file_type
        _ = f.content_text
        _ = f.token_count
        assert calls["n"] == 0

    def test_to_file_descriptor_does_not_materialize(self) -> None:
        calls = {"n": 0}
        f = ChatLoadedFile.lazy_loaded(
            file_id="abc",
            file_type=ChatFileType.PLAIN_TEXT,
            filename="x.txt",
            content_text=None,
            token_count=0,
            loader=lambda: (calls.__setitem__("n", calls["n"] + 1), b"data")[1],
        )
        fd = f.to_file_descriptor()
        assert fd["id"] == "abc"
        assert calls["n"] == 0

    def test_to_base64_materializes_image(self) -> None:
        calls = {"n": 0}
        f = ChatLoadedFile.lazy_loaded(
            file_id="img",
            file_type=ChatFileType.IMAGE,
            filename="x.png",
            content_text=None,
            token_count=0,
            loader=lambda: (calls.__setitem__("n", calls["n"] + 1), b"PNG-bytes")[1],
        )
        _ = f.to_base64()
        assert calls["n"] == 1

    def test_concurrent_first_access_calls_loader_exactly_once(self) -> None:
        """Two threads racing on the first ``.content`` read must not both
        invoke the loader (would be a double S3 GET). The lazy shim takes a
        per-instance ``threading.Lock`` to make check-and-set atomic."""
        import threading

        call_count = {"n": 0}
        gate = threading.Event()

        def slow_loader() -> bytes:
            # Gate guarantees both threads observe _lazy_content_materialized
            # is False before the first writer completes — without the lock,
            # both would enter the load path.
            gate.wait()
            call_count["n"] += 1
            return b"once"

        f = ChatLoadedFile.lazy_loaded(
            file_id="x",
            file_type=ChatFileType.PLAIN_TEXT,
            filename="x.txt",
            content_text=None,
            token_count=0,
            loader=slow_loader,
        )

        results: list[bytes] = []

        def reader() -> None:
            results.append(f.content)

        t1 = threading.Thread(target=reader)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        # Let both threads enter __getattribute__ and contend on the lock.
        gate.set()
        t1.join()
        t2.join()

        assert results == [b"once", b"once"]
        assert call_count["n"] == 1

    def test_chat_file_lazy_content(self) -> None:
        calls = {"n": 0}
        cf = ChatFile.lazy_from_filename(
            filename="x.csv",
            loader=lambda: (calls.__setitem__("n", calls["n"] + 1), b"csv-bytes")[1],
        )
        assert calls["n"] == 0
        _ = cf.filename
        assert calls["n"] == 0
        assert cf.content == b"csv-bytes"
        assert cf.content == b"csv-bytes"
        assert calls["n"] == 1
