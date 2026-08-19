from onyx.configs.app_configs import _uses_default_object_storage_credentials


def test_default_credentials_detected_against_minio() -> None:
    # MinIO endpoint set + the well-known default => flagged.
    assert (
        _uses_default_object_storage_credentials(
            "http://minio:9000", "minioadmin", "minioadmin"
        )
        is True
    )


def test_default_credentials_detected_when_either_value_is_default() -> None:
    # A default in either the access key or the secret is enough to flag.
    assert (
        _uses_default_object_storage_credentials(
            "http://minio:9000", "minioadmin", "a-strong-secret"
        )
        is True
    )
    assert (
        _uses_default_object_storage_credentials(
            "http://minio:9000", "a-strong-key", "minioadmin"
        )
        is True
    )


def test_strong_credentials_not_flagged() -> None:
    assert (
        _uses_default_object_storage_credentials(
            "http://minio:9000", "a-strong-key", "a-strong-secret"
        )
        is False
    )


def test_no_endpoint_never_flagged() -> None:
    # Real AWS S3 has no endpoint URL; the check must never fire without one,
    # even if the (unrelated) credential values happened to match the default.
    assert (
        _uses_default_object_storage_credentials(None, "minioadmin", "minioadmin")
        is False
    )
    assert (
        _uses_default_object_storage_credentials("", "minioadmin", "minioadmin")
        is False
    )
