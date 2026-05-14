"""S3 Files backend (Amazon S3 + S3 Files NFSv4 mount).

api_server writes skill bytes into the bucket via the S3 API. Sandbox
pods mount the same bucket as NFSv4 via the ``aws-efs-csi-driver`` and
read from ``/skills/`` directly. Per-tenant isolation is enforced by
S3 Files **access points** scoped to ``tenants/<tenant_id>/`` — each
sandbox pod's CSI volume references that tenant's access point ID, so
cross-tenant reads are blocked at the NFS layer.

Two boto3 clients are involved:
- ``s3``: ``put_object`` / ``delete_object`` writes.
- ``elasticfilesystem``: access point lifecycle. The S3 Files service
  reuses the EFS API namespace.

Naming convention enforced here:
- bucket layout:   ``s3://onyx-skills-{cluster}/[<prefix>/]tenants/<tenant_id>/...``
- access point:    one per tenant, root ``/tenants/<tenant_id>``
- access point identification: tagged ``onyx-tenant-id=<uuid>`` so
  ``ensure_access_point`` is a paginated Describe + tag filter (no DB
  cache needed — AWS is authoritative).

See docs/craft/features/skills/skills_plan.md §"How the actual cloud
deployment is wired" for the deployment topology.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import boto3
from botocore.exceptions import ClientError

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.backends.base import SkillFile
from onyx.skills.backends.base import SkillsManifestEntry
from onyx.skills.backends.base import validate_skill_files
from onyx.utils.logger import setup_logger

logger = setup_logger()

_ACCESS_POINT_TENANT_TAG = "onyx-tenant-id"
_BUILTINS_PREFIX = "_builtins"


class S3FilesSkillsBackend:
    """SkillsBackend backed by an S3 Files-linked bucket.

    Args:
        bucket: S3 bucket name (e.g. ``onyx-skills-craft-dev``). Must
            have versioning enabled (S3 Files requirement).
        key_prefix: Optional prefix within the bucket (e.g.
            ``dev/alice/`` for shared dev buckets). Empty in production.
        file_system_id: Optional ``fs-XXXX`` for the S3 Files file system.
            Required to call ``ensure_access_point``; unset when the
            api_server is in S3-write-only mode (no CSI mount).
        region_name: Region for the S3 + EFS clients.
    """

    def __init__(
        self,
        *,
        bucket: str,
        key_prefix: str = "",
        file_system_id: str | None = None,
        region_name: str | None = None,
    ) -> None:
        if not bucket:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "SKILLS_S3_BUCKET must be set for the s3_files skills backend",
            )
        self._bucket = bucket
        self._key_prefix = key_prefix.rstrip("/")
        self._file_system_id = file_system_id
        self._region_name = region_name
        self._s3: Any = boto3.client("s3", region_name=region_name)
        self._efs: Any | None = None  # lazy — only when access points used

    @property
    def bucket(self) -> str:
        return self._bucket

    @property
    def file_system_id(self) -> str | None:
        return self._file_system_id

    # ----- key layout ---------------------------------------------------

    def _key(self, *parts: str) -> str:
        base = (self._key_prefix + "/") if self._key_prefix else ""
        return base + "/".join(parts)

    def _builtin_key(self, slug: str, relative_path: str) -> str:
        return self._key(_BUILTINS_PREFIX, slug, relative_path)

    def _custom_key(self, tenant_id: str, slug: str, relative_path: str) -> str:
        return self._key("tenants", tenant_id, "_custom", slug, relative_path)

    def _manifest_key(self, tenant_id: str) -> str:
        return self._key("tenants", tenant_id, "_manifest.json")

    # ----- writes -------------------------------------------------------

    def write_builtin(self, slug: str, files: Iterable[SkillFile]) -> None:
        validated = validate_skill_files(files)
        for f in validated:
            self._put_object(self._builtin_key(slug, f.relative_path), f.content)

    def write_custom(
        self, tenant_id: str, slug: str, files: Iterable[SkillFile]
    ) -> None:
        validated = validate_skill_files(files)
        for f in validated:
            self._put_object(
                self._custom_key(tenant_id, slug, f.relative_path), f.content
            )

    def delete_custom(self, tenant_id: str, slug: str) -> None:
        prefix = self._key("tenants", tenant_id, "_custom", slug) + "/"
        self._delete_prefix(prefix)

    def write_manifest(
        self,
        tenant_id: str,
        builtin: Iterable[SkillsManifestEntry],
        custom: Iterable[SkillsManifestEntry],
    ) -> None:
        payload = json.dumps(
            {
                "builtin": [entry.model_dump(mode="json") for entry in builtin],
                "custom": [entry.model_dump(mode="json") for entry in custom],
            },
            sort_keys=True,
        ).encode("utf-8")
        self._put_object(self._manifest_key(tenant_id), payload)

    # ----- access points ------------------------------------------------

    def ensure_access_point(self, tenant_id: str) -> str:
        """Return the access point ID for ``tenant_id``, creating it on
        first call.

        Tag-keyed lookup so this is idempotent across api_server restarts
        without any local state. AWS is the authority — if we ever cached
        the mapping in Postgres we'd just be adding a place to keep in
        sync. For latency, callers can wrap this in an LRU if pod create
        ever becomes hot path (it currently isn't).
        """
        if not self._file_system_id:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "SKILLS_S3_FILES_FILE_SYSTEM_ID is required to manage access points",
            )

        existing = self._find_access_point(tenant_id)
        if existing is not None:
            return existing

        efs = self._get_efs_client()
        try:
            resp = efs.create_access_point(
                FileSystemId=self._file_system_id,
                ClientToken=f"onyx-skills-{tenant_id}",
                RootDirectory={
                    "Path": f"/tenants/{tenant_id}",
                    "CreationInfo": {
                        "OwnerUid": 1000,
                        "OwnerGid": 1000,
                        "Permissions": "0755",
                    },
                },
                PosixUser={"Uid": 1000, "Gid": 1000},
                Tags=[
                    {"Key": _ACCESS_POINT_TENANT_TAG, "Value": tenant_id},
                    {"Key": "managed-by", "Value": "onyx-skills"},
                ],
            )
        except ClientError as e:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                f"failed to create access point for tenant {tenant_id}: {e}",
            ) from e

        return str(resp["AccessPointId"])

    def delete_access_point(self, access_point_id: str) -> None:
        """Best-effort delete. Non-existent APs are treated as success so
        the caller can blindly clean up on tenant teardown."""
        efs = self._get_efs_client()
        try:
            efs.delete_access_point(AccessPointId=access_point_id)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("AccessPointNotFound", "FileSystemNotFound"):
                return
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                f"failed to delete access point {access_point_id}: {e}",
            ) from e

    def _find_access_point(self, tenant_id: str) -> str | None:
        efs = self._get_efs_client()
        try:
            paginator = efs.get_paginator("describe_access_points")
            for page in paginator.paginate(FileSystemId=self._file_system_id):
                for ap in page.get("AccessPoints", []) or []:
                    tags = {t["Key"]: t["Value"] for t in ap.get("Tags", []) or []}
                    if tags.get(_ACCESS_POINT_TENANT_TAG) == tenant_id:
                        return str(ap["AccessPointId"])
        except ClientError as e:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                f"failed to look up access point for tenant {tenant_id}: {e}",
            ) from e
        return None

    def _get_efs_client(self) -> Any:
        if self._efs is None:
            self._efs = boto3.client("efs", region_name=self._region_name)
        return self._efs

    # ----- s3 helpers ---------------------------------------------------

    def _put_object(self, key: str, body: bytes) -> None:
        try:
            self._s3.put_object(Bucket=self._bucket, Key=key, Body=body)
        except ClientError as e:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                f"failed to write s3://{self._bucket}/{key}: {e}",
            ) from e

    def _delete_prefix(self, prefix: str) -> None:
        paginator = self._s3.get_paginator("list_objects_v2")
        try:
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                contents = page.get("Contents") or []
                if not contents:
                    continue
                self._s3.delete_objects(
                    Bucket=self._bucket,
                    Delete={"Objects": [{"Key": e["Key"]} for e in contents]},
                )
        except ClientError as e:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                f"failed to delete s3://{self._bucket}/{prefix}*: {e}",
            ) from e
