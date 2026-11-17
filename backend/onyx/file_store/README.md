# Onyx File Store

The Onyx file store provides a unified interface for storing files and large binary objects. It supports four storage backends: S3-compatible storage (AWS S3, MinIO, Digital Ocean Spaces, etc.), Google Cloud Storage (GCS), Azure Blob Storage, and PostgreSQL Large Objects.

## Architecture

The file store uses a single database table (`file_record`) to store file metadata while the actual file content is stored in the configured storage backend. This approach provides scalability, cost-effectiveness, and decouples file storage from the database.

### Database Schema

The `file_record` table contains the following columns:

- `file_id` (primary key): Unique identifier for the file
- `display_name`: Human-readable name for the file
- `file_origin`: Origin/source of the file (enum)
- `file_type`: MIME type of the file
- `file_metadata`: Additional metadata as JSON
- `bucket_name`: External storage bucket/container name
- `object_key`: External storage object key/path
- `created_at`: Timestamp when the file was created
- `updated_at`: Timestamp when the file was last updated

## Storage Backends

The backend is selected via the `FILE_STORE_BACKEND` environment variable:

| Value | Backend | Description |
|---|---|---|
| `s3` (default) | S3-compatible | AWS S3, MinIO, Digital Ocean Spaces, etc. |
| `gcs` | Google Cloud Storage | Native GCS with ADC/Workload Identity support |
| `azure` | Azure Blob Storage | Native Azure with Workload Identity / managed identity support |
| `postgres` | PostgreSQL Large Objects | No external storage service required |

## Configuration

### AWS S3

```bash
FILE_STORE_BACKEND=s3
S3_FILE_STORE_BUCKET_NAME=your-bucket-name  # Defaults to 'onyx-file-store-bucket'
S3_FILE_STORE_PREFIX=onyx-files  # Optional, defaults to 'onyx-files'

# AWS credentials (use one of these methods):
# 1. Environment variables
S3_AWS_ACCESS_KEY_ID=your-access-key
S3_AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_REGION_NAME=us-east-2  # Optional, defaults to 'us-east-2'

# 2. IAM roles (recommended for EC2/ECS deployments)
# No additional configuration needed if using IAM roles
```

### MinIO

```bash
FILE_STORE_BACKEND=s3
S3_FILE_STORE_BUCKET_NAME=your-bucket-name
S3_ENDPOINT_URL=http://localhost:9000  # MinIO endpoint
S3_AWS_ACCESS_KEY_ID=minioadmin
S3_AWS_SECRET_ACCESS_KEY=minioadmin
AWS_REGION_NAME=us-east-1  # Any region name
S3_VERIFY_SSL=false  # Optional, defaults to false
```

### Digital Ocean Spaces

```bash
FILE_STORE_BACKEND=s3
S3_FILE_STORE_BUCKET_NAME=your-space-name
S3_ENDPOINT_URL=https://nyc3.digitaloceanspaces.com
S3_AWS_ACCESS_KEY_ID=your-spaces-key
S3_AWS_SECRET_ACCESS_KEY=your-spaces-secret
AWS_REGION_NAME=nyc3
```

### Google Cloud Storage (GCS)

```bash
FILE_STORE_BACKEND=gcs
GCS_FILE_STORE_BUCKET_NAME=your-bucket-name    # Required
GCS_FILE_STORE_PREFIX=onyx-files               # Optional, defaults to 'onyx-files'
GCS_PROJECT_ID=your-gcp-project                # Optional, auto-detected via ADC

# Authentication (use one of these methods, in priority order):

# 1. Workload Identity / ADC (recommended for GKE, Cloud Run, Compute Engine)
#    No additional configuration needed. Credentials are resolved automatically
#    from the environment: GKE Workload Identity, instance metadata server,
#    GOOGLE_APPLICATION_CREDENTIALS env var, or gcloud CLI.

# 2. Service account key file
GCS_SERVICE_ACCOUNT_KEY_PATH=/path/to/service-account-key.json

# 3. Inline service account JSON (for environments where file mounts are impractical)
GCS_SERVICE_ACCOUNT_KEY_JSON='{"type":"service_account","project_id":"...","private_key":"..."}'
```

**Required IAM permissions:**

On the GCS bucket (object operations + existence check):
- `storage.objects.create`, `storage.objects.get`, `storage.objects.delete` (CRUD operations)
- `storage.buckets.get` (for `initialize()` to check bucket existence)

At the project level (only if `initialize()` should auto-create the bucket):
- `storage.buckets.create`

The predefined role `roles/storage.objectAdmin` (granted on the bucket) covers all object operations. For initial bucket creation, `roles/storage.admin` at the project level is needed.

### Azure Blob Storage

