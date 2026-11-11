"""The startup warning for an upgrade that left files in the bundled MinIO must
fire only for the s3 backend pointed at that MinIO, never for external storage."""

import importlib
import logging
import os
from unittest.mock import patch

import pytest

import onyx.configs.app_configs as app_configs
from onyx.configs.app_configs import _runs_on_legacy_minio

LEGACY_MINIO_ENV = {
    "FILE_STORE_BACKEND": "s3",
    "S3_ENDPOINT_URL": "http://minio:9000",
    "S3_LEGACY_ENDPOINT_URL": "",
}
OBJECT_STORE_ENV = {
    "FILE_STORE_BACKEND": "s3",
    "S3_ENDPOINT_URL": "http://object-store:8333",
    "S3_LEGACY_ENDPOINT_URL": "http://minio:9000",
}
EXTERNAL_S3_ENV = {
    "FILE_STORE_BACKEND": "s3",
    "S3_ENDPOINT_URL": "",
    "S3_LEGACY_ENDPOINT_URL": "",
}


def _startup_warnings(
    env: dict[str, str], caplog: pytest.LogCaptureFixture
) -> list[str]:
    """Import app_configs under `env` and return its legacy MinIO warnings."""
    caplog.clear()
    with (
        patch.dict(os.environ, env),
        caplog.at_level(logging.WARNING, logger="onyx.utils.logger"),
    ):
        importlib.reload(app_configs)
    warnings = [
        record.getMessage()
        for record in caplog.records
        if "legacy MinIO" in record.getMessage()
    ]
    # Back to the process env so later tests see the real constants. Collected
    # above because this reload warns too when the process env points at MinIO.
    importlib.reload(app_configs)
    return warnings


def test_only_the_bundled_minio_endpoint_on_the_s3_backend_is_flagged() -> None:
    assert _runs_on_legacy_minio("s3", "http://minio:9000") is True
    assert _runs_on_legacy_minio("s3", "http://minio:9000/") is True
    assert _runs_on_legacy_minio("s3", "http://object-store:8333") is False
    assert _runs_on_legacy_minio("s3", "https://s3.us-east-1.amazonaws.com") is False
    # Real AWS S3 has no endpoint URL.
    assert _runs_on_legacy_minio("s3", None) is False
    assert _runs_on_legacy_minio("postgres", "http://minio:9000") is False


def test_startup_warns_only_while_files_are_still_in_the_bundled_minio(
    caplog: pytest.LogCaptureFixture,
) -> None:
    [message] = _startup_warnings(LEGACY_MINIO_ENV, caplog)
    assert "S3_ENDPOINT_URL=http://object-store:8333" in message
    assert "S3_LEGACY_ENDPOINT_URL=http://minio:9000" in message
    assert _startup_warnings(OBJECT_STORE_ENV, caplog) == []
    assert _startup_warnings(EXTERNAL_S3_ENV, caplog) == []
