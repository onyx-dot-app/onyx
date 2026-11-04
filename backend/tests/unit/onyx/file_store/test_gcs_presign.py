"""GCS V4 signed URLs. No emulator signs URLs, so the IAM signBlob call is
mocked; a live GCS check is still needed."""

import base64
import datetime
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from google.auth import compute_engine
from google.auth.credentials import Credentials
from google.auth.exceptions import TransportError
from google.cloud import storage
from google.oauth2.credentials import Credentials as UserCredentials

from onyx.configs.constants import FileOrigin
from onyx.file_store.file_store import PresignedUrlsNotSupportedError
from onyx.file_store.gcs_file_store import GCSBackedFileStore
from onyx.file_store.models import PendingPresignedUpload

SERVICE_ACCOUNT = "onyx@project.iam.gserviceaccount.com"
SIGNATURE = b"signed-by-iam"
PENDING = PendingPresignedUpload(
    file_id="file-1",
    display_name="snapshot.tar",
    file_origin=FileOrigin.OTHER,
    file_type="application/x-tar",
    bucket_name="onyx-bucket",
    object_key="onyx-files/public/file-1",
    size=24,
    sha256="0" * 64,
)


def _store_with(credentials: Credentials) -> GCSBackedFileStore:
    store = GCSBackedFileStore(bucket_name="onyx-bucket")
    client = storage.Client(project="project", credentials=credentials)
    store._get_gcs_client = MagicMock(return_value=client)
    store._signing_credentials = credentials
    return store


def _workload_identity_store() -> GCSBackedFileStore:
    credentials = compute_engine.Credentials(
        service_account_email=SERVICE_ACCOUNT, universe_domain="googleapis.com"
    )
    credentials.token = "access-token"
    # google-auth compares expiry as naive UTC.
    credentials.expiry = datetime.datetime.now(datetime.UTC).replace(
        tzinfo=None
    ) + datetime.timedelta(hours=1)
    return _store_with(credentials)


def test_workload_identity_signs_an_upload_through_iam() -> None:
    store = _workload_identity_store()

    with patch(
        "google.cloud.storage._signing._sign_message",
        return_value=base64.b64encode(SIGNATURE).decode(),
    ) as sign_blob:
        request = store._sign_upload(PENDING, 300)

    sign_blob.assert_called_once()
    assert sign_blob.call_args.args[1:3] == ("access-token", SERVICE_ACCOUNT)
    url = urlparse(request.url)
    query = parse_qs(url.query)
    assert url.netloc == "storage.googleapis.com"
    assert url.path == "/onyx-bucket/onyx-files/public/file-1"
    assert query["X-Goog-Algorithm"] == ["GOOG4-RSA-SHA256"]
    assert query["X-Goog-Credential"][0].startswith(f"{SERVICE_ACCOUNT}/")
    assert query["X-Goog-Expires"] == ["300"]
    assert query["X-Goog-SignedHeaders"] == [
        "content-type;host;x-goog-content-length-range;x-goog-if-generation-match"
    ]
    assert query["X-Goog-Signature"] == [SIGNATURE.hex()]
    assert request.method == "PUT"
    assert request.headers == {
        "Content-Type": "application/x-tar",
        "x-goog-if-generation-match": "0",
        "x-goog-content-length-range": "24,24",
    }


def test_a_denied_sign_blob_names_the_missing_role() -> None:
    store = _workload_identity_store()

    with (
        patch(
            "google.cloud.storage._signing._sign_message",
            side_effect=TransportError("Error calling the IAM signBytes API: 403"),
        ),
        pytest.raises(
            PresignedUrlsNotSupportedError,
            match="roles/iam.serviceAccountTokenCreator",
        ),
    ):
        store._sign_download("onyx-bucket", "onyx-files/public/file-1", 300)


def test_user_credentials_cannot_sign() -> None:
    store = _store_with(UserCredentials(token="user-token"))

    with pytest.raises(PresignedUrlsNotSupportedError, match="service account"):
        store._sign_download("onyx-bucket", "onyx-files/public/file-1", 300)


def test_a_transient_sign_blob_failure_is_raised_as_is() -> None:
    store = _workload_identity_store()

    with (
        patch(
            "google.cloud.storage._signing._sign_message",
            side_effect=TransportError("Error calling the IAM signBytes API: 503"),
        ),
        pytest.raises(TransportError),
    ):
        store._sign_download("onyx-bucket", "onyx-files/public/file-1", 300)
