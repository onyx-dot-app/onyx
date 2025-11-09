import os


minio_access_key = os.getenv("MINIOUSER")
minio_secret_key = os.getenv("MINIOPASSWORD")
minio_host = 'minio'
minio_port = '9000'
bucket_name = 'resume'
