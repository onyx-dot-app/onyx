from io import BytesIO
from unittest.mock import MagicMock

import pytest
from fastapi import UploadFile

from onyx.natural_language_processing import utils as nlp_utils
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.natural_language_processing.utils import count_tokens
from onyx.server.features.projects import projects_file_utils as utils
from onyx.server.settings.models import Settings


class _Tokenizer(BaseTokenizer):
    def encode(self, text: str) -> list[int]:
        return [1] * len(text)

    def tokenize(self, text: str) -> list[str]:
        return list(text)

    def decode(self, _tokens: list[int]) -> str:
        return ""


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


def _make_settings(upload_size_mb: int = 1, token_threshold_k: int = 100) -> Settings:
    return Settings(
        user_file_max_upload_size_mb=upload_size_mb,
        file_token_count_threshold_k=token_threshold_k,
    )


def _patch_common_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    upload_size_mb: int = 1,
    token_threshold_k: int = 100,
) -> None:
    monkeypatch.setattr(utils, "fetch_default_llm_model", lambda _db: None)
    monkeypatch.setattr(utils, "get_tokenizer", lambda **_kwargs: _Tokenizer())
    monkeypatch.setattr(utils, "is_file_password_protected", lambda **_kwargs: False)
    monkeypatch.setattr(
        utils,
        "load_settings",
        lambda: _make_settings(upload_size_mb, token_threshold_k),
    )


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
    # upload_size_mb=1 → max_bytes = 1*1024*1024; file size 99 is well under
    _patch_common_dependencies(monkeypatch, upload_size_mb=1)
    monkeypatch.setattr(utils, "estimate_image_tokens_for_upload", lambda _upload: 10)

    upload = _make_upload("small.png", size=99)
    result = utils.categorize_uploaded_files([upload], MagicMock())

    assert len(result.acceptable) == 1
    assert len(result.rejected) == 0


def test_categorize_uploaded_files_uses_seek_fallback_when_upload_size_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common_dependencies(monkeypatch, upload_size_mb=1)
    monkeypatch.setattr(utils, "estimate_image_tokens_for_upload", lambda _upload: 10)

    upload = _make_upload_no_size("small.png", content=b"x" * 99)
    result = utils.categorize_uploaded_files([upload], MagicMock())

    assert len(result.acceptable) == 1
    assert len(result.rejected) == 0


def test_categorize_uploaded_files_accepts_size_at_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common_dependencies(monkeypatch, upload_size_mb=1)
    monkeypatch.setattr(utils, "estimate_image_tokens_for_upload", lambda _upload: 10)

    # 1 MB = 1048576 bytes; file at exactly that boundary should be accepted
    upload = _make_upload("edge.png", size=1048576)
    result = utils.categorize_uploaded_files([upload], MagicMock())

    assert len(result.acceptable) == 1
    assert len(result.rejected) == 0


def test_categorize_uploaded_files_rejects_size_over_limit_with_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common_dependencies(monkeypatch, upload_size_mb=1)
    monkeypatch.setattr(utils, "estimate_image_tokens_for_upload", lambda _upload: 10)

    upload = _make_upload("large.png", size=1048577)  # 1 byte over 1 MB
    result = utils.categorize_uploaded_files([upload], MagicMock())

    assert len(result.acceptable) == 0
    assert len(result.rejected) == 1
    assert result.rejected[0].reason == "Exceeds 1 MB file size limit"


def test_categorize_uploaded_files_mixed_batch_keeps_valid_and_rejects_oversized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common_dependencies(monkeypatch, upload_size_mb=1)
    monkeypatch.setattr(utils, "estimate_image_tokens_for_upload", lambda _upload: 10)

    small = _make_upload("small.png", size=50)
    large = _make_upload("large.png", size=1048577)

    result = utils.categorize_uploaded_files([small, large], MagicMock())

    assert [file.filename for file in result.acceptable] == ["small.png"]
    assert len(result.rejected) == 1
    assert result.rejected[0].filename == "large.png"
    assert result.rejected[0].reason == "Exceeds 1 MB file size limit"


