from typing import TYPE_CHECKING

import boto3

from onyx.configs.app_configs import AWS_REGION_NAME

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client


def build_s3_client() -> "S3Client":
    """Build an S3 client using IAM roles (IRSA)"""
    return boto3.client("s3", region_name=AWS_REGION_NAME)
