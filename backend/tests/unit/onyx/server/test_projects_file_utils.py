from io import BytesIO
from unittest.mock import MagicMock

import pytest
from fastapi import UploadFile

from onyx.server.features.projects import projects_file_utils as utils


class _Tokenizer:
    def encode(self, text: str) -> list[int]:
        return [1] * len(text)


class _NonSeekableFile(BytesIO):
    def tell(self) -> int:
        raise OSError("tell not supported")

    def seek(self, *_args: object, **_kwargs: object) -> int:
        raise OSError("seek not supported")


def _make_upload(filename: str, size: int, content: bytes | None = None) -> UploadFile:
    payload = content if content is not None else (b"x" * size)
    return UploadFile(filename=filename, file=BytesIO(payload), size=size)


def _make_upload_no_size(filename: str, content: bytes) -> UploadFile:
    return UploadFile(filename=filename, file=BytesIO(content), size=None)


def _patch_common_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(utils, "fetch_default_llm_model", lambda _db: None)
    monkeypatch.setattr(utils, "get_tokenizer", lambda **_kwargs: _Tokenizer())
    monkeypatch.setattr(utils, "is_file_password_protected", lambda **_kwargs: False)


def test_get_upload_size_bytes_falls_back_to_stream_size() -> None:
    upload = UploadFile(filename="example.txt", file=BytesIO(b"abcdef"), size=None)
    upload.file.seek(2)

    size = utils.get_upload_size_bytes(upload)

    assert size == 6
    assert upload.file.tell() == 2


def test_get_upload_size_bytes_logs_warning_when_stream_size_unavailable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    upload = UploadFile(filename="non_seekable.txt", file=_NonSeekableFile(), size=None)

    caplog.set_level("WARNING")
    size = utils.get_upload_size_bytes(upload)

    assert size is None
    assert "Could not determine upload size via stream seek" in caplog.text
    assert "non_seekable.txt" in caplog.text


def test_is_upload_too_large_logs_warning_when_size_unknown(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    upload = _make_upload("size_unknown.txt", size=1)
    monkeypatch.setattr(utils, "get_upload_size_bytes", lambda _upload: None)

    caplog.set_level("WARNING")
    is_too_large = utils.is_upload_too_large(upload, max_bytes=100)

    assert is_too_large is False
    assert "Could not determine upload size; skipping size-limit check" in caplog.text
    assert "size_unknown.txt" in caplog.text


def test_categorize_uploaded_files_accepts_size_under_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common_dependencies(monkeypatch)
    monkeypatch.setattr(utils, "USER_FILE_MAX_UPLOAD_SIZE_BYTES", 100)
    monkeypatch.setattr(utils, "USER_FILE_MAX_UPLOAD_SIZE_MB", 1)
    monkeypatch.setattr(utils, "estimate_image_tokens_for_upload", lambda _upload: 10)

    upload = _make_upload("small.png", size=99)
    result = utils.categorize_uploaded_files([upload], MagicMock())

    assert len(result.acceptable) == 1
    assert len(result.rejected) == 0


def test_categorize_uploaded_files_uses_seek_fallback_when_upload_size_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common_dependencies(monkeypatch)
    monkeypatch.setattr(utils, "USER_FILE_MAX_UPLOAD_SIZE_BYTES", 100)
    monkeypatch.setattr(utils, "USER_FILE_MAX_UPLOAD_SIZE_MB", 1)
    monkeypatch.setattr(utils, "estimate_image_tokens_for_upload", lambda _upload: 10)

    upload = _make_upload_no_size("small.png", content=b"x" * 99)
    result = utils.categorize_uploaded_files([upload], MagicMock())

    assert len(result.acceptable) == 1
    assert len(result.rejected) == 0


def test_categorize_uploaded_files_accepts_size_at_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common_dependencies(monkeypatch)
    monkeypatch.setattr(utils, "USER_FILE_MAX_UPLOAD_SIZE_BYTES", 100)
    monkeypatch.setattr(utils, "USER_FILE_MAX_UPLOAD_SIZE_MB", 1)
    monkeypatch.setattr(utils, "estimate_image_tokens_for_upload", lambda _upload: 10)

    upload = _make_upload("edge.png", size=100)
    result = utils.categorize_uploaded_files([upload], MagicMock())

    assert len(result.acceptable) == 1
    assert len(result.rejected) == 0


def test_categorize_uploaded_files_rejects_size_over_limit_with_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common_dependencies(monkeypatch)
    monkeypatch.setattr(utils, "USER_FILE_MAX_UPLOAD_SIZE_BYTES", 100)
    monkeypatch.setattr(utils, "USER_FILE_MAX_UPLOAD_SIZE_MB", 1)
    monkeypatch.setattr(utils, "estimate_image_tokens_for_upload", lambda _upload: 10)

    upload = _make_upload("large.png", size=101)
    result = utils.categorize_uploaded_files([upload], MagicMock())

    assert len(result.acceptable) == 0
    assert len(result.rejected) == 1
    assert result.rejected[0].reason == "Exceeds 1 MB file size limit"


def test_categorize_uploaded_files_mixed_batch_keeps_valid_and_rejects_oversized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common_dependencies(monkeypatch)
    monkeypatch.setattr(utils, "USER_FILE_MAX_UPLOAD_SIZE_BYTES", 100)
    monkeypatch.setattr(utils, "USER_FILE_MAX_UPLOAD_SIZE_MB", 1)
    monkeypatch.setattr(utils, "estimate_image_tokens_for_upload", lambda _upload: 10)

    small = _make_upload("small.png", size=50)
    large = _make_upload("large.png", size=101)

    result = utils.categorize_uploaded_files([small, large], MagicMock())

    assert [file.filename for file in result.acceptable] == ["small.png"]
    assert len(result.rejected) == 1
    assert result.rejected[0].filename == "large.png"
    assert result.rejected[0].reason == "Exceeds 1 MB file size limit"


def test_categorize_uploaded_files_enforces_size_limit_even_when_threshold_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common_dependencies(monkeypatch)
    monkeypatch.setattr(utils, "SKIP_USERFILE_THRESHOLD", True)
    monkeypatch.setattr(utils, "USER_FILE_MAX_UPLOAD_SIZE_BYTES", 100)
    monkeypatch.setattr(utils, "USER_FILE_MAX_UPLOAD_SIZE_MB", 1)

    upload = _make_upload("oversized.pdf", size=101)
    result = utils.categorize_uploaded_files([upload], MagicMock())

    assert len(result.acceptable) == 0
    assert len(result.rejected) == 1
    assert result.rejected[0].reason == "Exceeds 1 MB file size limit"


def test_categorize_uploaded_files_checks_size_before_text_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common_dependencies(monkeypatch)
    monkeypatch.setattr(utils, "USER_FILE_MAX_UPLOAD_SIZE_BYTES", 100)
    monkeypatch.setattr(utils, "USER_FILE_MAX_UPLOAD_SIZE_MB", 1)

    extract_mock = MagicMock(return_value="this should not run")
    monkeypatch.setattr(utils, "extract_file_text", extract_mock)

    oversized_doc = _make_upload("oversized.pdf", size=101)
    result = utils.categorize_uploaded_files([oversized_doc], MagicMock())

    extract_mock.assert_not_called()
    assert len(result.acceptable) == 0
    assert len(result.rejected) == 1
    assert result.rejected[0].reason == "Exceeds 1 MB file size limit"
