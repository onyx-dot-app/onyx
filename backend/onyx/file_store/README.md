# Onyx File Store

The Onyx file store provides a unified interface for storing files and large binary objects. It supports multiple storage backends including PostgreSQL large objects and external storage systems like AWS S3, MinIO, Azure Blob Storage, and other S3-compatible services.

## Architecture

The file store uses a single database table (`file_store`) that can handle both PostgreSQL large objects and external storage references. This unified approach allows for easy migration between storage backends and provides flexibility in deployment configurations.

### Database Schema

The `file_store` table contains the following columns:

- `file_name` (primary key): Unique identifier for the file
- `display_name`: Human-readable name for the file
- `file_origin`: Origin/source of the file (enum)
- `file_type`: MIME type of the file
- `file_metadata`: Additional metadata as JSON
- `lobj_oid`: PostgreSQL large object ID (nullable, for PostgreSQL storage)
- `bucket_name`: External storage bucket/container name (nullable, for external storage)
- `object_key`: External storage object key/path (nullable, for external storage)
- `created_at`: Timestamp when the file was created
- `updated_at`: Timestamp when the file was last updated

## Storage Backends

### PostgreSQL Large Objects (Default)

Uses PostgreSQL's native large object storage. Files are stored directly in the database as large objects and referenced by their OID.

**Pros:**
- No additional infrastructure required
- ACID compliance
- Backup consistency with database

**Cons:**
- Database size growth
- Memory usage during file operations
- Limited scalability for large files

### External Storage (S3-Compatible)

Stores files in external storage systems while keeping metadata in the database.

**Pros:**
- Scalable storage
- Cost-effective for large files
- CDN integration possible
- Decoupled from database

**Cons:**
- Additional infrastructure required
- Eventual consistency considerations
- Network dependency

## Configuration

### AWS S3

```bash
S3_FILE_STORE_BUCKET_NAME=your-bucket-name
S3_FILE_STORE_PREFIX=onyx-files  # Optional, defaults to 'onyx-files'

# AWS credentials (use one of these methods):
# 1. Environment variables
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_REGION_NAME=us-east-2  # Optional, defaults to 'us-east-2'

# 2. IAM roles (recommended for EC2/ECS deployments)
# No additional configuration needed if using IAM roles
```

### MinIO

```bash
S3_FILE_STORE_BUCKET_NAME=your-bucket-name
S3_ENDPOINT_URL=http://localhost:9000  # MinIO endpoint
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin
AWS_REGION_NAME=us-east-1  # Any region name
S3_VERIFY_SSL=false  # Optional, for local development
```

### Digital Ocean Spaces

```bash
S3_FILE_STORE_BUCKET_NAME=your-space-name
S3_ENDPOINT_URL=https://nyc3.digitaloceanspaces.com
AWS_ACCESS_KEY_ID=your-spaces-key
AWS_SECRET_ACCESS_KEY=your-spaces-secret
AWS_REGION_NAME=nyc3
```

## Implementation

The system uses a unified `FileStore` model that supports both storage types with generic column names (`bucket_name`, `object_key`) instead of S3-specific names. This allows future support for Azure Blob Storage, Google Cloud Storage, and other backends.

### File Store Interface

All storage backends implement the `FileStore` abstract base class with methods for file operations like `save_file()`, `read_file()`, `delete_file()`, etc.

### Migration

When migrating between storage backends, existing files continue to work seamlessly. The system detects which storage backend a file uses based on the database record.

## Usage Example

```python
from onyx.file_store.file_store import get_default_file_store
from onyx.configs.constants import FileOrigin

# Get the configured file store
file_store = get_default_file_store(db_session)

# Save a file
with open("example.pdf", "rb") as f:
    file_store.save_file(
        file_name="document-123",
        content=f,
        display_name="Important Document.pdf",
        file_origin=FileOrigin.OTHER,
        file_type="application/pdf"
    )

# Read a file
file_content = file_store.read_file("document-123")

# Delete a file
file_store.delete_file("document-123")
``` 