```bash
FILE_STORE_BACKEND=azure
AZURE_FILE_STORE_CONTAINER_NAME=your-container-name  # Required
AZURE_FILE_STORE_PREFIX=onyx-files                   # Optional, defaults to 'onyx-files'
AZURE_STORAGE_ACCOUNT_NAME=yourstorageaccount        # Required unless using a connection string
# Optional endpoint override — derived from the account name when unset.
# Set explicitly for Azurite or sovereign clouds (e.g. *.blob.core.usgovcloudapi.net):
AZURE_STORAGE_ACCOUNT_URL=https://yourstorageaccount.blob.core.windows.net

# Authentication (use one of these methods, in priority order):

# 1. Connection string
AZURE_STORAGE_CONNECTION_STRING='DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net'

# 2. Account key (requires AZURE_STORAGE_ACCOUNT_NAME)
AZURE_STORAGE_ACCOUNT_KEY=your-account-key

# 3. DefaultAzureCredential (recommended for AKS)
#    No additional configuration needed. Credentials are resolved automatically
#    from the environment: AKS Workload Identity, managed identity, environment
#    credentials (AZURE_CLIENT_ID/AZURE_TENANT_ID/etc.), or local `az login`.
```

**Required RBAC role:** `Storage Blob Data Contributor` on the storage account (or container)
covers all object operations. For `initialize()` to auto-create the container, the identity
also needs container-create rights, which the account-scoped role includes.

