"""Unit tests for `SnapshotEgressPolicy`.

Pins the wire-level snapshot key layout
(`{tenant_id}/snapshots/{session_id}/{snapshot_id}.tar.gz`) and both S3
addressing modes. The security-relevant cases are the rejections: another
tenant's prefix, an attacker bucket/host, or a non-snapshot key must NOT be
opted into uncapped streaming.
"""

from __future__ import annotations

import os

import pytest

from onyx.sandbox_proxy import snapshot_egress
from onyx.sandbox_proxy.snapshot_egress import SnapshotEgressPolicy

_BUCKET = "onyx-sandbox-snapshots"
_TENANT = "tenant_acme"

# Hardcoded spec: path-style puts the bucket in the path; vhost in the host.
_PATH_STYLE_KEY = (_BUCKET, _TENANT, "snapshots", "sess-1", "snap-1.tar.gz")
_VHOST_KEY = (_TENANT, "snapshots", "sess-1", "snap-1.tar.gz")


def _path_style() -> SnapshotEgressPolicy:
    return SnapshotEgressPolicy(
        bucket=_BUCKET, endpoint_host="release-minio", endpoint_port=9000
    )


def _vhost() -> SnapshotEgressPolicy:
    return SnapshotEgressPolicy(bucket=_BUCKET, endpoint_host=None, endpoint_port=None)


# ---------------------------------------------------------------------------
# Path-style (custom endpoint / MinIO)
# ---------------------------------------------------------------------------


def test_path_style_streams_tenant_snapshot_upload() -> None:
    assert _path_style().should_stream(
        host="release-minio",
        port=9000,
        path_components=_PATH_STYLE_KEY,
        tenant_id=_TENANT,
    )


def test_path_style_rejects_other_tenant_prefix() -> None:
    """Path-style MinIO shares one host across buckets, so the tenant-prefix
    check is the load-bearing control."""
    assert not _path_style().should_stream(
        host="release-minio",
        port=9000,
        path_components=(_BUCKET, "tenant_evil", "snapshots", "x", "y.tar.gz"),
        tenant_id=_TENANT,
    )


def test_path_style_rejects_non_snapshot_key() -> None:
    assert not _path_style().should_stream(
        host="release-minio",
        port=9000,
        path_components=(_BUCKET, _TENANT, "secrets", "exfil.bin"),
        tenant_id=_TENANT,
    )


def test_path_style_rejects_other_bucket() -> None:
    assert not _path_style().should_stream(
        host="release-minio",
        port=9000,
        path_components=("other-bucket", _TENANT, "snapshots", "x.tar.gz"),
        tenant_id=_TENANT,
    )


def test_path_style_rejects_wrong_host() -> None:
    assert not _path_style().should_stream(
        host="attacker.internal",
        port=9000,
        path_components=_PATH_STYLE_KEY,
        tenant_id=_TENANT,
    )


def test_path_style_rejects_wrong_port() -> None:
    assert not _path_style().should_stream(
        host="release-minio",
        port=9999,
        path_components=_PATH_STYLE_KEY,
        tenant_id=_TENANT,
    )


# ---------------------------------------------------------------------------
# Virtual-hosted (real AWS S3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        f"{_BUCKET}.s3.amazonaws.com",
        f"{_BUCKET}.s3.us-east-2.amazonaws.com",
        f"{_BUCKET}.s3-us-west-1.amazonaws.com",
    ],
)
def test_vhost_streams_tenant_snapshot_upload(host: str) -> None:
    assert _vhost().should_stream(
        host=host,
        port=443,
        path_components=_VHOST_KEY,
        tenant_id=_TENANT,
    )


def test_vhost_rejects_attacker_bucket() -> None:
    """A broad `*.s3.amazonaws.com` suffix would match this; the
    bucket-pinned check must not."""
    assert not _vhost().should_stream(
        host="attacker-bucket.s3.amazonaws.com",
        port=443,
        path_components=_VHOST_KEY,
        tenant_id=_TENANT,
    )


def test_vhost_rejects_non_s3_amazonaws_host() -> None:
    assert not _vhost().should_stream(
        host=f"{_BUCKET}.execute-api.us-east-1.amazonaws.com",
        port=443,
        path_components=_VHOST_KEY,
        tenant_id=_TENANT,
    )


def test_vhost_rejects_other_tenant_prefix() -> None:
    assert not _vhost().should_stream(
        host=f"{_BUCKET}.s3.amazonaws.com",
        port=443,
        path_components=("tenant_evil", "snapshots", "x.tar.gz"),
        tenant_id=_TENANT,
    )


# ---------------------------------------------------------------------------
# host_matches — cheap pre-check that gates the (DB-touching) resolve
# ---------------------------------------------------------------------------


def test_host_matches_pathstyle() -> None:
    policy = _path_style()
    assert policy.host_matches("release-minio")
    assert not policy.host_matches("slack.com")


def test_host_matches_vhost() -> None:
    policy = _vhost()
    assert policy.host_matches(f"{_BUCKET}.s3.amazonaws.com")
    assert not policy.host_matches("attacker-bucket.s3.amazonaws.com")
    assert not policy.host_matches("slack.com")


# ---------------------------------------------------------------------------
# from_env — endpoint precedence + addressing-mode selection
# ---------------------------------------------------------------------------


def test_from_env_path_style_when_endpoint_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(snapshot_egress, "SANDBOX_S3_BUCKET", _BUCKET)
    monkeypatch.setattr(
        os, "environ", {"AWS_ENDPOINT_URL": "http://release-minio:9000"}
    )
    policy = SnapshotEgressPolicy.from_env()
    assert policy == SnapshotEgressPolicy(
        bucket=_BUCKET, endpoint_host="release-minio", endpoint_port=9000
    )


def test_from_env_vhost_when_no_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(snapshot_egress, "SANDBOX_S3_BUCKET", _BUCKET)
    monkeypatch.setattr(os, "environ", {})
    policy = SnapshotEgressPolicy.from_env()
    assert policy == SnapshotEgressPolicy(
        bucket=_BUCKET, endpoint_host=None, endpoint_port=None
    )


def test_from_env_prefers_aws_endpoint_over_s3_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(snapshot_egress, "SANDBOX_S3_BUCKET", _BUCKET)
    monkeypatch.setattr(
        os,
        "environ",
        {
            "AWS_ENDPOINT_URL": "http://cluster-minio:9000",
            "S3_ENDPOINT_URL": "http://localhost:9004",
        },
    )
    policy = SnapshotEgressPolicy.from_env()
    assert policy is not None
    assert policy.endpoint_host == "cluster-minio"


def test_from_env_none_without_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(snapshot_egress, "SANDBOX_S3_BUCKET", "")
    monkeypatch.setattr(os, "environ", {})
    assert SnapshotEgressPolicy.from_env() is None
