"""The startup warning for an upgrade that left files in the bundled MinIO must
fire only for the s3 backend pointed at that MinIO, never for external storage."""

from onyx.configs.app_configs import _runs_on_legacy_minio


def test_only_the_bundled_minio_endpoint_on_the_s3_backend_is_flagged() -> None:
    assert _runs_on_legacy_minio("s3", "http://minio:9000") is True
    assert _runs_on_legacy_minio("s3", "http://minio:9000/") is True
    assert _runs_on_legacy_minio("s3", "http://object-store:8333") is False
    assert _runs_on_legacy_minio("s3", "https://s3.us-east-1.amazonaws.com") is False
    # Real AWS S3 has no endpoint URL.
    assert _runs_on_legacy_minio("s3", None) is False
    assert _runs_on_legacy_minio("postgres", "http://minio:9000") is False