**Local development:** [Azurite](https://learn.microsoft.com/en-us/azure/storage/common/storage-use-azurite)
(`mcr.microsoft.com/azure-storage/azurite`) emulates Azure Blob Storage, playing the role MinIO
plays for S3. Use its well-known development connection string.

### Other S3-Compatible Services

The file store works with any S3-compatible service. Simply configure:
- `S3_FILE_STORE_BUCKET_NAME`: Your bucket/container name
- `S3_ENDPOINT_URL`: The service endpoint URL
- `S3_AWS_ACCESS_KEY_ID` and `S3_AWS_SECRET_ACCESS_KEY`: Your credentials
- `AWS_REGION_NAME`: The region (any valid region name)

### PostgreSQL Large Objects

```bash
FILE_STORE_BACKEND=postgres
# No additional configuration needed — files are stored directly in PostgreSQL.
```

## Implementation

The system provides four implementations of the abstract `FileStore` interface:

- `S3BackedFileStore` (`file_store.py`): For S3-compatible storage (AWS S3, MinIO, etc.)
- `GCSBackedFileStore` (`gcs_file_store.py`): For Google Cloud Storage with native ADC support
- `AzureBlobBackedFileStore` (`azure_blob_file_store.py`): For Azure Blob Storage with DefaultAzureCredential support
- `PostgresBackedFileStore` (`postgres_file_store.py`): For PostgreSQL Large Objects

The factory function `get_default_file_store()` returns the appropriate implementation based on `FILE_STORE_BACKEND`. The database uses generic column names (`bucket_name`, `object_key`) to maintain compatibility across all backends.

### File Store Interface

The `FileStore` abstract base class defines the following methods:

- `initialize()`: Initialize the storage backend (create bucket if needed)
- `has_file(file_id, file_origin, file_type)`: Check if a file exists
- `save_file(content, display_name, file_origin, file_type, file_metadata, file_id)`: Save a file
- `read_file(file_id, mode, use_tempfile)`: Read file content
- `read_file_record(file_id)`: Get file metadata from database
- `get_file_size(file_id)`: Get file size in bytes
- `delete_file(file_id)`: Delete a file and its metadata
- `get_file_with_mime_type(file_id)`: Get file with parsed MIME type
- `change_file_id(old_file_id, new_file_id)`: Rename a file
- `list_files_by_prefix(prefix)`: List files matching a prefix

## Presigned URLs

A presigned URL lets a client without storage credentials (for example a Craft
sandbox node) read or write one object directly. The api_server signs each URL
for one object and one method. The default TTL is 5 minutes and the maximum is
15 minutes (`FILE_STORE_PRESIGN_DEFAULT_TTL_SECONDS` and
`FILE_STORE_PRESIGN_MAX_TTL_SECONDS` in `app_configs.py`).

- `presign_download(file_id)` returns a GET request for an existing file.
- `presign_upload(display_name, file_origin, file_type, size, sha256)` reserves a
  file ID and returns a PUT request and a pending upload ID. It writes no
  `file_record` row. The pending upload is kept in the cache backend.
- Uploads are at most 5 GiB (`FILE_STORE_PRESIGN_MAX_UPLOAD_BYTES`), the largest
  single S3 PUT. Azure allows at most 5000 MiB, the largest single Put Blob.
- `presign_download` checks no user. Authorize the caller before you hand out
  the URL.
- `finalize_presigned_upload(pending_upload_id)` checks the size and SHA-256 of
  the uploaded object, then writes the `file_record` row. On a mismatch it
  deletes the object and raises `PresignedUploadVerificationError`.

The client must send every header in `PresignedRequest.headers` unchanged.
An upload object that is never finalized stays in the bucket without a record.

Only the cloud backends (S3, GCS, Azure) have presigned URLs. These methods are
on the `PresignableFileStore` subclass, not on `FileStore`, so callers check
`isinstance(store, PresignableFileStore)`.
The PostgreSQL backend has none. GCS and Azure raise
`PresignedUrlsNotSupportedError` when their credentials are not allowed to sign.
S3 signs locally, so a credential problem only shows when the client uses the
URL. Temporary errors (network, metadata server) are raised as they are.

### S3 and S3-compatible stores

- URLs use SigV4. The signature covers `Content-Length` and
  `x-amz-checksum-sha256`, so an upload URL accepts only the expected bytes.
  Finalize reads the SHA-256 from a HEAD request.
- IAM roles (IRSA) and other session credentials work. A URL stops working when
  the session credentials that signed it expire, even before its TTL.
- The URL host comes from `S3_ENDPOINT_URL`, and the host is part of the
  signature. Clients must reach the store at that same host. If clients reach
  the store at a different host than the api_server does, the URLs do not work,
  and a proxy that changes the `Host` header breaks the signature.
- Legacy MinIO store (`S3_LEGACY_ENDPOINT_URL`): a presigned PUT skips the dual
  write. Finalize marks the object out of sync, and the replay loop
  (`legacy_copy --replay`) copies it into MinIO within a few minutes. A file
  that is only in the legacy store gets no download URL.

### Google Cloud Storage

- URLs use V4 signing. A service account key file signs locally.
- Workload Identity or the metadata server (no key file) signs through the IAM
  Credentials `signBlob` API. Grant `roles/iam.serviceAccountTokenCreator` on
  the service account to the service account itself. Without it, the presign
  methods raise `PresignedUrlsNotSupportedError`.
- Signing needs an IAM service account. A direct Workload Identity principal
  (`principal://...`, the default of `deployment/terraform/modules/gcp`) has
  none, so it cannot sign. Map the Kubernetes service account to an IAM service
  account first. That module does this when `craft_sandbox_runtime =
  "firecracker"`.
- An upload URL signs `x-goog-if-generation-match: 0` and
  `x-goog-content-length-range`, so it creates the object once and with the
  expected size. GCS keeps no SHA-256, so finalize reads the object once and
  hashes it.

### Azure Blob Storage

- An account key (`AZURE_STORAGE_ACCOUNT_KEY`, or `AccountKey` in the connection
  string) signs a service SAS.
- Workload Identity or a managed identity (`DefaultAzureCredential`) signs a
  user delegation SAS. No account key is needed, so shared key access can stay
  off. The store gets a delegation key for 1 hour and keeps it until less than
  the maximum TTL remains.
- The identity needs `Storage Blob Data Contributor` on the storage account.
  That role has `generateUserDelegationKey` and the blob read and write rights
  that the SAS uses. Assign it at the account scope: a container-scope
  assignment cannot get a delegation key. Without it, the presign methods raise
  `PresignedUrlsNotSupportedError`. `deployment/terraform/modules/azure/aks`
  assigns this role.
- Each SAS is for one blob, with one permission (`r` for downloads, `c` for
  uploads) and a short expiry. Create permission cannot overwrite a blob. A SAS
  cannot limit the size or content, so finalize checks the size and reads the
  blob once to hash it.

## Usage Example

```python
from onyx.file_store.file_store import get_default_file_store
from onyx.configs.constants import FileOrigin

# Get the configured file store
file_store = get_default_file_store()

# Initialize the storage backend (creates bucket if needed)
file_store.initialize()

# Save a file
with open("example.pdf", "rb") as f:
    file_id = file_store.save_file(
        content=f,
        display_name="Important Document.pdf",
        file_origin=FileOrigin.OTHER,
        file_type="application/pdf",
        file_metadata={"department": "engineering", "version": "1.0"},
    )

# Check if a file exists
exists = file_store.has_file(
    file_id=file_id, file_origin=FileOrigin.OTHER, file_type="application/pdf"
)

# Read a file
file_content = file_store.read_file(file_id)

# Read file with temporary file (for large files)
file_content = file_store.read_file(file_id, use_tempfile=True)

# Get file metadata
file_record = file_store.read_file_record(file_id)

# Get file with MIME type detection
file_with_mime = file_store.get_file_with_mime_type(file_id)

# Delete a file
file_store.delete_file(file_id)
```

## Blob Connector: GCS Authentication

The blob storage connector (`backend/onyx/connectors/blob/connector.py`) also supports native GCS authentication via the admin UI. When creating a Google Cloud Storage connector, three auth methods are available:

- **HMAC Access Key**: S3-compatible HMAC credentials (existing behavior)
- **Service Account JSON**: Paste a GCP service account JSON key
- **Workload Identity / ADC**: No credentials needed; uses the pod's service account

**Security note:** When using ADC/Workload Identity in the blob connector, the connector inherits the permissions of the pod's service account. If the SA has access to buckets beyond the intended connector target (e.g., the internal file store bucket), an admin could point a connector at those buckets. This mirrors the existing S3 "Assume Role" auth method. Mitigation is IAM scoping at the infrastructure level: scope the pod's service account to only the buckets it should access.

## Initialization

When deploying the application, ensure that:

1. The storage service is accessible from the application
2. Credentials are properly configured for the chosen backend
3. The bucket exists or the service account has permissions to create it
4. Call `file_store.initialize()` during application startup to ensure the bucket exists

The file store will automatically create the bucket if it doesn't exist and the credentials have sufficient permissions.
