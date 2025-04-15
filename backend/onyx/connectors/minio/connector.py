from datetime import datetime
from datetime import timezone
from io import BytesIO
import os
from typing import Any

import boto3
from botocore.client import BaseClient

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError, TextSection
from onyx.connectors.models import Document
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.utils.logger import setup_logger


logger = setup_logger()


class MinioConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        bucket_name: str,
        prefix: str = "",
        batch_size: int = INDEX_BATCH_SIZE
    ) -> None:
        self.bucket_name = bucket_name
        self.prefix = prefix if not prefix or prefix.endswith("/") else prefix + "/"
        self.batch_size = batch_size
        self.minio_client: BaseClient | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        if credentials["aws_access_key_id"] and credentials["aws_secret_access_key"]:
            session = boto3.Session(
                aws_access_key_id=credentials["aws_access_key_id"],
                aws_secret_access_key=credentials["aws_secret_access_key"]
            )
        elif credentials["profile_name"]:
            session = boto3.Session(profile_name=credentials["profile_name"])
        else:
            session = boto3.Session()

        self.minio_client = session.client('s3')
        return None

    def _download_object(self, key: str) -> bytes:
        """Download a single object from S3."""
        if self.minio_client is None:
            raise ConnectorMissingCredentialError("S3")
        object = self.minio_client.get_object(Bucket=self.bucket_name, Key=key)
        return object['Body'].read()

    def _get_presigned_url(self, key: str) -> str:
        """Create a presigned URL for an S3 object."""
        if self.minio_client is None:
            raise ConnectorMissingCredentialError("S3")

        url = self.minio_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': self.bucket_name,
                'Key': key
            },
            ExpiresIn=0
        )

        return url

    def _yield_objects(
        self,
        start: datetime,
        end: datetime,
    ) -> GenerateDocumentsOutput:
        """Yield objects in batches from a specified S3 bucket."""
        if self.minio_client is None:
            raise ConnectorMissingCredentialError("S3")

        paginator = self.minio_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=self.bucket_name, Prefix=self.prefix)

        batch: list[Document] = []
        for page in pages:
            if 'Contents' not in page:
                continue

            for obj in page['Contents']:
                if obj['Key'].endswith('/'):
                    continue

                last_modified = obj['LastModified'].replace(tzinfo=timezone.utc)

                if not start <= last_modified <= end:
                    continue

                downloaded_file = self._download_object(obj['Key'])
                link = self._get_presigned_url(obj['Key'])
                name = os.path.basename(obj['Key'])
                try:
                    text = extract_file_text(
                        BytesIO(downloaded_file),
                        name,
                        break_on_unprocessable=False,
                    )
                    batch.append(
                        Document(
                            id=f"s3:{self.bucket_name}:{obj['Key']}",
                            sections=[TextSection(link=link, text=text)],
                            source=DocumentSource.MINIO,
                            semantic_identifier=name,
                            doc_updated_at=last_modified,
                            metadata={"type": "article"},
                        )
                    )
                    if len(batch) == self.batch_size:
                        yield batch
                        batch = []
                except Exception as e:
                    logger.exception(
                        f"Error decoding object {obj['Key']} as UTF-8: {e}"
                    )

            if batch:
                yield batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._yield_objects(
            start=datetime(1970, 1, 1, tzinfo=timezone.utc),
            end=datetime.now(timezone.utc)
        )

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        if self.minio_client is None:
            raise ConnectorMissingCredentialError("S3")

        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)

        for batch in self._yield_objects(start_datetime, end_datetime):
            yield batch

        return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('bucket_name')
    args = parser.parse_args()

    connector = MinioConnector(bucket_name=args.bucket_name)
    connector.load_credentials({})
    document_batches = connector.load_from_state()
    print(next(document_batches))