from minio import Minio
from datetime import timedelta
import datetime
import json
import os
import io
import base64
from apscheduler.schedulers.background import BackgroundScheduler

from onyx.tools.tool_implementations.resume import config
from onyx.utils.logger import setup_logger

scheduler = BackgroundScheduler()
scheduler.start()
DOWNLOAD_FOLDER = 'downloads'


logger = setup_logger()

def minio_get_client():
    client = Minio(
        f'{config.minio_host}:{config.minio_port}',
        access_key=config.minio_access_key,
        secret_key=config.minio_secret_key,
        secure=True
    )
    return client


def minio_get_policy(bucket_name):
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": "*"},
                "Action": [
                    "s3:GetBucketLocation",
                    "s3:ListBucket",
                    "s3:ListBucketMultipartUploads",
                ],
                "Resource": f"arn:aws:s3:::{bucket_name}",
            },
            {
                "Effect": "Allow",
                "Principal": {"AWS": "*"},
                "Action": [
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:ListMultipartUploadParts",
                    "s3:AbortMultipartUpload",
                ],
                "Resource": f"arn:aws:s3:::{bucket_name}/*",
            },
        ],
    }
    return policy


def minio_get_object_template(template_file_name):
    client = minio_get_client()
    policy = minio_get_policy(config.bucket_name)
    client.set_bucket_policy(config.bucket_name, json.dumps(policy))

    file_path = os.path.join(DOWNLOAD_FOLDER, template_file_name)
    client.fget_object(config.bucket_name, template_file_name, file_path)


def minio_get_bytes(file_name):
    client = minio_get_client()
    policy = minio_get_policy(config.bucket_name)
    client.set_bucket_policy(config.bucket_name, json.dumps(policy))

    file_bytes = client.get_object(config.bucket_name, file_name)
    return file_bytes


def minio_delete_object(file_name):
    client = minio_get_client()
    policy = minio_get_policy(config.bucket_name)
    client.set_bucket_policy(config.bucket_name, json.dumps(policy))

    client.remove_object(config.bucket_name, file_name)


def minio_put_bytes(file_name, file_content):
    client = minio_get_client()
    policy = minio_get_policy(config.bucket_name)
    client.set_bucket_policy(config.bucket_name, json.dumps(policy))
    file_bytes = file_content.encode()
    file_io = io.BytesIO(file_bytes)
    client.put_object(
        config.bucket_name,
        file_name,
        file_io,
        length=len(file_bytes)
    )
    scheduler.add_job(
        minio_delete_object,
        'date',
        run_date=datetime.datetime.now() + datetime.timedelta(minutes=5),
        args=[file_name]
    )
    return file_name, file_content


def minio_put_template_bytes(file_name, file_content):
    client = minio_get_client()
    policy = minio_get_policy(config.bucket_name)
    client.set_bucket_policy(config.bucket_name, json.dumps(policy))

    base64_string = file_content.decode('utf-8')

    while len(base64_string) % 4 != 0:
        base64_string += '='
    decoded_bytes = base64.b64decode(base64_string)
    byte_stream = io.BytesIO(decoded_bytes)
    client.put_object(
        config.bucket_name,
        file_name,
        byte_stream,
        length=len(decoded_bytes)
    )
    return file_name, file_content


def minio_put_object(file_name):
    client = minio_get_client()
    policy = minio_get_policy(config.bucket_name)
    client.set_bucket_policy(config.bucket_name, json.dumps(policy))

    with open(file_name, 'rb') as file_data:
        file_size = os.stat(file_name).st_size
        client.put_object(
            config.bucket_name,
            file_name,
            file_data,
            length=file_size
        )
    scheduler.add_job(
        minio_delete_object,
        'date',
        run_date=datetime.datetime.now() + datetime.timedelta(hours=48),
        args=[file_name])


def minio_get_object_url(file_name):
    client = minio_get_client()
    policy = minio_get_policy(config.bucket_name)
    client.set_bucket_policy(config.bucket_name, json.dumps(policy))

    url = client.get_presigned_url(
        "GET",
        config.bucket_name,
        file_name,
        expires=timedelta(hours=48),
    )
    return url
