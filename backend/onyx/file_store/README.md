# Onyx File Store

The Onyx file store provides a unified interface for storing files and large binary objects in S3-compatible storage systems. It supports AWS S3, MinIO, Azure Blob Storage, Digital Ocean Spaces, and other S3-compatible services.

## Architecture

The file store uses a single database table (`file_record`) to store file metadata while the actual file content is stored in external S3-compatible storage. This approach provides scalability, cost-effectiveness, and decouples file storage from the database.

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

## Storage Backend

### S3-Compatible Storage

Stores files in external S3-compatible storage systems while keeping metadata in the database.

**Pros:**
- Scalable storage
- Cost-effective for large files
- CDN integration possible
- Decoupled from database
- Wide ecosystem support

**Cons:**
- Additional infrastructure required
- Network dependency
- Eventual consistency considerations

## Configuration

All configuration is handled via environment variables. The system requires S3-compatible storage to be configured.

### AWS S3

```bash
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
S3_FILE_STORE_BUCKET_NAME=your-bucket-name
S3_ENDPOINT_URL=http://localhost:9000  # MinIO endpoint
S3_AWS_ACCESS_KEY_ID=minioadmin
S3_AWS_SECRET_ACCESS_KEY=minioadmin
AWS_REGION_NAME=us-east-1  # Any region name
S3_VERIFY_SSL=false  # Optional, defaults to false
```

### Digital Ocean Spaces

```bash
S3_FILE_STORE_BUCKET_NAME=your-space-name
S3_ENDPOINT_URL=https://nyc3.digitaloceanspaces.com
S3_AWS_ACCESS_KEY_ID=your-spaces-key
S3_AWS_SECRET_ACCESS_KEY=your-spaces-secret
AWS_REGION_NAME=nyc3
```

### Other S3-Compatible Services

The file store works with any S3-compatible service. Simply configure:
- `S3_FILE_STORE_BUCKET_NAME`: Your bucket/container name
- `S3_ENDPOINT_URL`: The service endpoint URL
- `S3_AWS_ACCESS_KEY_ID` and `S3_AWS_SECRET_ACCESS_KEY`: Your credentials
- `AWS_REGION_NAME`: The region (any valid region name)

## Implementation

The system uses the `S3BackedFileStore` class that implements the abstract `FileStore` interface. The database uses generic column names (`bucket_name`, `object_key`) to maintain compatibility with different S3-compatible services.

### File Store Interface

The `FileStore` abstract base class defines the following methods:

- `initialize()`: Initialize the storage backend (create bucket if needed)
- `has_file(file_id, file_origin, file_type)`: Check if a file exists
- `save_file(content, display_name, file_origin, file_type, file_metadata, file_id)`: Save a file
- `read_file(file_id, mode, use_tempfile)`: Read file content
- `read_file_record(file_id)`: Get file metadata from database
- `delete_file(file_id)`: Delete a file and its metadata
- `get_file_with_mime_type(filename)`: Get file with parsed MIME type

## Usage Example

```python
from onyx.file_store.file_store import get_default_file_store
from onyx.configs.constants import FileOrigin

# Get the configured file store
file_store = get_default_file_store(db_session)

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

## Initialization

When deploying the application, ensure that:

1. The S3-compatible storage service is accessible
2. Credentials are properly configured
3. The bucket specified in `S3_FILE_STORE_BUCKET_NAME` exists or the service account has permissions to create it
4. Call `file_store.initialize()` during application startup to ensure the bucket exists

The file store will automatically create the bucket if it doesn't exist and the credentials have sufficient permissions.
 