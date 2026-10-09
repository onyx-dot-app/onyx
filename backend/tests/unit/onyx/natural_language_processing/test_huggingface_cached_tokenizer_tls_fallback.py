from pathlib import Path

import httpx
import huggingface_hub
import huggingface_hub.constants
import pytest
import requests
from huggingface_hub import file_download
from huggingface_hub.file_download import repo_folder_name
from packaging.version import Version
from tokenizers import Tokenizer
from tokenizers.models import WordLevel

from onyx.configs.model_configs import DEFAULT_DOCUMENT_ENCODER_MODEL

TOKENIZER_FILENAME = "tokenizer.json"
TEST_COMMIT_HASH = "0" * 40
TEST_TOKEN = "airgap"


def _write_cached_tokenizer(cache_dir: Path) -> None:
    repo_dir = cache_dir / repo_folder_name(
        repo_id=DEFAULT_DOCUMENT_ENCODER_MODEL,
        repo_type="model",
    )
    refs_dir = repo_dir / "refs"
    snapshot_dir = repo_dir / "snapshots" / TEST_COMMIT_HASH
    refs_dir.mkdir(parents=True)
    snapshot_dir.mkdir(parents=True)
    (refs_dir / huggingface_hub.constants.DEFAULT_REVISION).write_text(TEST_COMMIT_HASH)

    tokenizer = Tokenizer(WordLevel({"[UNK]": 0, TEST_TOKEN: 1}, unk_token="[UNK]"))
    tokenizer.save(str(snapshot_dir / TOKENIZER_FILENAME))


def _tls_error() -> Exception:
    if Version(huggingface_hub.__version__).major >= 1:
        return httpx.ConnectError("certificate verification failed")
    return requests.exceptions.SSLError("certificate verification failed")


def test_cached_tokenizer_loads_when_huggingface_tls_verification_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "hub"
    _write_cached_tokenizer(cache_dir)
    monkeypatch.setattr(huggingface_hub.constants, "HF_HUB_CACHE", str(cache_dir))

    def fail_metadata_request(*_args: object, **_kwargs: object) -> None:
        raise _tls_error()

    monkeypatch.setattr(
        file_download,
        "get_hf_file_metadata",
        fail_metadata_request,
    )

    tokenizer = Tokenizer.from_pretrained(DEFAULT_DOCUMENT_ENCODER_MODEL)

    assert tokenizer.encode(TEST_TOKEN).ids == [1]