def test_categorize_uploaded_files_enforces_size_limit_always(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common_dependencies(monkeypatch, upload_size_mb=1)

    upload = _make_upload("oversized.pdf", size=1048577)
    result = utils.categorize_uploaded_files([upload], MagicMock())

    assert len(result.acceptable) == 0
    assert len(result.rejected) == 1
    assert result.rejected[0].reason == "Exceeds 1 MB file size limit"


def test_categorize_uploaded_files_checks_size_before_text_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common_dependencies(monkeypatch, upload_size_mb=1)

    extract_mock = MagicMock(return_value="this should not run")
    monkeypatch.setattr(utils, "extract_file_text", extract_mock)

    oversized_doc = _make_upload("oversized.pdf", size=1048577)
    result = utils.categorize_uploaded_files([oversized_doc], MagicMock())

    extract_mock.assert_not_called()
    assert len(result.acceptable) == 0
    assert len(result.rejected) == 1
    assert result.rejected[0].reason == "Exceeds 1 MB file size limit"


def test_categorize_enforces_size_limit_when_upload_size_mb_is_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A positive upload_size_mb is always enforced."""
    _patch_common_dependencies(monkeypatch, upload_size_mb=1)
    monkeypatch.setattr(utils, "estimate_image_tokens_for_upload", lambda _upload: 10)

    upload = _make_upload("huge.png", size=1048577, content=b"x")
    result = utils.categorize_uploaded_files([upload], MagicMock())

    assert len(result.acceptable) == 0
    assert len(result.rejected) == 1


def test_categorize_enforces_token_limit_when_threshold_k_is_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A positive token_threshold_k is always enforced."""
    _patch_common_dependencies(monkeypatch, upload_size_mb=1000, token_threshold_k=5)
    monkeypatch.setattr(utils, "estimate_image_tokens_for_upload", lambda _upload: 6000)

    upload = _make_upload("big_image.png", size=100)
    result = utils.categorize_uploaded_files([upload], MagicMock())

    assert len(result.acceptable) == 0
    assert len(result.rejected) == 1


def test_categorize_no_token_limit_when_threshold_k_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """token_threshold_k=0 means no token limit; high-token files are accepted."""
    _patch_common_dependencies(monkeypatch, upload_size_mb=1000, token_threshold_k=0)
    monkeypatch.setattr(
        utils, "estimate_image_tokens_for_upload", lambda _upload: 999_999
    )

    upload = _make_upload("huge_image.png", size=100)
    result = utils.categorize_uploaded_files([upload], MagicMock())

    assert len(result.rejected) == 0
    assert len(result.acceptable) == 1


def test_categorize_both_limits_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both positive limits are enforced; file exceeding token limit is rejected."""
    _patch_common_dependencies(monkeypatch, upload_size_mb=10, token_threshold_k=5)
    monkeypatch.setattr(utils, "estimate_image_tokens_for_upload", lambda _upload: 6000)

    upload = _make_upload("over_tokens.png", size=100)
    result = utils.categorize_uploaded_files([upload], MagicMock())

    assert len(result.acceptable) == 0
    assert len(result.rejected) == 1
    assert result.rejected[0].reason == "Exceeds 5K token limit"


def test_categorize_rejection_reason_contains_dynamic_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rejection reasons reflect the admin-configured limits, not hardcoded values."""
    _patch_common_dependencies(monkeypatch, upload_size_mb=42, token_threshold_k=7)
    monkeypatch.setattr(utils, "estimate_image_tokens_for_upload", lambda _upload: 8000)

    # File within size limit but over token limit
    upload = _make_upload("tokens.png", size=100)
    result = utils.categorize_uploaded_files([upload], MagicMock())

    assert result.rejected[0].reason == "Exceeds 7K token limit"

    # File over size limit
    _patch_common_dependencies(monkeypatch, upload_size_mb=42, token_threshold_k=7)
    oversized = _make_upload("big.png", size=42 * 1024 * 1024 + 1)
    result2 = utils.categorize_uploaded_files([oversized], MagicMock())

    assert result2.rejected[0].reason == "Exceeds 42 MB file size limit"


# --- count_tokens tests ---


def test_count_tokens_small_text() -> None:
    """Small text should be encoded in a single call and return correct count."""
    tokenizer = _Tokenizer()
    text = "hello world"
    assert count_tokens(text, tokenizer) == len(tokenizer.encode(text))


def test_count_tokens_chunked_matches_single_call() -> None:
    """Chunked encoding should produce the same result as single-call for small text."""
    tokenizer = _Tokenizer()
    text = "a" * 1000
    assert count_tokens(text, tokenizer) == len(tokenizer.encode(text))


def test_count_tokens_large_text_is_chunked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Text exceeding _ENCODE_CHUNK_SIZE should be split into multiple encode calls."""
    monkeypatch.setattr(nlp_utils, "_ENCODE_CHUNK_SIZE", 100)
    tokenizer = _Tokenizer()
    text = "a" * 250
    # _Tokenizer returns 1 token per char, so total should be 250
    assert count_tokens(text, tokenizer) == 250


def test_count_tokens_with_token_limit_exits_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When token_limit is set and exceeded, count_tokens should stop early."""
    monkeypatch.setattr(nlp_utils, "_ENCODE_CHUNK_SIZE", 100)

    encode_call_count = 0
    original_tokenizer = _Tokenizer()

    class _CountingTokenizer(BaseTokenizer):
        def encode(self, text: str) -> list[int]:
            nonlocal encode_call_count
            encode_call_count += 1
            return original_tokenizer.encode(text)

        def tokenize(self, text: str) -> list[str]:
            return list(text)

        def decode(self, _tokens: list[int]) -> str:
            return ""

    tokenizer = _CountingTokenizer()
    # 500 chars → 5 chunks of 100; limit=150 → should stop after 2 chunks
    text = "a" * 500
    result = count_tokens(text, tokenizer, token_limit=150)

    assert result == 200  # 2 chunks × 100 tokens each
    assert encode_call_count == 2, "Should have stopped after 2 chunks"


def test_count_tokens_with_token_limit_not_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When token_limit is set but not exceeded, all chunks are encoded."""
    monkeypatch.setattr(nlp_utils, "_ENCODE_CHUNK_SIZE", 100)
    tokenizer = _Tokenizer()
    text = "a" * 250
    result = count_tokens(text, tokenizer, token_limit=1000)
    assert result == 250


def test_count_tokens_no_limit_encodes_all_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without token_limit, all chunks are encoded regardless of count."""
    monkeypatch.setattr(nlp_utils, "_ENCODE_CHUNK_SIZE", 100)
    tokenizer = _Tokenizer()
    text = "a" * 500
    result = count_tokens(text, tokenizer)
    assert result == 500


# --- early exit via token_limit in categorize tests ---


def test_categorize_early_exits_tokenization_for_large_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Large text files should be rejected via early-exit tokenization
    without encoding all chunks."""
    _patch_common_dependencies(monkeypatch, upload_size_mb=1000, token_threshold_k=1)
    # token_threshold = 1000; _ENCODE_CHUNK_SIZE = 100 → text of 500 chars = 5 chunks
    # Should stop after 2nd chunk (200 tokens > 1000? No... need 1 token per char)
    # With _Tokenizer: 1 token per char. threshold=1000, chunk=100 → need 11 chunks
    # Let's use a bigger text
    monkeypatch.setattr(nlp_utils, "_ENCODE_CHUNK_SIZE", 100)
    large_text = "x" * 5000  # 5000 tokens, threshold 1000
    monkeypatch.setattr(utils, "extract_file_text", lambda **_kwargs: large_text)

    encode_call_count = 0
    original_tokenizer = _Tokenizer()

    class _CountingTokenizer(BaseTokenizer):
        def encode(self, text: str) -> list[int]:
            nonlocal encode_call_count
            encode_call_count += 1
            return original_tokenizer.encode(text)

        def tokenize(self, text: str) -> list[str]:
            return list(text)

        def decode(self, _tokens: list[int]) -> str:
            return ""

    monkeypatch.setattr(utils, "get_tokenizer", lambda **_kwargs: _CountingTokenizer())

    upload = _make_upload("big.txt", size=5000, content=large_text.encode())
    result = utils.categorize_uploaded_files([upload], MagicMock())

    assert len(result.rejected) == 1
    assert "token limit" in result.rejected[0].reason
    # 5000 chars / 100 chunk_size = 50 chunks total; should stop well before all 50
    assert (
        encode_call_count < 50
    ), f"Expected early exit but encoded {encode_call_count} chunks out of 50"


def test_categorize_text_under_token_limit_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Text files under the token threshold should be accepted with exact count."""
    _patch_common_dependencies(monkeypatch, upload_size_mb=1000, token_threshold_k=1)
    small_text = "x" * 500  # 500 tokens < 1000 threshold
    monkeypatch.setattr(utils, "extract_file_text", lambda **_kwargs: small_text)

    upload = _make_upload("ok.txt", size=500, content=small_text.encode())
    result = utils.categorize_uploaded_files([upload], MagicMock())

    assert len(result.acceptable) == 1
    assert result.acceptable_file_to_token_count["ok.txt"] == 500
