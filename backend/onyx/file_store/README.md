# Onyx File Store

The Onyx file store provides a unified interface for storing files and large binary objects. It supports three storage backends: S3-compatible storage (AWS S3, MinIO, Digital Ocean Spaces, etc.), Google Cloud Storage (GCS), and PostgreSQL Large Objects.

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

The system provides three implementations of the abstract `FileStore` interface:

- `S3BackedFileStore` (`file_store.py`): For S3-compatible storage (AWS S3, MinIO, etc.)
- `GCSBackedFileStore` (`gcs_file_store.py`): For Google Cloud Storage with native ADC support
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
        file_metadata={"department": "engineering", "version": "1.0"}
    )

# Check if a file exists
exists = file_store.has_file(
    file_id=file_id,
    file_origin=FileOrigin.OTHER,
    file_type="application/pdf"
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
