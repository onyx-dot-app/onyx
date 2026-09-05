# RustFS connector

The RustFS connector indexes objects from an S3-compatible RustFS bucket. It
uses Onyx's existing file extraction and indexing pipeline.

## Configure

Create a RustFS connector in the Onyx administration UI and provide:

- **Endpoint URL**: The RustFS S3 API endpoint, including `http://` or
  `https://`.
- **Bucket Name**: The source bucket.
- **Prefix**: An optional object-key prefix.
- **Region**: The signing region. The default is `us-east-1`.
- **Access Key** and **Secret Key**: Credentials for a dedicated RustFS user.

The connector uses path-style S3 addressing. The endpoint must be reachable
from the Onyx background workers.

Onyx applies its outbound-request security policy to the endpoint. The default
policy blocks private network addresses. An operator can relax connector URL
validation when RustFS runs on a trusted private network. Link-local and cloud
metadata addresses remain blocked.

## Permissions

Use credentials with read-only access to the configured bucket and prefix. The
equivalent S3 permissions are:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": ["arn:aws:s3:::documents"],
      "Condition": {
        "StringLike": {"s3:prefix": ["research/*"]}
      }
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": ["arn:aws:s3:::documents/research/*"]
    }
  ]
}
```

The connector does not require write or delete permission.

## Indexing behavior

The connector lists objects under the configured prefix. Initial indexing
processes all matching objects. Scheduled polling uses each object's
`LastModified` value to process new and modified objects. Folder markers ending
in `/` are ignored.

Object links are not exposed because RustFS endpoints and buckets are commonly
private. Onyx still provides citations to the indexed document.

Objects larger than `BLOB_STORAGE_SIZE_THRESHOLD` are skipped. Repeated object
listing can become expensive for very large prefixes.

## Test

Run the focused connector tests from the repository root:

```bash
uv run pytest -q \
  backend/tests/unit/onyx/connectors/blob/test_blob_connector_rustfs.py \
  backend/tests/unit/onyx/connectors/test_connector_factory.py
```
