import uuid
from collections.abc import Generator
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError
from sqlalchemy.orm import Session

from onyx.configs.app_configs import S3_ENDPOINT_URL, S3_LEGACY_ENDPOINT_URL
from onyx.file_store import file_store
from onyx.file_store.file_store import (
    LEGACY_OUT_OF_SYNC_PREFIX,
    LEGACY_RETIRED_MARKER_KEY,
    S3BackedFileStore,
)
from tests.external_dependency_unit.file_store.legacy_store_helpers import (
    BUCKET,
    delete_objects,
    make_store,
)


@pytest.fixture
def stores(
    db_session: Session,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
) -> Generator[tuple[S3BackedFileStore, S3BackedFileStore], None, None]:
    """(what an earlier release wrote with, what this release reads with)."""
    assert S3_ENDPOINT_URL and S3_LEGACY_ENDPOINT_URL
    prefix = f"legacy-store-tests-{uuid.uuid4()}"
    old_release = make_store(S3_LEGACY_ENDPOINT_URL, None, prefix)
    new_release = make_store(S3_ENDPOINT_URL, S3_LEGACY_ENDPOINT_URL, prefix)
    old_release.initialize()
    new_release.initialize()
    yield old_release, new_release
    for client in (old_release._get_s3_client(), new_release._get_s3_client()):
        delete_objects(client, BUCKET, f"{prefix}/")
    delete_objects(
        new_release._get_s3_client(), BUCKET, LEGACY_OUT_OF_SYNC_PREFIX + prefix
    )


@pytest.fixture
def fresh_bucket_store(
    db_session: Session,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
) -> Generator[S3BackedFileStore, None, None]:
    """A store on a bucket that exists in neither store yet, like a fresh install."""
    assert S3_ENDPOINT_URL and S3_LEGACY_ENDPOINT_URL
    bucket = f"legacy-fresh-{uuid.uuid4()}"
    store = make_store(S3_ENDPOINT_URL, S3_LEGACY_ENDPOINT_URL, "fresh", bucket)
    store.initialize()
    legacy = store._get_legacy_s3_client()
    assert legacy is not None
    yield store
    for client in (store._get_s3_client(), legacy):
        try:
            delete_objects(client, bucket)
        except ClientError:
            continue
        client.delete_bucket(Bucket=bucket)


@pytest.fixture
def retired_marker(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> Generator[None, None, None]:
    """Checks the retire marker on every call and removes it afterwards."""
    target = stores[1]._get_s3_client()
    with patch.object(file_store, "LEGACY_RETIRED_RECHECK_SECONDS", 0):
        yield
    target.delete_object(Bucket=BUCKET, Key=LEGACY_RETIRED_MARKER_KEY)
    file_store._legacy_retired.clear()
